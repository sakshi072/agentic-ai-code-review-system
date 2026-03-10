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
        "messages": [HumanMessage(content=f"Review PR #{pr_data.number} commit {pr_data.head_sha[:7]}")],
    }

    # Fire and forget — webhook must return quickly (GitHub 10s timeout)
    # Pipeline runs in background, posts results back to PR when done
    asyncio.create_task(
        _run_pipeline(
            get_pipeline(), 
            initial_state, 
            pr_data.number,
            pr_data.repo_owner,
            pr_data.repo_name
        )
    )

async def _run_pipeline(pipeline, state:dict, pr_number:int, owner:str, repo:str):
    """Runs the agent pipeline in the background"""
    config = {
        "configurable":{
            "thread_id": f"pr-{owner}-{repo}-{pr_number}"
        }
    }
    logger.info(f"Agent pipeline starting for PR #{pr_number}")
    try:
        result = await pipeline.ainvoke(state, config=config)
        logger.info(f"✅ Pipeline complete — decision: {result.get('review_decision')}")
    except Exception as e:
        logger.error(f"Pipeline failed for PR #{pr_number}: {e}", exc_info=True)