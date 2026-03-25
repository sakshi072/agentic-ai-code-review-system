from app.models.workflow_state import PRReviewState, AgentFinding
from app.clients.github_mcp_client import github_mcp_session
from app.core.configs.github_server_config import MCPTool
from app.utils.agent_helper import (
    build_llm, 
    format_files_for_llm, 
    find_line_in_diff, 
    fetch_file_contents, 
    split_files_by_sha,
    updated_shas,
    build_agent_prompt
)
from app.models.agent_finding_model import StyleResponseSchema
from app.core.prompts.style_agent_prompt import STYLE_AGENT_SYSTEM_PROMPT
from app.tools.linter import run_linters
from langchain_core.messages import SystemMessage, HumanMessage
import logging

logger = logging.getLogger(__name__)

async def style_agent_node(state:PRReviewState):
    """
    LangGraph node — runs style and quality analysis on the PR.

    Flow:
        1. Fetch changed files via MCP get_pull_request_files
        2. Build structured prompt with the full diff
        3. Call structured LLM with style-focused system prompt
        4. Map findings into state
    """
    owner = state["owner"]
    repo = state["repo"]
    pr_number = state["pr_number"]

    logger.info(f"Style agent starting - {owner}/{repo}/{pr_number}")
   
    # Read ingestion outputs from state
    to_analyze   = state.get("files_to_analyze") or []
    diff_context = state.get("diff_context") or ""
    file_patches = state.get("file_patches") or {}
 
    if not to_analyze or not diff_context:
        logger.info("Style agent — nothing to analyze (ingestion found no changes)")
        return {
            "style_findings": [],
            "messages": state["messages"],
        }
    
    # Run linters 
    linter_output = await run_linters(to_analyze, owner=owner, repo=repo, head_sha=state["head_sha"])
    logger.info(f"Linting complete — {len(linter_output)} files with output")
    
    prompt = build_agent_prompt(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        diff_context=diff_context,
        files = to_analyze,
        issues_identified= state.get("style_issues_identified") or [],
        focus = "style discrepancies",
        linter_output=linter_output
    )
    
    # Call structured LLM
    structured_llm = build_llm("qwen3:8b", 0, "http://localhost:11434").with_structured_output(
        StyleResponseSchema
    )

    try:
        response: StyleResponseSchema = await structured_llm.ainvoke([
            SystemMessage(content=STYLE_AGENT_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        logger.info(f"Structured response received - {len(response.findings)} findings")
    except Exception as e:
        logger.error(f"Structured LLM call failed: {e}")
        return {"style_findings": [], "messages": state["messages"]}

    # Map pydantic -> AgentFinding TypedDict
    findings:list[AgentFinding] = [
        AgentFinding(
            severity = finding.severity.value,
            file = finding.file,
            line = find_line_in_diff(
                file_patches.get(finding.file, ""),
                finding.code_snippet
            ),
            title = finding.title,
            description = finding.description.replace("\\\\n", "\\n"),
            suggestion = finding.suggestion.replace("\\\\n", "\\n"),
            status = finding.status.value,
        )
        for finding in response.findings
    ]

    logger.info(f" Style agent complete — {len(findings)} findings")

    # SHA proved these files didn't change — issues still open by definition
    analyzed_filenames = {f.get("filename") for f in to_analyze}
    carried_over = [
        issue for issue in (state.get("style_issues_identified") or [])
        if issue["file"] not in analyzed_filenames
    ]

    # Split by status
    to_post = [f for f in findings if f["status"] == "new"]
    open_issues = [f for f in findings if f["status"] in ("new", "persists")]
    resolved = [f for f in findings if f["status"] == "resolved"]
    merged_open_issues = open_issues + carried_over

    for r in resolved:
        logger.info(f"  ✅ Resolved: {r['file']} — {r['title']}")

    for f in findings:
        logger.info(f"   [{f['severity'].upper()}] {f['file']}: {f['title']}")

    return {
        "style_findings":          to_post,
        "style_issues_identified": merged_open_issues,
        "messages":                state["messages"],
    }



    
        
