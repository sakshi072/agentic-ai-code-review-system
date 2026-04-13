from app.models.agent_finding_model import SecurityResponseSchema
from app.models.workflow_state import AgentFinding
from app.utils.agent_helper import (
    build_llm, 
    find_line_in_diff, 
    build_agent_prompt
)
from app.core.prompts.security_agent_prompt import SECURITY_AGENT_SYSTEM_PROMPT
from langchain_core.messages import SystemMessage, HumanMessage
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Security agent node
# ---------------------------------------------------------------------------
async def security_agent_node(payload:dict) -> dict:
    """
    LangGraph node — runs security analysis on the PR.
    Flow:
        1. Fetch changed files via MCP get_pull_request_files
        2. Build a structured prompt with the full diff
        3. Call LLM with security-focused system prompt
        4. Parse JSON findings and write to state
    """
    owner = payload["owner"]
    repo = payload["repo"]
    pr_number = payload["pr_number"]
    
    # Read ingestion outputs from state
    chunk = payload["chunk"]
    to_analyze   = chunk["files"]
    diff_context = chunk["diff_context"]
    file_patches = chunk["file_patches"]
    
    issues_identified = chunk.get("security_issues_identified") or []

    logger.info(
        f"Security agent starting — {owner}/{repo}/#{pr_number} "
        f"({len(to_analyze)} files in chunk)"
    )
    
    prompt = build_agent_prompt(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        diff_context=diff_context,
        focus = "security vulnerabilities",
    )

    # Call structured LLM
    structured_llm = build_llm("qwen3:8b", 0, "http://127.0.0.1:11434").with_structured_output(
        SecurityResponseSchema
    )

    try:
        response: SecurityResponseSchema = await structured_llm.ainvoke([
            SystemMessage(content=SECURITY_AGENT_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        logger.info(f"Security agent — {len(response.findings)} findings, ")
        for finding in response.findings:
            logger.info(
                f"LLM finding — {finding.title}: "
                f"fix_explanation='{finding.fix_explanation[:60]}' "
                f"fix_code='{finding.fix_code[:60] if finding.fix_code else 'EMPTY'}'"
            )
    except Exception as e:
        logger.error(f"Security agent — structured LLM call failed: {e}")
        return {
            "security_findings": []
        }

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
            fix_explanation = finding.fix_explanation.replace("\\\\n", "\\n"),
            fix_code = finding.fix_code,
        )
        for finding in response.findings
    ]

    logger.info(f" Security agent complete — {len(findings)} findings")

    for finding in response.findings:
        logger.info(
            f"  snippet='{finding.code_snippet[:50] if finding.code_snippet else 'EMPTY'}' "
            f"→ line={find_line_in_diff(file_patches.get(finding.file, ''), finding.code_snippet)}"
        )

    return {
        "security_findings": findings,
        "agents_completed": 1, 
    }