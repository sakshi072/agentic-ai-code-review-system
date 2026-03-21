import logging
from app.models.workflow_state import ReviewDecision
from collections import defaultdict

logger = logging.getLogger(__name__)

def decide_review_outcome(findings: list) -> ReviewDecision:
    # if not findings:
    #     return ReviewDecision.APPROVE
    if not findings:
        return ReviewDecision.COMMENT
    # severities = [f["severity"] for f in findings]
    # has_high_or_above = any(s.value in ("critical", "high") for s in severities)
    # if has_high_or_above:
    #     return ReviewDecision.REQUEST_CHANGES
    return ReviewDecision.COMMENT

def format_review_body(security: list, style: list) -> str:
    lines = []
    lines.append("## Security & Style Review")
    lines.append("")

    if security:
        critical_high = [f for f in security if f["severity"] in ("critical", "high")]
        medium_low    = [f for f in security if f["severity"] in ("medium", "low", "info")]

        if critical_high:
            lines.append("### Security — Critical / High")
            lines.append("")
            for f in critical_high:
                lines.append(f"**`{f['file']}`** - {f['title']}")
                lines.append(f"- **Severity:** `{f["severity"].upper()}`")
                if f.get("line"):
                    lines.append(f"- **Line:** `{f['line']}`")
                lines.append(f"- **Issue:** {f['description']}")
                lines.append(f"- **Fix:** {f['suggestion']}")
                lines.append("")

        if medium_low:
            lines.append("### Security — Medium / Low")
            lines.append("")
            for f in medium_low:
                lines.append(f"**`{f['file']}`** - {f['title']}")
                lines.append(f"- **Severity:** `{f["severity"].upper()}`")
                if f.get("line"):
                    lines.append(f"- **Line:** `{f['line']}`")
                lines.append(f"- **Issue:** {f['description']}")
                lines.append(f"- **Fix:** {f['suggestion']}")
                lines.append("")
    
    if style:
        lines.append("### Style & Quality")
        lines.append("")
        for f in style:
            lines.append(f"**`{f['file']}`** - {f['title']}")
            lines.append(f"- **Severity:** `{f["severity"].upper()}`")
            lines.append(f"- **Issue:** {f['description']}")
            lines.append(f"- **Fix:** {f['suggestion']}")
            lines.append("")
    
    if not security and not style:
        lines.append(" No issues found.")
        lines.append("")

    lines.append("---")
    lines.append(f"* AI Security Agent {len(security + style)} finding(s)*")

    return chr(10).join(lines)

def build_inline_comments(findings: list) -> list[dict]:
    """
    Build inline comment objects for findings that have line numbers.
    Findings without line number appear in the overall body only.
    """
    grouped: dict[tuple, list] = defaultdict(list)

    for f in findings:
        if not f.get("line"):
            continue
        try:
            line = int(str(f["line"]).split("-")[0])
        except (ValueError, TypeError):
            continue
        grouped[(f["file"], line)].append(f)
    
    sep = chr(10) + chr(10) + "---" + chr(10) + chr(10)
    comments = []
    for (path, line), group in grouped.items():
        parts = [
            f"**{f['title']}** (`{f['severity'].upper()}`)"
            + chr(10) + chr(10)
            + f"**Issue:** {f['description']}"
            + chr(10) + chr(10)
            + f"**Suggestion:** {f['suggestion']}"
            for f in group
        ]
        comments.append({
            "path": path,
            "line": line,
            "body": sep.join(parts),
        })
        
    return comments
