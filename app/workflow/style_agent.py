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
   
    # Fetch changed files via MCP
    try:
        files = await fetch_file_contents(owner, repo, pr_number)
    except Exception as e:
        logger.error(f" Failed to fetch PR files: {e}")
        return {"style_findings": [], "messages": state["messages"]}
    
    prev_shas = state.get("analyzed_file_shas") or {}
    
    # Skip unchanged files
    to_analyze, skipped = split_files_by_sha(files, prev_shas)

    if not to_analyze:
        logger.info("Style agent - all files unchanged, nothing to analyze")
        return {
            "style_findings": [],
            "analyzed_file_shas": updated_shas(prev_shas, files),
            "messages": state["messages"]
        }

    # Build diff context for llm
    diff_context = format_files_for_llm(to_analyze)
    logger.info(f"DIFF CONTEXT SENT TO LLM:\\n{diff_context}")

    if not diff_context.strip():
        logger.info("No reviewable files found - skipping style analysis")
        return {
            "style_findings": [], 
            "analyzed_file_shas": updated_shas(prev_shas, files),
            "messages": state["messages"]
            }
    
    prompt = build_agent_prompt(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        diff_context=diff_context,
        files = to_analyze,
        issues_identified= state.get("style_issues_identified") or [],
        focus = "style discrepancies",
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

    file_patches = {f.get("filename"): f.get("patch", "") for f in files}

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

    # Split by status
    to_post = [f for f in findings if f["status"] == "new"]
    open_issues = [f for f in findings if f["status"] == ("new", "persists")]
    resolved = [f for f in findings if f["status"] == "resolved"]

    for r in resolved:
        logger.info(f"  ✅ Resolved: {r['file']} — {r['title']}")

    for f in findings:
        logger.info(f"   [{f['severity'].upper()}] {f['file']}: {f['title']}")

    return {
        "style_findings": to_post,
        "style_issues_identified": open_issues,
        "analyzed_file_shas": updated_shas(prev_shas, files),
        "messages": state["messages"]
    }



    
        
