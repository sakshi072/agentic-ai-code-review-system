"""
Shared state for the PR review LangGraph pipeline.

This TypedDict is the single object that flows through every node.
Each agent reads from it and writes its findings back into it.
The supervisor reads all findings and synthesizes the final review.
"""
from typing import TypedDict, Optional, Annotated
from enum import Enum
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
from app.utils.agent_helper import merge_dicts

class ReviewDecision(str, Enum):
    APPROVED = "APPROVED"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    COMMENT = "COMMENT"

class Severity(str, Enum):
    """
    Finding severity levels — ordered from highest to lowest.
    """
    CRITICAL = "critical"
    HIGH     = "high"
    MEDIUM   = "medium"
    LOW      = "low"
    INFO     = "info"

class Category(str, Enum):
    """Finding category — which specialist agent produced it."""
    SECURITY     = "security"
    STYLE        = "style"
    PERFORMANCE  = "performance"
    TEST_COVERAGE = "test_coverage"

class ReviewDecision(str, Enum):
    """
    GitHub PR review decision.
    Maps directly to values accepted by create_pull_request_review MCP tool.
    """
    APPROVE          = "APPROVE"
    REQUEST_CHANGES  = "REQUEST_CHANGES"
    COMMENT          = "COMMENT" 

class AgentFinding(TypedDict):
    """A single finding from a specialist agent"""
    severity: Severity  # enum — set by each agent
    category: Category  # enum — set by each agent
    file: str           # filename where the issue was found
    line: Optional[str] # line number or range if available
    title: str          # short one-line summary
    description: str    # details explanation
    suggestion: str    # concrete fix recommendation

class PRReviewState(TypedDict):
    """
    Shared state flowing through the entire LangGraph pipeline.

    Populated progressively:
        webhook → pr_metadata set
        security_agent → security_findings set
        style_agent → style_findings set
        test_agent → test_findings set
        supervisor → final_review set → posted to GitHub
    """
    # PR identity — set by webhook handler
    owner: str
    repo: str
    pr_number: int

    # Conversation messages for LangGraph ReAct agents
    messages: Annotated[list[BaseMessage], add_messages]

    # Agent Finding - each agent writes its own key
    security_findings: Optional[list[AgentFinding]]
    style_findings: Optional[list[AgentFinding]]
    test_findings: Optional[list[AgentFinding]]
    analyzed_file_shas:  Annotated[dict[str, str], merge_dicts]
    # Supervisor output
    final_review: Optional[str]     # markdown summary posted to GitHub
    review_decision: Optional[ReviewDecision]  # enum — maps to GitHub API value
