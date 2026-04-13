import logging
from langgraph.types import Send
from app.models.workflow_state import PRReviewState
from langgraph.graph import END

logger = logging.getLogger(__name__)

def chunk_router(state:PRReviewState) -> list[Send]:
    """
    Conditional edge: ingestion → [security_agent, style_agent] × N chunks.
    """
    chunks = state.get("chunks") or []
    linter_outputs = state.get("linter_outputs") or {}

    if not chunks:
        logger.info("Chunk router - no chunks to dispatch, skipping agents")
        return [Send("supervisor", {**state})]
    
    sends: list[Send] = []

    pr_context = {
        "owner": state["owner"],
        "repo": state["repo"],
        "pr_number": state["pr_number"],
        "head_sha":  state["head_sha"],
    }

    for i, chunk in enumerate(chunks):
        total_chars = len(chunk["diff_context"])
        logger.info(
            f"Chunk router - dispatching chunk {i} "
            f"({len(chunk['files'])} files) to all agents"
        )

        # Hard guard: skip chunks that are too large for the LLM context window
        if total_chars > 80_000:
            logger.warning(
                f"Chunk router — chunk {i} exceeds 80k chars, skipping "
                f"to avoid context overflow"
            )
            continue

        # Security agent - no linter output needed
        sends.append(Send("security_agent", {
            **pr_context,
            "chunk": chunk,
            "security_issues_identified": state.get("security_issues_identified") or [],
        }))

        # Style agent - with linter output
        sends.append(Send("style_agent",{
            **pr_context,
            "chunk": chunk,
            "linter_output": linter_outputs.get(i, {}),
            "style_issues_identified": state.get("style_issues_identified") or [],
        }))

    logger.info(
        f"Chunk router - {len(sends)} total Send(s) dispatched "
        f"({len(chunks)} chunks x 2 agents)"
    )
    return sends