from app.models.agent_finding_model import SecurityResponseSchema
from app.models.workflow_state import PRReviewState, AgentFinding
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
from app.core.prompts.security_agent_prompt import SECURITY_AGENT_SYSTEM_PROMPT
from langchain_core.messages import SystemMessage, HumanMessage
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Security agent node
# ---------------------------------------------------------------------------
async def security_agent_node(state: PRReviewState) -> dict:
    """
    LangGraph node — runs security analysis on the PR.
    Flow:
        1. Fetch changed files via MCP get_pull_request_files
        2. Build a structured prompt with the full diff
        3. Call LLM with security-focused system prompt
        4. Parse JSON findings and write to state
    """
    owner = state["owner"]
    repo = state["repo"]
    pr_number = state["pr_number"]

    logger.info(f"Security agent starting - {owner}/{repo}/{pr_number}")
   
    # Fetch changed files via MCP
    try:
        files = await fetch_file_contents(owner, repo, pr_number)
    except Exception as e:
        logger.error(f" Failed to fetch PR files: {e}")
        return {"security_findings": [], "messages": state["messages"]}
    
    prev_shas = state.get("analyzed_file_shas") or {}
    
    # Skip unchanged files
    to_analyze, skipped = split_files_by_sha(files, prev_shas)

    logger.info(f"Number of files unchanged - {len(skipped)}")

    if not to_analyze:
        logger.info("Security agent - all files unchanged, nothing to analyze")
        return {
            "security_findings": [],
            "analyzed_file_shas": updated_shas(prev_shas, files),
            "messages": state["messages"]
        }

    # Build diff context for llm
    diff_context = format_files_for_llm(to_analyze)
    logger.info(f"DIFF CONTEXT SENT TO LLM:\\n{diff_context}")
    
    if not diff_context.strip():
        logger.info("No reviewable files found - skipping security analysis")
        return {
            "security_findings": [], 
            "analyzed_file_shas": updated_shas(prev_shas, files),
            "messages": state["messages"]}
    
    prompt = build_agent_prompt(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        diff_context=diff_context,
        files = to_analyze,
        issues_identified= state.get("security_issues_identified") or [],
        focus = "security vulnerabilities",
    )

    # Call structured LLM
    structured_llm = build_llm("qwen3:8b", 0, "http://localhost:11434").with_structured_output(
        SecurityResponseSchema
    )
    # structured_llm = build_llm("deepseek-coder-v2", 0, "http://localhost:11434")

    try:
        response: SecurityResponseSchema = await structured_llm.ainvoke([
            SystemMessage(content=SECURITY_AGENT_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        logger.info(f"Security agent — {len(response.findings)} findings, ")

    except Exception as e:
        logger.error(f"Structured LLM call failed: {e}")
        return {
            "security_findings": [], 
            "analyzed_file_shas": updated_shas(prev_shas, files),
            "messages": state["messages"]
            }

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

    logger.info(f" Security agent complete — {len(findings)} findings")

    # Split by status
    to_post = [f for f in findings if f["status"] == "new"]
    open_issues = [f for f in findings if f["status"] == ("new", "persists")]
    resolved = [f for f in findings if f["status"] == "resolved"]
    
    for r in resolved:
        logger.info(f"  ✅ Resolved: {r['file']} — {r['title']}")

    for f in to_post:
        logger.info(f"  [{f['severity'].upper()}] {f['file']}: {f['title']}")

    return {
        "security_findings": to_post,
        "security_issues_identified": open_issues,
        "analyzed_file_shas": updated_shas(prev_shas, files),
        "messages": state["messages"]
    }