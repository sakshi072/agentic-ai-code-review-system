import asyncio
from app.workflow.supervisor import get_pipeline
from langchain_core.messages import HumanMessage
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from app.models.pr_model import PRData
from app.core.configs.settings import settings
import logging

logger = logging.getLogger(__name__)
langfuse = Langfuse(
    secret_key=settings.LANGFUSE_SECRET_KEY,
    public_key=settings.LANGFUSE_PUBLIC_KEY,
    host=settings.LANGFUSE_BASE_URL
)
logger.info("Langfuse auth check: %s", langfuse.auth_check())

# Verify settings are loading
logger.info("Langfuse secret key: %s", settings.LANGFUSE_SECRET_KEY[:8])
logger.info("Langfuse public key: %s", settings.LANGFUSE_PUBLIC_KEY[:8])
logger.info("Langfuse host: %s", settings.LANGFUSE_BASE_URL)

# Create handler with same creds
langfuse_handler = CallbackHandler(
    public_key=settings.LANGFUSE_PUBLIC_KEY,
)

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
        },
        "callbacks":[langfuse_handler]
    }
    logger.info(f"Agent pipeline starting for PR #{pr_number}")
    try:
        result = await pipeline.ainvoke(state, config=config)
        logger.info(f"✅ Pipeline complete — decision: {result.get('review_decision')}")
    except Exception as e:
        logger.error(f"Pipeline failed for PR #{pr_number}: {e}", exc_info=True)