"""
Ingestion node — runs once before all specialist agents.
 
Responsibilities:
    1. Fetch changed files from GitHub via MCP
    2. Filter out files whose SHA hasn't changed since the last run
    3. Render the diff into a single LLM-ready string
    4. Write results to state so every downstream agent can read them
       without re-fetching or re-filtering independently
"""
import logging
from app.models.workflow_state import PRReviewState
from app.utils.agent_helper import (
    fetch_file_contents,
    split_files_by_sha,
    format_files_for_llm,
    updated_shas
)

logger = logging.getLogger(__name__)

async def ingestion_node(state: PRReviewState) -> dict:
    """
    LangGraph node — fetches and prepares PR file data for all agents.
 
    Reads:   owner, repo, pr_number, analyzed_file_shas (from state)
    Writes:  files_to_analyze, diff_context, file_patches,
             analyzed_file_shas (updated)
    """
    owner = state["owner"]
    repo = state["repo"]
    pr_number = state["pr_number"]

    logger.info(f"Ingestion node starting — {owner}/{repo}/#{pr_number}")

    # Fetch changed files via MCP
    try:
        files = await fetch_file_contents(owner, repo, pr_number)
    except Exception as e:
        logger.error(f"Ingestion node — failed to fetch PR files: {e}")
        # Return empty sentinel values; agents will short-circuit on empty
        # files_to_analyze rather than each hitting the same failure
        return {
            "files_to_analyze": [],
            "diff_context":     "",
            "file_patches":     {},
            "analyzed_file_shas": state.get("analyzed_file_shas") or {},
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
            "files_to_analyze": [],
            "diff_context":     "",
            "file_patches":     {},
            "analyzed_file_shas": updated_shas(prev_shas, files),
        }
    
    # Render diff context once for all agents
    diff_context = format_files_for_llm(to_analyze)
 
    if not diff_context.strip():
        logger.info("Ingestion node — no reviewable content in diff, skipping")
        return {
            "files_to_analyze": [],
            "diff_context":     "",
            "file_patches":     {},
            "analyzed_file_shas": updated_shas(prev_shas, files),
        }

    # Build raw patch map for line-number resolution
    file_patches = {
        f.get("filename"): f.get("patch", "")
        for f in files
    }

    logger.info(
        f"Ingestion node complete — diff_context {len(diff_context)} chars, "
        f"{len(to_analyze)} files queued for analysis"
    )

    return {
        "files_to_analyze":   to_analyze,
        "diff_context":       diff_context,
        "file_patches":       file_patches,
        "analyzed_file_shas": updated_shas(prev_shas, files),
    }