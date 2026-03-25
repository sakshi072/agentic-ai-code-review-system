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
from operator import add

def merge_dicts(a:dict | None, b:dict | None) -> dict:
    """Merge two dict - b override a keys"""
    return {**(a or {}), **(b or {})}

class Severity(str, Enum):
    """
    Finding severity levels — ordered from highest to lowest.
    """
    CRITICAL = "critical"
    HIGH     = "high"
    MEDIUM   = "medium"
    LOW      = "low"
    INFO     = "info"

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
    file: str           # filename where the issue was found
    line: Optional[str] # line number or range if available
    title: str          # short one-line summary
    description: str    # details explanation
    suggestion: str     # concrete fix recommendation
    status: str         # status of the issue founded

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
    head_sha: str

    # Conversation messages for LangGraph ReAct agents
    messages: Annotated[list[BaseMessage], add_messages]

    # Ingestion node states
    # Files that have changed SHA since the last run — agents read these
    files_to_analyze: Optional[list[dict]]
    # Pre-rendered diff string ready for LLM consumption — agents read this
    diff_context: Optional[str]
    # Raw patch per filename — used by agents for find_line_in_diff
    file_patches: Optional[dict[str,str]]

    # Agent Finding - each agent writes its own key
    security_findings: Optional[list[AgentFinding]]
    style_findings: Optional[list[AgentFinding]]
    
    # SHA map — merged across runs so unchanged files are skipped
    analyzed_file_shas:  Annotated[dict[str, str], merge_dicts]
    
    # Previously identified open issues — compared against on re-runs
    security_issues_identified: Optional[list[AgentFinding]]                       # List of Issue object combing every file's all issues in Security agent
    style_issues_identified: Optional[list[AgentFinding]]                          # List of Issue object combing every file's all issues in Style agent

    # Supervisor output
    final_review: Optional[str]                                                     # markdown summary posted to GitHub
    review_decision: Optional[ReviewDecision]                                       # enum — maps to GitHub API value
