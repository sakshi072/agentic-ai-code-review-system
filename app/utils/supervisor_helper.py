import logging
from app.models.workflow_state import ReviewDecision
from collections import defaultdict
from app.models.agent_finding_model import CuratedFinding

logger = logging.getLogger(__name__)

def _severity_order(f: CuratedFinding) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}.get(f.severity, 5)

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

def is_actionable(f: dict) -> bool:
    has_line     = bool(f.get("line"))
    has_fix      = bool(f.get("fix_code", "").strip())
    # fix_code alone isn't enough — need a line number to be actionable
    return has_line and (has_fix or bool(f.get("code_snippet", "").strip()))

def _join_lines(lines: list[str]) -> str:
    """Flatten list to string, expanding any embedded newlines within elements."""
    flat = []
    for item in lines:
        flat.extend(item.split("\n"))
    return "\n".join(flat)

def rebuild_open_issues(fresh_findings, prev_issues, analyzed_files, pr_files):
    carried_over = [
        issue for issue in prev_issues
        if issue["file"] not in analyzed_files and issue["file"] in pr_files
    ]
    return fresh_findings + carried_over

def format_finding(f: CuratedFinding) -> list[str]:
    lines = []
    lines.append(
        f"**`{f.file}`** — {f.title} "
        f"`[{f.finding_type.capitalize()} · {f.severity.upper()}]`"
    )

    # Code snippet with inline line numbers
    if f.code_snippet and f.code_snippet.strip():
        lines.append("")
        lines.append("```python")
        snippet_lines = f.code_snippet.strip().splitlines()
        if f.line and len(snippet_lines) == 1:
            # Single line — prefix directly
            lines.append(f"# line {f.line}")
            lines.append(snippet_lines[0])
        elif f.line:
            # Multi-line — number from the anchor line
            start = int(str(f.line).split(",")[0].strip().split("-")[0])
            for i, snippet_line in enumerate(snippet_lines):
                lines.append(f"{start + i:>4}  {snippet_line}")
        else:
            for snippet_line in snippet_lines:
                lines.append(snippet_line)
        lines.append("```")
        lines.append("")

    lines.append(f"- **Issue:** {f.description}")
    if f.fix_explanation:
        lines.append(f"- **Fix:** {f.fix_explanation}")
    lines.append("")

    if f.fix_code and f.fix_code.strip():
        lines.append("**Suggested Fix:**")
        lines.append("```python")
        lines.extend(f.fix_code.strip().splitlines())
        lines.append("```")

    lines.append("")
    return lines

def format_review_body(findings: list[CuratedFinding]) -> str:
    lines: list[str] = ["## AI Code Review", ""]
 
    if not findings:
        lines += [" No issues found.", "", "---", "*AI Review — 0 finding(s)*"]
        return "\n".join(lines)
 
    for f in sorted(findings, key=_severity_order):
        lines.extend(format_finding(f))
 
    lines += ["---", f"*AI Review — {len(findings)} finding(s)*"]
 
    # Flatten any embedded newlines within elements
    flat: list[str] = []
    for item in lines:
        flat.extend(item.split("\n"))
    return "\n".join(flat)

def build_inline_comments(findings: list[CuratedFinding]) -> list[dict]:
    """Build inline comment objects for findings that have valid line numbers."""
    grouped: dict[tuple, list] = defaultdict(list)
 
    for f in findings:
        if not f.line:
            continue
        try:
            line = int(str(f.line).split(",")[0].strip().split("-")[0])
        except (ValueError, TypeError):
            continue
        grouped[(f.file, line)].append(f)
 
    comments = []
    for (path, line), group in grouped.items():
        parts = []
        for f in group:
            part = (
                f"**{f.title}** "
                f"`[{f.finding_type.capitalize()} · {f.severity.upper()}]`\n\n"
                f"**Issue:** {f.description}"
            )
            if f.fix_explanation:
                part += f"\n\n**Fix:** {f.fix_explanation}"
            if f.fix_code.strip():
                clean = f.fix_code.strip()
                part += f"\n\n```python\n{clean}\n```"
            parts.append(part)
 
        comments.append({
            "path": path,
            "line": line,
            "body": "\n\n---\n\n".join(parts),
        })
 
    return comments