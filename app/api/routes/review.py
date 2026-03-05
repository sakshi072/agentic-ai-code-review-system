from fastapi import APIRouter, Request, Header, HTTPException
import logging
import json
from app.utils.pr_helper import verify_github_signature, log_pr_data, classify_pr_size
from app.models.pr_models import PRData

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/review', tags=["PR-Review"])

SUPPORTED_ACTIONS = {"opened", "synchronize", "reopened"}

@router.post("/webhook")
async def review_pr(
    request: Request,
    x_github_event: str = Header(None, alias="x-github-event"),
    x_hub_signature_256: str = Header(None, alias="x-hub-signature-256")
):
    """
    GitHub webhook receiver for Pull Request events.
    Triggered on: opened | synchronize | reopened
    Validates signature → parses payload → logs structured PR data → (agents next)
    """
    # Read raw bytes first (needed for signature verification)
    payload_bytes = await request.body()
    logger.info(f"DEBUG: Received Body: {payload_bytes.decode()[:100]}...")

    # Verify Github signature
    if not verify_github_signature(payload_bytes, x_hub_signature_256):
        logger.error(" Invalid GitHub webhook signature — rejecting request")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    # Parse JSON
    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse webhook payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    
    # Filter: only handle pull_request events
    if x_github_event != "pull_request":
        logger.info(f" Ingoring Github event: '{x_github_event}' (not a PR event)")
        return {"status": "ignored", "reason": f"event '{x_github_event}' not handled"}
    
    # Filter: only handle relevant PR actions
    action = payload.get("action", "")
    if action not in SUPPORTED_ACTIONS:
        logger.info(f" Ingoring PR action: '{x_github_event}'")
        return {"status": "ignored", "reason": f"event '{x_github_event}' not handled"}
    
    # Parse into structured PRData model
    try:
        pr_data = PRData.from_webhook_payload(payload)
    except (KeyError, ValueError) as e:
        logger.error(f"  Failed to parse PR payload into PRData: {e}")
        raise HTTPException(status_code=422, detail=f"Payload parse error: {e}")
    
    # Structured logging
    log_pr_data(pr_data, action)

    # TODO: Dispatch to agent pipeline (next step)
    logger.info(f"🔜 PR #{pr_data.number} queued for agent review pipeline")

    return {
        "status": "accepted",
        "pr_number": pr_data.number,
        "repo": pr_data.repo_full_name,
        "action": action,
        "pr_size": classify_pr_size(pr_data.changed_files, pr_data.additions + pr_data.deletions),
        "message": f"PR #{pr_data.number} received — review pipeline will start shortly",
    }