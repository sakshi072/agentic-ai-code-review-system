"""
app/workflow/performance_agent.py
 
Performance agent node — reviews PR diff for runtime performance issues.
 
Uses create_react_agent with two focused tools:
  - ast_analyze: confirm loop nesting depth before flagging complexity
  - search_callers: determine hot-path severity after confirming an issue
 
The agent starts with the diff and calls tools only on demand.
response_format gives us structured output in one pass (no second LLM call).
"""

import asyncio
import logging

from langchain_core.messages import HumanMessage
from langchain.agents import create_agent
from app.tools.gihub_files import fetch_reviewed_file
from app.tools.performance_tools import ast_analyze, search_callers
from app.core.configs.settings import settings
from app.utils.agent_helper import build_agent_prompt, build_llm, find_line_in_diff
from app.models.agent_finding_model import ResponseSchema
from app.core.prompts.performance_agent_prompt import PERFORMANCE_AGENT_SYSTEM_PROMPT
from app.models.workflow_state import AgentFinding

logger = logging.getLogger(__name__)

PERFORMANCE_AGENT_TOOLS = [fetch_reviewed_file, ast_analyze, search_callers]
_AGENT_TIMEOUT_SECONDS = 120
# ---------------------------------------------------------------------------
# Performance agent node
# ---------------------------------------------------------------------------
async def performance_agent_node(payload: dict) -> dict:
    """
    LangGraph node — performance code review on one diff chunk.
 
    Receives (via Send payload):
        owner, repo, pr_number, head_sha  — PR identity
        chunk                              — {files, diff_context, file_patches}
 
    Returns:
        performance_findings   — list[AgentFinding] (accumulated via add reducer)
        agents_completed — 1
    """
    owner     = payload["owner"]
    repo      = payload["repo"]
    pr_number = payload["pr_number"]
    head_sha  = payload["head_sha"]
 
    chunk        = payload["chunk"]
    to_analyze   = chunk["files"]
    diff_context = chunk["diff_context"]
    file_patches = chunk["file_patches"]
 
    logger.info(
        f"Performance agent starting — {owner}/{repo}/#{pr_number} "
        f"({len(to_analyze)} file(s) in chunk)"
    )
 
    if not diff_context.strip():
        logger.info("Performance agent — empty diff, skipping")
        return {"performance_findings": [], "agents_completed": 1}
 
    # ------------------------------------------------------------------
    # Build the agent
    # ------------------------------------------------------------------
    llm = build_llm()
 
    agent = create_agent(
        model=llm,
        tools=PERFORMANCE_AGENT_TOOLS,
        system_prompt=PERFORMANCE_AGENT_SYSTEM_PROMPT,  # system message injected into every turn
        response_format=ResponseSchema,
    )
    
    # ------------------------------------------------------------------
    # Build the user prompt
    # ------------------------------------------------------------------
    user_prompt = build_agent_prompt(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        diff_context=diff_context,
        focus="runtime performance",
    )
 
    user_prompt += (
        f"\n\n## Tool arguments\n"
        f"owner={owner!r}  repo={repo!r}  head_sha={head_sha!r}\n\n"
        "## ast_analyze usage\n"
        "The diff is a fragment — passing it to ast_analyze causes SyntaxError\n"
        "or wrong nesting depth. Always fetch the full file first:\n"
        "  1. Call fetch_reviewed_file(owner, repo, head_sha, filename)\n"
        "  2. Pass the returned source to ast_analyze(code=<full source>)\n\n"
        "## search_callers usage\n"
        "Only call after confirming an issue. Pass the exact function name.\n"
        "Use the result to raise severity if callers are in hot-path files."
    )
 
    # ------------------------------------------------------------------
    # Run the agent
    # ------------------------------------------------------------------
    try:
        result = await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [HumanMessage(content=user_prompt)]},
                config={"recursion_limit": 4},
            ),
            timeout=_AGENT_TIMEOUT_SECONDS,
        )
        response: ResponseSchema = result.get("structured_response")
        if response is None:
            logger.warning("Performance agent — no structured_response, returning empty")
            return {"performance_findings": [], "agents_completed": 1}
 
        logger.info(f"Performance agent — {len(response.findings)} finding(s)")
        for f in response.findings:
            logger.info(f"  [{f.severity}] {f.title} | file={f.file} | snippet={f.code_snippet[:60]!r}")
 
    except asyncio.TimeoutError:
        logger.warning(f"Performance agent — timed out after {_AGENT_TIMEOUT_SECONDS}s")
        return {"performance_findings": [], "agents_completed": 1}
    except Exception as exc:
        logger.error(f"Performance agent — failed: {exc}", exc_info=True)
        return {"performance_findings": [], "agents_completed": 1}
 
    # ------------------------------------------------------------------
    # Map pydantic → AgentFinding TypedDict
    # ------------------------------------------------------------------
    findings: list[AgentFinding] = [
        AgentFinding(
            severity        = f.severity.value,
            file            = f.file,
            line            = find_line_in_diff(
                                  file_patches.get(f.file, ""),
                                  f.code_snippet,
                              ),
            title           = f.title,
            description     = f.description.replace("\\\\n", "\n"),
            fix_explanation = f.fix_explanation.replace("\\\\n", "\n"),
            fix_code        = f.fix_code,
        )
        for f in response.findings
    ]
 
    logger.info(f"Performance agent complete — {len(findings)} finding(s)")
    for f in findings:
        logger.info(f"Performance agent finding: {f}")
    return {"performance_findings": findings, "agents_completed": 1}