# Helper file for Github webhook verification and pr data classification
import logging
import hmac 
import hashlib
from app.core.settings import settings
from app.models.pr_models import PRData

logger = logging.getLogger(__name__)
GITHUB_WEBHOOK_SECRET = settings.GITHUB_WEBHOOK_SECRET

def verify_github_signature(payload_bytes:bytes, signature_header:str|None)-> bool:
    """
    Validates the X-Hub-Signature-256 header sent by GitHub.
    Skip verification when GITHUB_WEBHOOK_SECRET is not configured (local dev).
    """
    if not GITHUB_WEBHOOK_SECRET:
        logger.warning("GITHUB_WEBHOOK_SECRET not set - skipping signation verification (dev mode)")
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        logger.error("Empty or Invalid github signature header")
        return False
    
    expected = hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(f"sha256={expected}", signature_header)

def log_pr_data(pr: PRData, action:str) -> None:
    """
    Emit structured log lines for the incoming PR.
    Keeping log fields flat makes them easy to query in any log aggregator
    (Datadog, CloudWatch, Grafana Loki, etc.)
    """
    summary = pr.log_summary()

    logger.info("=" * 60)
    logger.info("  GitHub PR Webhook Received")
    logger.info("=" * 60)
    logger.info(f"  Action        : {action}")

    for key, value in summary.items():
        logger.info(f"  {key:<22}: {value}")

    # Size classification — useful later for routing to different agents
    size = classify_pr_size(pr.changed_files, pr.additions + pr.deletions)
    logger.info(f". {'pr_size':<22}: {size}")

    # Draft warning
    if pr.draft:
        logger.warning(".   PR is a DRAFT - review will be advisory only")
    
    logger.info("=" * 60)

def classify_pr_size(changed_files:int, total_lines:int) -> str:
    """
    Classify PR size — will drive agent behaviour later
    (e.g. skip deep analysis for XS, run all agents for XL)
    """
    if changed_files <= 2 and total_lines <= 50:
        return "XS"
    elif changed_files <= 5 and total_lines <= 200:
        return "S"
    elif changed_files <= 10 and total_lines <= 500:
        return "M"
    elif changed_files <= 20 and total_lines <= 1000:
        return "L"
    else:
        return "XL"
