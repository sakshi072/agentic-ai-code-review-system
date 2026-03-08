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

logger = logging.getLogger(__name__)

def _decide_review_outcome(findings: list) -> ReviewDecision:
    if not findings:
        return ReviewDecision.APPROVE
    
    # severities = [f["severity"] for f in findings]
    # has_high_or_above = any(s.value in ("critical", "high") for s in severities)
    # if has_high_or_above:
    #     return ReviewDecision.REQUEST_CHANGES
    return ReviewDecision.COMMENT

def _format_review_body(findings: list) -> str:
    critical_high = [f for f in findings if f["severity"].value in ("critical", "high")]
    medium_low    = [f for f in findings if f["severity"].value in ("medium", "low", "info")]

    lines = []
    lines.append("## Security Review")
    lines.append("")

    if critical_high:
        lines.append("### Critical / High Severity")
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
        lines.append("### Medium / Low Severity")
        lines.append("")
        for f in medium_low:
            lines.append(f"**`{f['file']}`** - {f['title']}")
            lines.append(f"- **Severity:** `{f['severity'].value.upper()}`")
            if f.get("line"):
                lines.append(f"- **Line:** `{f['line']}`")
            lines.append(f"- **Issue:** {f['description']}")
            lines.append(f"- **Fix:** {f['suggestion']}")
            lines.append("")

    lines.append("---")
    lines.append(f"* AI Security Agent {len(findings)} finding(s)*")

    return chr(10).join(lines)

async def supervisor_node(state: PRReviewState):
    """
    Runs after all specialist agents complete.
    Synthesizes findings → decides review outcome → posts to GitHub.
    """
    security = state["security_findings"] or []

    # Decide review outcome based on severity
    review_decsion = _decide_review_outcome(security)

    # Format unified review body
    review_body = _format_review_body(security)

    # Post to Github via MCP
    await github_mcp_session.invoke_tool(
        MCPTool.CREATE_PULL_REQUEST_REVIEW,
        owner=state["owner"],
        repo=state["repo"],
        pull_number=state["pr_number"],
        body=review_body,
        event=review_decsion.value
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
    graph.add_node("supervisor", supervisor_node)

    # Wire edges
    graph.add_edge(START, "security_agent")
    graph.add_edge("security_agent", "supervisor")
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