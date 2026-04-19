"""
Ingestion node — runs once before all specialist agents.
 
Responsibilities:
    1. Fetch changed files from GitHub via MCP
    2. Filter out files whose SHA hasn't changed since the last run
    3. Run linters once across all changed files (style-agent concern,
       but centralised here to avoid N parallel linter fetches in the fan-out)
    4. Split the changed files into line-budgeted chunks
    5. Render a diff string for each chunk
    6. Write chunk payloads + per-chunk linter slices to state
"""
import logging
from app.models.workflow_state import PRReviewState
from app.utils.agent_helper import (
    fetch_file_contents,
    split_files_by_sha,
    format_files_for_llm,
    updated_shas
)
from app.tools.linter import run_linters, filter_linter_to_diff

logger = logging.getLogger(__name__)
MAX_LINES_PER_CHUNK = 500

async def ingestion_node(state: PRReviewState) -> dict:
    """
    LangGraph node — fetches and prepares PR file data for all agents.
 
    Reads:   owner, repo, pr_number, analyzed_file_shas (from state)
    Writes:  chunks, linter_outputs, analyzed_file_shas (updated)
    """
    owner = state["owner"]
    repo = state["repo"]
    pr_number = state["pr_number"]
    head_sha  = state["head_sha"]

    logger.info(f"Ingestion node starting — {owner}/{repo}/#{pr_number}")

    # Fetch changed files via MCP
    try:
        files = await fetch_file_contents(owner, repo, pr_number)
    except Exception as e:
        logger.error(f"Ingestion node — failed to fetch PR files: {e}")
        # Return empty sentinel values; agents will short-circuit on empty
        # files_to_analyze rather than each hitting the same failure
        return {
            "chunks": [],
            "analyzed_file_shas": state.get("analyzed_file_shas") or {}
        }
    
    # Skip files whose SHA hasn't changed since the last run
    prev_shas = state.get("analyzed_file_shas") or {}
    to_analyze, skipped = split_files_by_sha(files, prev_shas)
 
    logger.info(
        f"Ingestion node — {len(to_analyze)} files to analyze, "
        f"{len(skipped)} unchanged and skipped"
    )

    if not to_analyze:
        logger.info("Ingestion node — all files unchanged, nothing to analyze")
        return {
            "chunks":             [],
            "linter_outputs":     {},
            "analyzed_file_shas": updated_shas(prev_shas, files),
            "security_findings":   [],   # ← reset before fan-out
            "style_findings":      [],   # ← reset before fan-out
            "pr_files": files,
            "agents_completed":   0
        }
    
    # Run linters once across all changed files
    # it gets sliced per-chunk below so the router can forward only the
    # relevant slice to each style agent Send.
    try:
        linter_output_flat = await run_linters(
            to_analyze,
            owner=owner,
            repo=repo,
            head_sha=head_sha
        )
        logger.info(
            f"Ingestion node — linting complete, "
            f"{len(linter_output_flat)} files with output"
        )
    except Exception as e:
        logger.error(f"Ingestion node — linter failed, continuing without output: {e}")
        linter_output_flat = {}
    
    # Split into file-budgeted chunks at file boundaries
    
    logger.info(
        f"Ingestion node — {len(to_analyze)} files, chunking at "
        f"1 file/chunk"
    )
    file_chunks = [[f] for f in to_analyze]
    
    logger.info(
        f"Ingestion node — {len(to_analyze)} files split into "
        f"{len(file_chunks)} chunk(s) (budget: {MAX_LINES_PER_CHUNK} lines/chunk)"
    )

    # Build chunk payloads and slice linter output per chunk
    chunks: list[dict] = []
    linter_outputs: dict[int, dict[str, str]] = {}

    for i, chunk_files in enumerate(file_chunks):
        diff_context = format_files_for_llm(chunk_files)

        if not diff_context.strip():
            logger.info(f"Ingestion node — chunk {i} has no reviewable content, skipping")
            continue

        file_patches = {
            f.get("filename"): f.get("patch", "")
            for f in chunk_files
        }

        # Slice linter output to only filename in this chunk
        chunk_filenames = {f.get("filename") for f in chunk_files}
        linter_outputs[i] = filter_linter_to_diff(
            {
                filename: output
                for filename, output in linter_output_flat.items()
                if filename in chunk_filenames
            },
            file_patches
        )

        chunks.append({
            "files": chunk_files,
            "diff_context": diff_context,
            "file_patches": file_patches
        })

        logger.info(
            f"Ingestion node — chunk {i}: {len(chunk_files)} files, "
            f"{len(diff_context)} diff chars, "
            f"{len(linter_outputs[i])} files with linter output"
        )

    if not chunks:
        logger.info("Ingestion node — no reviewable content across all chunks")
        return {
            "chunks":             [],
            "linter_outputs":     {},
            "analyzed_file_shas": updated_shas(prev_shas, files),
            "pr_files": files,
            "agents_completed":   0
        }
    
    logger.info(f"Ingestion node complete — {len(chunks)} chunk(s) ready for routing")

    return {
        "chunks":   chunks,
        "linter_outputs": linter_outputs,
        "analyzed_file_shas": updated_shas(prev_shas, files),
        "pr_files": files,
        "agents_completed":   0
    }