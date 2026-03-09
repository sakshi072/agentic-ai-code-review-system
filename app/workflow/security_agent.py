from app.models.agent_finding_model import SecurityResponseSchema
from app.models.workflow_state import PRReviewState, AgentFinding, Category
from app.clients.github_mcp_client import github_mcp_session
from app.core.configs.github_server_config import MCPTool
from app.utils.agent_helper import parse_mcp_response, build_llm, format_files_for_llm, find_line_in_diff
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
    github_mcp_session.tools
    # Fetch changed files via MCP
    try:
        raw_changes = await github_mcp_session.invoke_tool(
            MCPTool.GET_PULL_REQUEST_FILES,
            owner=owner,
            repo=repo,
            pull_number=pr_number
        )

        files = parse_mcp_response(raw_changes)
        logger.info(f"Security agent fetched {len(files)} changed files")
        logger.info(f"files ======= {files}")
    except Exception as e:
        logger.error(f" Failed to fetch PR files: {e}")
        return {"security_findings": [], "messages": state["messages"]}
    
    # Build diff context for llm
    diff_context = format_files_for_llm(files)
    logger.info(f"DIFF CONTEXT SENT TO LLM:\\n{diff_context}")

    if not diff_context.strip():
        logger.info("No reviewable files found - skipping security analysis")
        return {"security_findings": [], "messages": state["messages"]}
    
    # Call structured LLM
    structured_llm = build_llm("qwen3:8b", 0, "http://localhost:11434").with_structured_output(
        SecurityResponseSchema
    )
    # structured_llm = build_llm("deepseek-coder-v2", 0, "http://localhost:11434")

    messages = [
        SystemMessage(content=SECURITY_AGENT_SYSTEM_PROMPT),
        HumanMessage(content=(
            f"Review this Pull Request for security vulnerabilities:\n\n"
            f"PR: {owner}/{repo}/{pr_number}\n\n"
            f"{diff_context}"
        ))
    ]

    try:
        response: SecurityResponseSchema = await structured_llm.ainvoke(messages)
        # logger.info(f"RAW LLM OUTPUT:\\n{response.content}")
        logger.info(f"Structured response received - {len(response.findings)} findings")
    except Exception as e:
        logger.error(f"Structured LLM call failed: {e}")
        return {"security_findings": [], "messages": state["messages"]}

    file_patches = {f.get("filename"): f.get("patch", "") for f in files}

    # Map pydantic -> AgentFinding TypedDict
    findings:list[AgentFinding] = [
        AgentFinding(
            severity = finding.severity,
            category = Category.SECURITY,
            file = finding.file,
            line = find_line_in_diff(
                file_patches.get(finding.file, ""),
                finding.code_snippet
            ),
            title = finding.title,
            description = finding.description.replace("\\\\n", "\\n"),
            suggestion = finding.suggestion.replace("\\\\n", "\\n"),
        )
        for finding in response.findings
    ]

    logger.info(f" Security agent complete — {len(findings)} findings")

    for f in findings:
        logger.info(f"   [{f['severity'].value.upper()}] {f['file']}: {f['title']}")

    return {
        "security_findings": findings,
        "messages": state["messages"]
    }