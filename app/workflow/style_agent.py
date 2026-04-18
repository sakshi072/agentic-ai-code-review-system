from app.models.workflow_state import PRReviewState, AgentFinding
from app.clients.github_mcp_client import github_mcp_session
from app.core.configs.github_server_config import MCPTool
from app.utils.agent_helper import (
    build_llm, 
    find_line_in_diff, 
    build_agent_prompt
)
from app.models.agent_finding_model import StyleResponseSchema
from app.core.prompts.style_agent_prompt import STYLE_AGENT_SYSTEM_PROMPT
from app.tools.linter import run_linters
from langchain_core.messages import SystemMessage, HumanMessage
import logging

logger = logging.getLogger(__name__)

async def style_agent_node(payload:dict):
    """
    LangGraph node — runs style and quality analysis on one diff chunk.

    Receives (via Send payload):
        owner, repo, pr_number      — PR identity
        chunk                       — {files, diff_context, file_patches}
        linter_output               — pre-computed linter results from ingestion
                                      (scoped to this chunk's files only)
        style_issues_identified     — open issues from previous runs
 
    Returns:
        style_findings           — new findings only (appended via add reducer)
        style_issues_identified  — updated open issue list for this chunk's files
    """
    owner     = payload["owner"]
    repo      = payload["repo"]
    pr_number = payload["pr_number"]
   
    # Read ingestion outputs from state
    chunk = payload["chunk"]
    to_analyze = chunk["files"]
    diff_context = chunk["diff_context"]
    file_patches = chunk["file_patches"]
 
    # Linter output pre-computed by ingestion node — scoped to this chunk's files
    linter_output = payload.get("linter_output") or {}
    
    logger.info(
        f"Style agent starting — {owner}/{repo}/#{pr_number} "
        f"({len(to_analyze)} files in chunk, "
        f"{len(linter_output)} files with linter output)"
    )
    
    prompt = build_agent_prompt(
        owner=owner,
        repo=repo,
        pr_number=pr_number,
        diff_context=diff_context,
        focus = "style discrepancies",
        linter_output=linter_output
    )
    
    # Call structured LLM
    # structured_llm = build_llm("hermes3:3b", 0, "http://127.0.0.1:11434", False).with_structured_output(
    #     StyleResponseSchema
    # )

    structured_llm = build_llm().with_structured_output(StyleResponseSchema)

    try:
        response: StyleResponseSchema = await structured_llm.ainvoke([
            SystemMessage(content=STYLE_AGENT_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        logger.info(f"Style agent - {len(response.findings)} findings")
        for finding in response.findings:
            logger.info(
                f"LLM finding — {finding.title}: "
                f"fix_explanation='{finding.fix_explanation[:60]}' "
                f"fix_code='{finding.fix_code[:60] if finding.fix_code else 'EMPTY'}'"
            )
    except Exception as e:
        logger.error(f"Structured LLM call failed: {e}")
        return {
            "style_findings": []
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
            fix_code = finding.fix_code
        )
        for finding in response.findings
    ]

    logger.info(f" Style agent complete — {len(findings)} findings")

    for finding in response.findings:
        logger.info(
            f"  snippet='{finding.code_snippet[:50] if finding.code_snippet else 'EMPTY'}' "
            f"→ line={find_line_in_diff(file_patches.get(finding.file, ''), finding.code_snippet)}"
        )

    return {
        "style_findings": findings,
        "agents_completed": 1, 
    }