import asyncio
from app.workflow.supervisor import get_pipeline
from langchain_core.messages import HumanMessage
from app.models.pr_model import PRData
import logging

logger = logging.getLogger(__name__)

def start_supervisor(pr_data:PRData):
    initial_state = {
        "owner": pr_data.repo_owner,
        "repo": pr_data.repo_name,
        "pr_number": pr_data.number,
        "messages": [HumanMessage(content=f"Review PR #{pr_data.number} in {pr_data.repo_full_name}")],
    }

    # Fire and forget — webhook must return quickly (GitHub 10s timeout)
    # Pipeline runs in background, posts results back to PR when done
    asyncio.create_task(
        _run_pipeline(get_pipeline(), initial_state, pr_data.number)
    )

async def _run_pipeline(pipeline, state:dict, pr_number:int):
    """Runs the agent pipeline in the background"""
    logger.info(f"Agent pipeline starting for PR #{pr_number}")
    try:
        result = await pipeline.ainvoke(state)
        logger.info(f"✅ Pipeline complete — decision: {result.get('review_decision')}")
    except Exception as e:
        logger.error(f"Pipeline failed for PR #{pr_number}: {e}", exc_info=True)