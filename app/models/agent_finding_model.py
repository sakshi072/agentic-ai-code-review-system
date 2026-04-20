"""
app/models/agent_finding_model.py

Key change: CuratedFinding.clean_fix_code now rejects fix_code that is
semantically identical to the code_snippet. This was causing the judge to
output the existing (already-added) code as a "fix", which confused reviewers.
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from app.models.workflow_state import Severity
from typing import Any
import re

FINDING_TYPES = ("security", "style", "logic", "performance")
SEVERITIES    = ("critical", "high", "medium", "low", "info")


def _strip_diff_markers(text: str) -> str:
    """Remove [line N] annotations and leading +/- markers for comparison."""
    text = re.sub(r"\[line \d+\]\s*", "", text)
    lines = [l[1:] if l.startswith(("+", "-")) else l for l in text.splitlines()]
    return "\n".join(lines).strip()


class AgentFindingSchema(BaseModel):
    """Single agent finding — schema enforced by LLM structured output."""
    severity:        Severity = Field(
        description="Severity level: critical, high, medium, low, or info"
    )
    file:            str = Field(
        description="Path to the file where the issue was found"
    )
    code_snippet:    str = Field(
        default="Line not provided",
        description=(
            "Copy the EXACT full line from the diff INCLUDING the [line N] annotation. "
            "Example: '+[line 25] SECRET_KEY = \"abc\"'. "
            "The [line N] prefix is required. Do NOT copy just the line number."
        )
    )
    title:           str = Field(
        max_length=100,
        description="Short one-line summary of the issue — max 6 words"
    )
    description:     str = Field(
        max_length=250,
        description="1 sentence: what is wrong and why it matters"
    )
    fix_explanation: str = Field(
        max_length=250,
        description="1 sentence: exactly what to change"
    )
    fix_code:        str = Field(
        default="",
        description=(
            "The corrected line(s) only — no explanation, no diff markers. "
            "Do NOT include leading '+' or '-' characters. "
            "Must be DIFFERENT from the current code. "
            "If the fix cannot be shown as a short snippet, leave empty."
        )
    )

    @field_validator("fix_code", mode="before")
    @classmethod
    def clean_fix_code(cls, v: str) -> str:
        if not v or str(v).strip().upper() in ("EMPTY", "N/A", "NONE", ""):
            return ""
        if any(marker in str(v) for marker in ("## Diff", "## PR diff", "[line ")):
            return ""
        cleaned = []
        for line in str(v).splitlines():
            cleaned.append(line[1:] if line.startswith(("+", "-")) else line)
        return "\n".join(cleaned)

    @model_validator(mode="after")
    def fix_must_differ_from_snippet(self) -> "AgentFindingSchema":
        """
        Clear fix_code if it is semantically identical to code_snippet.
        Catches the pattern where the LLM copies the existing added line
        as both the snippet and the suggested fix.
        """
        if self.fix_code and self.code_snippet:
            if _strip_diff_markers(self.fix_code) == _strip_diff_markers(self.code_snippet):
                self.fix_code = ""
        return self
    
    @field_validator("severity", mode="before")
    @classmethod
    def handle_severity_case(cls, v: Any) -> str:
        """Coerce 'HIGH' -> 'high' to match Severity Enum expectations."""
        if isinstance(v, str):
            return v.lower()
        return v

class ResponseSchema(BaseModel):
    findings: list[AgentFindingSchema] = Field(
        max_length=5,
        default_factory=list,
        description="Top 5 most critical security findings only"
    )
    
class CuratedFinding(BaseModel):
    """Single finding after LLM judge curation."""

    finding_type:    str = Field(description="One of: security, style, logic, performance")
    severity:        str = Field(description="One of: critical, high, medium, low, info")
    file:            str = Field(description="File path where the issue was found")
    line:            int = Field(description="Line number — copied from source finding")
    code_snippet:    str = Field(default="Line not provided", description="Exact annotated line from the diff")
    title:           str = Field(max_length=100, description="Short one-line summary")
    description:     str = Field(max_length=250, description="Why this matters")
    fix_explanation: str = Field(max_length=250, description="What to change")
    fix_code:        str = Field(
        default="",
        description=(
            "Corrected code snippet only. "
            "Must differ from the current code in code_snippet. "
            "Leave empty if the fix cannot be expressed as a short snippet."
        )
    )

    @field_validator("finding_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        return v.lower() if v.lower() in FINDING_TYPES else "logic"

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        return v.lower() if v.lower() in SEVERITIES else "medium"

    @field_validator("fix_code", mode="before")
    @classmethod
    def clean_fix_code(cls, v: str) -> str:
        if not v or str(v).strip().upper() in ("EMPTY", "N/A", "NONE", ""):
            return ""
        if any(marker in str(v) for marker in ("## Diff", "## PR diff", "### Security", "### Style", "### Logic", "### Performance")):
            return ""
        cleaned = []
        for line in str(v).splitlines():
            cleaned.append(line[1:] if line.startswith(("+", "-")) else line)
        return "\n".join(cleaned)

    @model_validator(mode="after")
    def fix_must_differ_from_snippet(self) -> "CuratedFinding":
        if self.fix_code and self.code_snippet:
            if _strip_diff_markers(self.fix_code) == _strip_diff_markers(self.code_snippet):
                self.fix_code = ""
        return self


class JudgeOutput(BaseModel):
    findings: list[CuratedFinding] = Field(max_length=5)