from langchain_openai import ChatOpenAI
from app.core.configs.settings import settings
from app.clients.github_mcp_client import github_mcp_session
from app.core.configs.github_server_config import MCPTool
from app.models.workflow_state import AgentFinding
from typing import Any, Optional
import json
import logging
import codecs 
import re
import base64
import httpx

logger = logging.getLogger(__name__)

SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".pdf", ".zip", ".tar", ".gz", ".lock",
}

def unescape_patches(files: list) -> list:
    for f in files:
        if isinstance(f.get("patch"), str):
            try:
                f["patch"] = codecs.decode(f["patch"], "unicode-escape")
            except Exception:
                pass
    return files

# def build_llm(model:str, temperature:float, base_url:str, ollama:bool):
#     if ollama:
#         return ChatOllama(
#             model= model or settings.DEFAULT_AGENT_MODEL_ID,
#             temperature=temperature or settings.DEFAULT_AGENT_TEMPERATURE,
#             base_url=base_url or settings.DEFAULT_AGENT_BASE_URL,
#             timeout=30,
#         )
    
#     return ChatOpenAI(
#         model="gpt-5-nano",
#         temperature=0,
#         api_key=settings.OPEN_API_KEY,

#     )

def build_llm():
    return ChatOpenAI(
        model="gpt-5-nano",
        temperature=0,
        api_key=settings.OPEN_API_KEY
        
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

def format_files_for_llm(files: list) -> str:
    """
    Renders changed files into a structured string for LLM consumption.
 
    Each added line (+) is annotated with its actual file line number:
        +[line 91] SECRET_KEY = "..."
    This lets the LLM report exact line numbers without parsing hunk headers.
 
    Skips binary files and removed files.
    Caps individual file patches at 200 lines.
    """
    sections = []
 
    for f in files:
        filename  = f.get("filename", "")
        status    = f.get("status", "modified")
        patch     = f.get("patch", "")
        additions = f.get("additions", 0)
        deletions = f.get("deletions", 0)
 
        logger.info(
            f"  📄 {filename} — patch length: {len(patch)}, "
            f"lines: {len(patch.splitlines())}"
        )
 
        # Skip binary / non-reviewable files
        ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
        if ext in SKIP_EXTENSIONS or status == "removed" or not patch:
            continue
 
        # Annotate added lines with their actual file line numbers
        annotated: list[str] = []
        current_line = 0
 
        for line in patch.splitlines():
            if line.startswith("@@"):
                # Hunk header — extract new-file start line
                m = re.search(r"\+(\d+)", line)
                if m:
                    current_line = int(m.group(1))
                annotated.append(line)
            elif line.startswith("+"):
                # Added line — inject line number so LLM can read it directly
                annotated.append(f"+[line {current_line}] {line[1:]}")
                current_line += 1
            elif line.startswith("-"):
                # Removed line — no new-file line number
                annotated.append(line)
            else:
                # Context line — advances new-file line counter
                annotated.append(line)
                current_line += 1
 
        # Cap patch size — large patches lose LLM focus
        truncated = False
        if len(annotated) > 200:
            annotated = annotated[:200]
            truncated = True
 
        section = (
            f"### File: `{filename}` [{status}] +{additions}/-{deletions}\n"
            f"```diff\n"
            f"{chr(10).join(annotated)}\n"
            f"{'[... truncated for length ...]' if truncated else ''}"
            f"```\n"
        )
        sections.append(section)
 
    return "\n".join(sections)

def find_line_in_diff(patch: str, snippet: str) -> int | None:
    if not snippet:
        return None

    snippet = snippet.strip()

    # Strategy 1: LLM copied [line N] annotation verbatim
    m = re.search(r"\[line (\d+)\]", snippet)
    if m:
        return int(m.group(1))

    # ADDED Strategy: The LLM was lazy and just returned the line number like "+12" or "12"
    m_lazy = re.fullmatch(r"\+?(\d+)", snippet)
    if m_lazy:
        return int(m_lazy.group(1))

    # Strategy 2: match first non-empty line of snippet against patch
    first_line = next(
        (
            re.sub(r"\[line \d+\]\s*", "", l).lstrip("+").strip()
            for l in snippet.splitlines()
            if l.strip() and not l.strip().startswith("...")
        ),
        None,
    )
    
    if not first_line:
        return None

    current_line = 0
    for line in patch.splitlines():
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            if match:
                current_line = int(match.group(1)) - 1
        elif not line.startswith("-"):
            current_line += 1
            clean_patch_line = line.lstrip("+").strip()
            if first_line and first_line in clean_patch_line:
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
    owner: str,
    repo: str,
    pr_number: str,
    diff_context: str,
    focus: str,
) -> str:

    prompt = (
        f"REVIEW TASK: PR #{pr_number} ({owner}/{repo})\n"
        "## STRICTOR RULES\n"
        "1. Identify issues ONLY in lines starting with '+'.\n"
        "2. Use the [line N] annotation as the line number.\n"
        "---\n"
    )

    # ── Diff ──────────────────────────────────────────────────────────────────
    prompt += f"Diff\n{diff_context}\n"

    return prompt

async def fetch_full_file(owner: str, repo: str, filepath: str, ref: str) -> str:
    """Fetch file content directly from GitHub REST API at a specific ref."""
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{filepath}"
    
    headers = {
        "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    params = {"ref": ref}
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
    
    content = data.get("content", "")
    if not content:
        logger.warning(f"fetch_full_file: empty content for {filepath} at {ref}")
        return ""
    
    decoded = base64.b64decode(content.replace("\n", "")).decode("utf-8")
    logger.info(f"fetch_full_file: {filepath} at {ref[:7]} — {len(decoded)} chars, {decoded.count(chr(10))} lines")
    return decoded