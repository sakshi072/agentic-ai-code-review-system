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
from app.workflow.logic_agent import logic_agent_node
from app.workflow.performance_agent import performance_agent_node
from langgraph.checkpoint.memory import InMemorySaver
from app.utils.supervisor_helper import decide_review_outcome, format_review_body, build_inline_comments
from app.workflow.router import chunk_router
from app.tools.github_apis import _parse_review_ids, _tag_inline_comments, update_review
from app.models.agent_finding_model import JudgeOutput, CuratedFinding
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from app.core.configs.settings import settings
from langchain_core.messages import SystemMessage, HumanMessage
from app.core.prompts.supervisor_judge_prompt import JUDGE_SYSTEM_PROMPT, JUDGE_USER_TEMPLATE
import json

logger = logging.getLogger(__name__)
checkpointer = InMemorySaver()

_judge_llm = ChatOpenAI(
        model="gpt-5-nano",
        temperature=0,
        timeout=300,
        api_key=settings.OPEN_API_KEY
).with_structured_output(JudgeOutput)

async def _run_judge(
    security_findings: list[dict],
    style_findings: list[dict],
    logic_findings: list[dict],
    performance_findings: list[dict],
    carried_over: list[dict],
) -> list[CuratedFinding]:
    """
    Run the LLM judge over all findings — current run + carried-over.
    Uses structured output — no JSON parsing or validation needed.
    Falls back to empty list on any failure so the pipeline never crashes.
    """
    prompt = JUDGE_USER_TEMPLATE.format(
        total=len(security_findings) + len(style_findings),
        n_security=len(security_findings),
        n_style=len(style_findings),
        n_logic = len(logic_findings),
        n_performance = len(performance_findings),
        n_carried=len(carried_over),
        security_json=json.dumps(security_findings, indent=2, default=str),
        style_json=json.dumps(style_findings, indent=2, default=str),
        logic_json = json.dumps(logic_findings, indent=2, default=str),
        performance_json = json.dumps(performance_findings, indent=2, default=str),
        carried_json=json.dumps(carried_over, indent=2, default=str),
    )

    try:
        result: JudgeOutput = await _judge_llm.ainvoke([
            SystemMessage(content=JUDGE_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        logger.info(
            f"Judge — input: {len(security_findings)} security + "
            f"{len(style_findings)} style + {len(logic_findings)} logic + {len(performance_findings)} performance + {len(carried_over)} carried-over"
            f"→ {len(result.findings)} curated findings"
        )
        return result.findings

    except Exception as e:
        logger.error(f"Judge LLM call failed: {e}")
        return []

async def supervisor_node(state: PRReviewState):
    """
    Runs after all specialist agents complete.
    Synthesizes findings → decides review outcome → posts to GitHub.
    """
    raw_security         = state.get("security_findings") or []
    raw_style            = state.get("style_findings") or []
    raw_logic          = state.get("logic_findings") or []
    raw_performance = state.get("performance_findings") or []
    chunks               = state.get("chunks") or []
    n_expected           = len(chunks) * 1
    n_completed          = state.get("agents_completed", 0)
    prior_review_id      = state.get("prior_review_id")
    prior_review_node_id = state.get("prior_review_node_id")
    pr_files             = state.get("pr_files") or []

    logger.info(
        f"Supervisor — {n_completed}/{n_expected} agents done | "
        f"{len(raw_security)} security, {len(raw_style)} style findings, {len(raw_logic)} logic, {len(raw_performance)} performance findings"
    )
 
    # ── Guard: no chunks dispatched (all files unchanged) ────────────────────
    if n_expected == 0:
        logger.info("Supervisor — no chunks dispatched, nothing to post")
        return {
            "final_review":          None,
            "review_decision":       None,
            "prior_review_id":       prior_review_id,
            "prior_review_node_id":  prior_review_node_id,
        }

    if n_completed < n_expected:
        logger.info(
            f"Supervisor — waiting "
            f"({n_expected - n_completed} agent(s) still running)"
        )
        return {}
    
    logger.info(
        f"Supervisor — raw: {len(raw_security)} security, "
        f"{len(raw_style)} style"
    )

    # ── Compute carried-over issues from unchanged files
    prev_all = state.get("open_issues_identified") or []
    all_pr_filenames = {f.get("filename") for f in pr_files}
    analyzed_files   = {
        f.get("filename")
        for chunk in chunks
        for f in chunk["files"]
    }

    carried_over = [
        issue for issue in prev_all
        if issue["file"] not in analyzed_files          # not re-analyzed this run
        and issue["file"] in all_pr_filenames           # still present in the PR
    ]
 
    logger.info(
        f"Supervisor — sending to judge: "
        f"{len(raw_security)} security + {len(raw_style)} style + {len(raw_logic)} logic + {len(raw_performance)} performance +"
        f"{len(carried_over)} carried-over"
    )
    
    # ── Aggregate diff context across all chunks
    diff_context = "\n\n".join(
        chunk.get("diff_context", "") for chunk in chunks
    )

    logger.info(f"diff context with line number : {diff_context}")

    logger.info(
        f"Agent findings with line numbers: "
        f"{sum(1 for f in raw_security + raw_style if f.get('line'))}/"
        f"{len(raw_security) + len(raw_style) + len(raw_logic) + len(raw_performance)}"
    )

    # ── LLM judge: curate all findings into one unified list
    curated = await _run_judge(raw_security, raw_style, raw_logic, raw_performance, carried_over, diff_context)

    for f in curated:
        logger.info(f"logging curated findings: {f}")
 
    logger.info(
        f"Supervisor — judge output: {len(curated)} finding(s) | "
        f"severities: { {f.severity for f in curated} }"
    )

    # open_issues is the judge's output — single flat list for next run
    open_issues = [f.model_dump() for f in curated]
 
    if not curated:
        logger.info("Supervisor — no findings after judge, skipping post")
        return {
            "final_review":          None,
            "review_decision":       None,
            "prior_review_id":       prior_review_id,
            "prior_review_node_id":  prior_review_node_id,
            "open_issues_identified": open_issues,
        }

    owner = state["owner"]
    repo = state["repo"]
    pr_number = state["pr_number"]

    # Decide review outcome based on severity
    review_decision = decide_review_outcome(curated)
    review_body     = format_review_body(curated)
    inline_comments = _tag_inline_comments(build_inline_comments(curated))
    
    if prior_review_id is not None:
        logger.info(f"Supervisor — updating prior review {prior_review_id}")
        await update_review(owner, repo, pr_number, prior_review_id, review_body)
        logger.info(
            f"Review updated — {review_decision.value} | "
            f"{len(curated)} finding(s) | {len(inline_comments)} inline comment(s)"
        )
        return {
            "final_review":           review_body,
            "review_decision":        review_decision,
            "prior_review_id":        prior_review_id,
            "prior_review_node_id":   prior_review_node_id,
            "open_issues_identified": open_issues,
        }

    #Post to Github via MCP
    try:
        response = await github_mcp_session.invoke_tool(
            MCPTool.CREATE_PULL_REQUEST_REVIEW,
            owner=owner,
            repo=repo,
            pull_number=pr_number,
            body=review_body,
            event=review_decision.value,
            # comments=inline_comments,
        )
        new_review_id, new_review_node_id = _parse_review_ids(response)
        logger.info(
            f"Review posted — {review_decision.value} | "
            f"id={new_review_id} | node={new_review_node_id} | "
            f"{len(curated)} finding(s) | {len(inline_comments)} inline comment(s)"
        )
    except Exception as e:
        logger.error(f"Failed to post review: {e}")
        raise
 
    return {
        "final_review":           review_body,
        "review_decision":        review_decision,
        "prior_review_id":        new_review_id,
        "prior_review_node_id":   new_review_node_id,
        "open_issues_identified": open_issues,
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
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("logic_agent", logic_agent_node)
    graph.add_node("performance_agent", performance_agent_node)
    # Wire edges
    # Ingestion runs first, alone
    graph.add_edge(START, "ingestion")

    # chunk_router is a conditional edge — returns Send[] for dynamic fan-out.
    # LangGraph dispatches all Send objects concurrently. Each agent node
    # runs once per Send, findings accumulate via the add reducer on state.
    graph.add_conditional_edges("ingestion", chunk_router)

    # Both agents converge on supervisor
    graph.add_edge("security_agent", "supervisor")
    graph.add_edge("style_agent", "supervisor")
    graph.add_edge("logic_agent", "supervisor")
    graph.add_edge("performance_agent", "supervisor")
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