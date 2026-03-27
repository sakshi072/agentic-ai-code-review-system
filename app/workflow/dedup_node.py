import logging
from app.models.workflow_state import PRReviewState

logger = logging.getLogger(__name__)

def group_repeated_findings(findings: list[dict]) -> list[dict]:
    """
    Collapse findings with the same file+title into one,
    listing all affected lines together.
    """
    from collections import defaultdict
    groups: dict[tuple, list] = defaultdict(list)
    for f in findings:
        key = (f["file"], f["title"].lower().strip().replace(" ", ""))
        groups[key].append(f)
    
    result = []
    for (file, _), group in groups.items():
        if len(group) == 1:
            result.append(group[0])
            continue
        # Merge into one finding with all line numbers
        lines = sorted(set(
            str(f["line"]) for f in group if f.get("line")
        ))
        merged = dict(group[0])  # copy first finding
        merged["line"] = ", ".join(lines) if lines else None
        merged["description"] = (
            f"{group[0]['description']} "
            f"({len(group)} occurrences: lines {', '.join(lines)})"
        )
        merged["fix_code"] = ""  # no single fix_code for grouped findings
        result.append(merged)
    return result

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
    grouped_style = group_repeated_findings(all_style) 

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
        "style_issues_identified":    rebuild_open_issues(grouped_style,    prev_style, analyzed_files),
    }