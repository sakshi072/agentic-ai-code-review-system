import logging
from app.models.workflow_state import PRReviewState

logger = logging.getLogger(__name__)

# For analyzed files: use fresh LLM verdicts from this run's findings
# For untouched files: carry previous open issues forward (SHA guarantees unchanged)
def rebuild_open_issues(fresh_findings, prev_issues, analyzed_files):
    carried_over = [
        issue for issue in prev_issues
        if issue["file"] not in analyzed_files
    ]
    fresh_open = [
        f for f in fresh_findings
        if f["status"] in ("new", "persists")
    ]
    return fresh_open + carried_over

async def dedup_node(state: PRReviewState):
    all_security = state.get("security_findings") or []
    all_style = state.get("style_findings") or []

    prev_security = state.get("security_issues_identified") or []
    prev_style = state.get("style_issues_identified") or []

    # Files that were actually analyzed this run
    analyzed_files = {
        f.get("filename")
        for chunk in (state.get("chunks") or [])
        for f in chunk["files"]
    }

    # For analyzed files: use fresh LLM verdicts from this run's findings
    # For untouched files: carry previous open issues forward (SHA guarantees unchanged)
    return {
        "security_issues_identified": rebuild_open_issues(all_security, prev_security, analyzed_files),
        "style_issues_identified":    rebuild_open_issues(all_style,    prev_style, analyzed_files),
    }