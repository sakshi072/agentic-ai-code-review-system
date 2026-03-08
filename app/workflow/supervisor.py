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

def supervisor_pipeline():
    """
    Builds and compiles the LangGraph review pipeline.
    Returns a compiled graph ready for .ainvoke()

    Called once at startup or lazily on first request.
    """
    graph = StateGraph(PRReviewState)

    # Register agent nodes
    graph.add_node("security_agent", security_agent_node)
    # graph.add_node("supervisor", supervisor_node)

    # Wire edges
    graph.add_edge(START, "security_agent")
    # graph.add_edge("security_agent", "supervisor")
    # graph.add_edge("supervisor", END)
    graph.add_edge("security_agent", END)

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