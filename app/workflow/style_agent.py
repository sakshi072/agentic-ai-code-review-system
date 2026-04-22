from app.models.workflow_state import AgentFinding
from app.utils.agent_helper import (
    build_llm, 
    find_line_in_diff, 
    build_agent_prompt
)
from app.models.agent_finding_model import ResponseSchema
from app.core.prompts.style_agent_prompt import STYLE_AGENT_SYSTEM_PROMPT
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
    
    logger.info(
        f"Style agent starting — {owner}/{repo}/#{pr_number} "
        f"({len(to_analyze)} files in chunk, "
    )

    added_lines_only = "\n".join(
        line for line in diff_context.splitlines()
        if line.startswith("@@") or line.startswith("+")
    )

    structured_llm = build_llm().with_structured_output(ResponseSchema)

    try:
        response: ResponseSchema = await structured_llm.ainvoke([
            SystemMessage(content=STYLE_AGENT_SYSTEM_PROMPT),
            HumanMessage(content=f"Diff (added lines only):\n{added_lines_only}"),
        ])
        logger.info(f"Style agent - {len(response.findings)} findings")
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