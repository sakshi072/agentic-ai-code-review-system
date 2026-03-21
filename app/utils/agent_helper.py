from langchain_ollama import ChatOllama
from app.core.configs.settings import settings
from app.clients.github_mcp_client import github_mcp_session
from app.core.configs.github_server_config import MCPTool
from app.models.workflow_state import AgentFinding
from typing import Any
import json
import logging
import codecs 
import re

logger = logging.getLogger(__name__)

def unescape_patches(files: list) -> list:
    for f in files:
        if isinstance(f.get("patch"), str):
            try:
                f["patch"] = codecs.decode(f["patch"], "unicode-escape")
            except Exception:
                pass
    return files

def build_llm(model:str, temperature:float, base_url:str):
    return ChatOllama(
        model= model or settings.DEFAULT_AGENT_MODEL_ID,
        temperature=temperature or settings.DEFAULT_AGENT_TEMPERATURE,
        base_url=base_url or settings.DEFAULT_AGENT_BASE_URL
    )

def parse_mcp_response(raw_changes:Any) -> list:
    if isinstance(raw_changes, list):
        if raw_changes and isinstance(raw_changes[0], dict) and "text" in raw_changes[0]:
            raw_changes = raw_changes[0]["text"]
        else:
            parsed = raw_changes
            return unescape_patches(parsed)
        
    if isinstance(raw_changes, str):
        try:
            parsed = json.loads(raw_changes)
        except json.JSONDecodeError as e:
            logger.error(f"Json Decoding failed: {e}")
            return []
    else:
        return []
    
    return unescape_patches(parsed)

def format_files_for_llm(files:list) -> str:
    """
    Renders changed files into a structured string for LLM consumption.
    Skips binary files, caps individual file patches at 200 lines.
    """
    sections = []

    SKIP_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
        ".pdf", ".zip", ".tar", ".gz", ".lock",
    }

    for f in files:
        filename = f.get("filename", "")
        status = f.get("status", "modified")
        patch = f.get("patch", "")
        additions = f.get("additions", 0)
        deletions = f.get("deletions", 0)

        # ── Add this temporarily to debug ────────────────────────────────
        logger.info(f"  📄 {filename} — patch length: {len(patch)}, lines: {len(patch.splitlines())}")
        # ─────────────────────────────────────────────────────────────────

        # Skip binary / non-reviewable files
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext in SKIP_EXTENSIONS:
            continue
        
        if status == "removed":
            continue

        if not patch:
            continue

        # Cap patch size - large patches lose LLM focus
        patch_lines = patch.splitlines()
        truncated = False
        if len(patch_lines) > 200:
            patch_lines = patch_lines[:200]
            truncated = True

        section = (
            f"### File: `{filename}` [{status}] +{additions}/-{deletions}\n"
            f"```diff\n"
            f"{chr(10).join(patch_lines)}\n"
            f"{'[... truncated for length ...]' if truncated else ''}"
            f"```\n"
        )
        sections.append(section)
    return "\n".join(sections)

def format_prev_issues(files:list, issues_identified: list[AgentFinding],) -> str:
    """
    Render issues from the previous run into a structured string for LLM context.
    The LLM uses this + the current diff to determine what is resolved,
    what persists, and what is new.
    """
    if not issues_identified:
        return ""

    filenames_in_run = {f.get("filename", "") for f in files}

    relevant_issues = [
        issue for issue in issues_identified
        if issue["file"] in filenames_in_run
    ]

    if not relevant_issues:
        return ""
    
    # Group by file for readable output
    issues_by_file: dict[str, list] = {}
    for issue in relevant_issues:
        issues_by_file.setdefault(issue["filename"], []).append(issue)

    sections = []
    for filename, file_issues in issues_by_file.items():
        section_lines = [f"### Previously posted issues in `{filename}`"]
        for i, issue in enumerate(file_issues, 1):
            line_ref = f" (line {issue['line']})" if issue.get("line") else ""
            section_lines.append(
                f"{i}. **{issue['title']}**{line_ref}"
                f"\n. {issue['description']}"
            )
        sections.append(chr(10).join(section_lines))
    
    if not sections:
        return ""
    
    header = (
        "## Context From Previous Review\n"
        "Issues already posted. For each one: if still present in the current diff "
        "→ set status=persists and omit. If no longer present → mark status=resolved"
        "Only report genuinely new issues and set status=new\n\n"
    )

    return header + "\n\n".join(sections)

def find_line_in_diff(patch:str, snippet:str) -> int | None:
    clean_snippet = snippet.lstrip("+").strip()
    current_line = 0
    for line in patch.splitlines():
        if line.startswith("@@"):
            match = re.search(r'\+(\d+)', line)
            if match:
                current_line = int(match.group(1)) - 1
        elif not line.startswith("-"):
            current_line += 1
            if clean_snippet and clean_snippet in line:
                return current_line
    return None

async def fetch_file_contents(owner, repo, pr_number):
    # Fetch changed files via MCP
    raw_changes = await github_mcp_session.invoke_tool(
        MCPTool.GET_PULL_REQUEST_FILES,
        owner=owner,
        repo=repo,
        pull_number=pr_number
    )

    files = parse_mcp_response(raw_changes)
    logger.info(f"Security agent fetched {len(files)} changed files")
    logger.info(f"files ======= {files}")
    return files

def split_files_by_sha(
    files: list,
    prev_shas: dict[str, str]
) -> tuple[list, list]:
    """Returns to_analyze and skipped files"""
    to_analyze = []
    skipped = []

    for f in files:
        filename = f.get("filename")
        sha = f.get("sha", "")

        if prev_shas.get(filename) == sha:
            logger.info(f" {filename} - sha unchanged, skipping")
            skipped.append(f)
        else:
            logger.info(f" {filename} - sha changed or new, analyzing")
            to_analyze.append(f)
    return to_analyze, skipped

def updated_shas(prev_shas:dict, files:list) -> dict:
    """Returns merged sha map with current files' shas"""
    return {
        **prev_shas,
        **{f.get("filename"): f.get("sha", "") for f in files}
    }

def build_agent_prompt(
    owner:str,
    repo:str,
    pr_number:str,
    diff_context:str,
    files:list,
    issues_identified:list[dict],
    focus:str,
) -> str:
    prompt = (
        f"Review this Pull Request for {focus}:\n\n"
        f"PR: {owner}/{repo}/#{pr_number}\n\n"
        f"## Current Diff\n{diff_context}"
    )

    prev_context = format_prev_issues(files, issues_identified)
    if prev_context:
        prompt += prev_context

    return prompt