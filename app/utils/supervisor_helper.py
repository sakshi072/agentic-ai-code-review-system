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

def _clean_fix_code(code: str) -> str:
    lines = []
    for line in code.splitlines():
        if line.startswith("+") or line.startswith("-"):
            lines.append(line[1:])  # strip the +/- but keep the indentation after it
        else:
            lines.append(line)
    return "\n".join(lines)

def _join_lines(lines: list[str]) -> str:
    """Flatten list to string, expanding any embedded newlines within elements."""
    flat = []
    for item in lines:
        flat.extend(item.split("\n"))
    return "\n".join(flat)

def format_finding(f: dict, show_line: bool = True) -> list[str]:
    lines = []
    lines.append(f"**`{f['file']}`** — {f['title']}")
    lines.append(f"- **Severity:** `{f['severity'].upper()}`")
    if show_line and f.get("line"):
        lines.append(f"- **Line:** `{f['line']}`")
    lines.append(f"- **Issue:** {f['description']}")
    if f.get("fix_explanation"):
        lines.append(f"- **Fix:** {f['fix_explanation']}")
    lines.append("")
    if f.get("fix_code", "").strip():
        clean = _clean_fix_code(f["fix_code"]).strip()
        lines.append("```python")
        lines.extend(clean.splitlines())
        lines.append("```")
    lines.append("")
    return lines

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
                lines.extend(format_finding(f))

        if medium_low:
            lines.append("### Security — Medium / Low")
            lines.append("")
            for f in medium_low:
                lines.extend(format_finding(f))
    
    if style:
        lines.append("### Style & Quality")
        lines.append("")
        for f in style:
            lines.extend(format_finding(f))
    
    if not security and not style:
        lines.append(" No issues found.")
        lines.append("")

    lines.append("---")
    total = len(security) + len(style)
    lines.append(f"*AI Review — {total} finding(s)*")
    result = _join_lines(lines)
    return result

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
        parts = []
        for f in group:
            part = (
                f"**{f['title']}** (`{f['severity'].upper()}`)\n\n"
                f"**Issue:** {f['description']}"
            )
            if f.get("fix_explanation"):
                part += f"\n\n**Fix:** {f['fix_explanation']}"
            if f.get("fix_code", "").strip():
                clean = _clean_fix_code(f["fix_code"]).strip()
                part += "\n\n```python\n" + clean + "\n```"
            parts.append(part)

        comments.append({
            "path": path,
            "line": line,
            "body": "\n\n---\n\n".join(parts),
        })
        
    return comments
