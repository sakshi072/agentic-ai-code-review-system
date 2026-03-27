"""
PR Review Pipeline — LangGraph graph wiring the agent pipeline.

Current state: single security agent node.

Graph structure:
    START → Ingestion -> (security_agent + style_agent) -> Supervisor → END
"""
import logging
from langgraph.graph import StateGraph, START, END
from app.models.workflow_state import PRReviewState
from app.workflow.security_agent import security_agent_node
from app.clients.github_mcp_client import github_mcp_session
from app.core.configs.github_server_config import MCPTool
from app.workflow.style_agent import style_agent_node
from app.workflow.ingestion_node import ingestion_node
from app.workflow.dedup_node import dedup_node
from langgraph.checkpoint.memory import InMemorySaver
from app.utils.supervisor_helper import decide_review_outcome, format_review_body, build_inline_comments
from app.workflow.chunk_router import chunk_router
logger = logging.getLogger(__name__)
checkpointer = InMemorySaver()

async def supervisor_node(state: PRReviewState):
    """
    Runs after all specialist agents complete.
    Synthesizes findings → decides review outcome → posts to GitHub.
    """
    security = state["security_findings"] or []
    style = state["style_findings"] or []

    all_new = security + style

    logger.info(
        f"Supervisor — {len(all_new)} new findings")

    # Skip posting if no findings
    if not all_new:
        logger.info("No findings — skipping review post")
        return {
            "final_review":    None,
            "review_decision": None,
        }

    # Decide review outcome based on severity
    review_decsion = decide_review_outcome(all_new)
    review_body = format_review_body(security, style)
    inline_comments = build_inline_comments(all_new)

    logger.info(f"Posting body repr: {repr(review_body[:200])}")
    #Post to Github via MCP
    try:
        await github_mcp_session.invoke_tool(
        MCPTool.CREATE_PULL_REQUEST_REVIEW,
        owner=state["owner"],
        repo=state["repo"],
        pull_number=state["pr_number"],
        body=review_body,
        event=review_decsion.value,
        comments=inline_comments, 
        )
        logger.info(
            f"✅ Review posted — {review_decsion.value}, "
            f"{len(all_new)} new, {len(inline_comments)} inline comments"
        )
    except Exception as e:
        logger.error(f"Failed to post review: {e}")
        raise
    
    return {
        "final_review": review_body,
        "review_decision": review_decsion,
    }

def supervisor_pipeline():
    """
    Builds and compiles the LangGraph review pipeline.
    Returns a compiled graph ready for .ainvoke()

    Called once at startup or lazily on first request.
    """
    graph = StateGraph(PRReviewState)

    # Register agent nodes
    graph.add_node("ingestion", ingestion_node)
    graph.add_node("security_agent", security_agent_node)
    graph.add_node("style_agent", style_agent_node)
    graph.add_node("dedup", dedup_node)
    graph.add_node("supervisor", supervisor_node)

    # Wire edges
    # Ingestion runs first, alone
    graph.add_edge(START, "ingestion")

    # chunk_router is a conditional edge — returns Send[] for dynamic fan-out.
    # LangGraph dispatches all Send objects concurrently. Each agent node
    # runs once per Send, findings accumulate via the add reducer on state.
    graph.add_conditional_edges("ingestion", chunk_router)

    # Both agents converge on supervisor
    graph.add_edge("security_agent", "dedup")
    graph.add_edge("style_agent", "dedup")
    graph.add_edge("dedup", "supervisor")

    graph.add_edge("supervisor", END)

    compiled = graph.compile(checkpointer=checkpointer)
    logger.info("PR review worflow compiled")
    return compiled

# Lazily compiled — created on first use
_pipeline = None

def get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = supervisor_pipeline()
    return _pipeline