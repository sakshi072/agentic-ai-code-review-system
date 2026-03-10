"""
PR Review Pipeline — LangGraph graph wiring the agent pipeline.

Current state: single security agent node.

Graph structure:
    START → security_agent → END
"""
import logging
from langgraph.graph import StateGraph, START, END
from app.models.workflow_state import PRReviewState, ReviewDecision
from app.workflow.security_agent import security_agent_node
from app.clients.github_mcp_client import github_mcp_session
from app.core.configs.github_server_config import MCPTool
from app.workflow.style_agent import style_agent_node
logger = logging.getLogger(__name__)

def _decide_review_outcome(findings: list) -> ReviewDecision:
    if not findings:
        return ReviewDecision.APPROVE
    
    # severities = [f["severity"] for f in findings]
    # has_high_or_above = any(s.value in ("critical", "high") for s in severities)
    # if has_high_or_above:
    #     return ReviewDecision.REQUEST_CHANGES
    return ReviewDecision.COMMENT

def _format_review_body(security: list, style: list) -> str:
    lines = []
    lines.append("## Security & Style Review")
    lines.append("")

    if security:
        critical_high = [f for f in security if f["severity"].value in ("critical", "high")]
        medium_low    = [f for f in security if f["severity"].value in ("medium", "low", "info")]

        if critical_high:
            lines.append("### Security — Critical / High")
            lines.append("")
            for f in critical_high:
                lines.append(f"**`{f['file']}`** - {f['title']}")
                lines.append(f"- **Severity:** `{f['severity'].value.upper()}`")
                if f.get("line"):
                    lines.append(f"- **Line:** `{f['line']}`")
                lines.append(f"- **Issue:** {f['description']}")
                lines.append(f"- **Fix:** {f['suggestion']}")
                lines.append("")

        if medium_low:
            lines.append("### Security — Medium / Low")
            lines.append("")
            for f in medium_low:
                lines.append(f"**`{f['file']}`** - {f['title']}")
                lines.append(f"- **Severity:** `{f['severity'].value.upper()}`")
                if f.get("line"):
                    lines.append(f"- **Line:** `{f['line']}`")
                lines.append(f"- **Issue:** {f['description']}")
                lines.append(f"- **Fix:** {f['suggestion']}")
                lines.append("")
    
    if style:
        lines.append("### Style & Quality")
        lines.append("")
        for f in style:
            lines.append(f"**`{f['file']}`** - {f['title']}")
            lines.append(f"- **Severity:** `{f['severity'].value.upper()}`")
            lines.append(f"- **Issue:** {f['description']}")
            lines.append(f"- **Fix:** {f['suggestion']}")
            lines.append("")
    
    if not security and not style:
        lines.append(" No issues found.")
        lines.append("")

    lines.append("---")
    lines.append(f"* AI Security Agent {len(security + style)} finding(s)*")

    return chr(10).join(lines)

def _build_inline_comments(findings: list) -> list[dict]:
    """
    Build inline comment objects for findings that have line numbers.
    Findings without line number appear in the overall body only.
    """
    comments = []
    
    for f in findings:
        if not f.get("line"):
            continue
        try:
            line = int(str(f["line"]).split("-")[0])
        except (ValueError, TypeError):
            continue

        comments.append({
            "path": f["file"],
            "line": line,
            "body": (
                f"**{f['title']}**(`{f['severity'].value.upper()}`)\n\n"
                f"**Issue:** {f['description']}\n\n"
                f"**Suggestion:** {f['suggestion']}"
            )
        })
    return comments

async def supervisor_node(state: PRReviewState):
    """
    Runs after all specialist agents complete.
    Synthesizes findings → decides review outcome → posts to GitHub.
    """
    security = state["security_findings"] or []
    style = state["style_findings"] or []
    all_findings = security + style

    # Decide review outcome based on severity
    review_decsion = _decide_review_outcome(all_findings)

    # Format unified review body
    review_body = _format_review_body(security, style)

    inline_comments = _build_inline_comments(all_findings)

    #Post to Github via MCP
    await github_mcp_session.invoke_tool(
        MCPTool.CREATE_PULL_REQUEST_REVIEW,
        owner=state["owner"],
        repo=state["repo"],
        pull_number=state["pr_number"],
        body=review_body,
        event=review_decsion.value,
        comments=inline_comments, 
    )

    return {
        "final_review": review_body,
        "review_decision": review_decsion
    }

def supervisor_pipeline():
    """
    Builds and compiles the LangGraph review pipeline.
    Returns a compiled graph ready for .ainvoke()

    Called once at startup or lazily on first request.
    """
    graph = StateGraph(PRReviewState)

    # Register agent nodes
    graph.add_node("security_agent", security_agent_node)
    graph.add_node("style_agent", style_agent_node)
    graph.add_node("supervisor", supervisor_node)

    # Wire edges
    graph.add_edge(START, "security_agent")
    graph.add_edge(START, "style_agent")

    graph.add_edge("security_agent", "supervisor")
    graph.add_edge("style_agent", "supervisor")

    graph.add_edge("supervisor", END)

    compiled = graph.compile()
    logger.info("PR review worflow compiled")
    return compiled

# Lazily compiled — created on first use
_pipeline = None

def get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = supervisor_pipeline()
    return _pipeline