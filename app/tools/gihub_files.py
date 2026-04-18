"""
app/tools/github_files.py
 
Standalone async tools for fetching GitHub file contents.
These are top-level @tool functions — independent, importable, and testable.
 
Both tools accept owner/repo/head_sha as explicit arguments so they carry
no hidden state and can be used by any agent in the pipeline.
 
Design notes
────────────
- Two separate tools with distinct names and docstrings so the LLM
  understands the different intent and depth rules for each.
- fetch_reviewed_file  → the file being changed in the PR (no line cap)
- fetch_import_file    → a direct import of the reviewed file (300-line cap)
- Both are async because fetch_full_file is an async HTTP call.
  Wrapping async I/O in a sync function would block the event loop.
"""

import logging
from langchain_core.tools import tool
from app.utils.agent_helper import fetch_full_file

logger = logging.getLogger(__name__)

_IMPORT_LINE_CAP = 300  # enough to see signatures/docstrings, not full impls

@tool
async def fetch_reviewed_file(owner:str, repo: str, head_sha: str, filename: str) -> str:
    """
    Fetch the complete current source of a file being reviewed in the PR.
 
    Use when the diff alone doesn't give enough context to judge correctness —
    for example, to see the surrounding class definition, how state is
    initialised, or what other methods exist on the same object.
 
    Args:
        owner:    Repository owner (e.g. "acme-corp")
        repo:     Repository name (e.g. "backend-api")
        head_sha: The PR's head commit SHA
        filename: Repo-relative path of the file (e.g. "app/utils/helper.py")
 
    Returns:
        Full file source with line numbers prepended, or an error string.
    """
    logger.info(f"[fetch_reviewed_file] {owner}/{repo}/{filename} @ {head_sha[:7]}")
    try:
        content = await fetch_full_file(owner, repo, filename, ref=head_sha)
    except Exception as exc:
        return f"[ERROR] Could not fetch '{filename}': {exc}"
 
    if not content or not content.strip():
        return f"[EMPTY] '{filename}' returned no content at {head_sha[:7]}"
 
    numbered = "\n".join(
        f"{i + 1:>4}  {line}" for i, line in enumerate(content.splitlines())
    )
    return f"### {filename} (full source @ {head_sha[:7]})\n```python\n{numbered}\n```"

@tool
async def fetch_import_file(owner: str, repo: str, head_sha: str, filename: str) -> str:
    """
    Fetch the source of a file that is directly imported by the file being reviewed.
 
    Use ONLY when:
      1. A changed line calls or inherits from a symbol defined in that file, AND
      2. You cannot determine the symbol's contract (signature, return type,
         side-effects) from the diff alone.
 
    Depth-1 rule: do NOT use this to fetch files imported by the file you
    just fetched. Only fetch imports of the PRIMARY file being reviewed.
 
    File path derivation — read the import statement in the diff directly:
      "from app.utils.agent_helper import X"  →  "app/utils/agent_helper.py"
      "from app.models.workflow_state import Y" →  "app/models/workflow_state.py"
    Do not fetch third-party packages (fastapi, pydantic, langchain, etc.).
 
    Budget: you may call this tool at most 4 times per review session.
    Count your calls. Stop fetching when you reach 4 and work with what you have.
 
    Args:
        owner:    Repository owner
        repo:     Repository name
        head_sha: The PR's head commit SHA
        filename: Repo-relative path of the imported file
 
    Returns:
        Up to 300 lines of source with line numbers, or an error string.
    """
    logger.info(f"[fetch_import_file] {owner}/{repo}/{filename} @ {head_sha[:7]}")
    try:
        content = await fetch_full_file(owner, repo, filename, ref=head_sha)
    except Exception as exc:
        return f"[ERROR] Could not fetch '{filename}': {exc}"
 
    if not content or not content.strip():
        return f"[EMPTY] '{filename}' returned no content at {head_sha[:7]}"
 
    lines = content.splitlines()
    truncated = len(lines) > _IMPORT_LINE_CAP
    shown = lines[:_IMPORT_LINE_CAP]
    numbered = "\n".join(f"{i + 1:>4}  {l}" for i, l in enumerate(shown))
    footer = (
        f"\n\n[truncated — showing {_IMPORT_LINE_CAP} of {len(lines)} lines. "
        "If you need more context, consider whether the symbol's contract is "
        "already clear from what you've seen.]"
        if truncated else ""
    )
    return (
        f"### {filename} (import context @ {head_sha[:7]})\n"
        f"```python\n{numbered}{footer}\n```"
    )