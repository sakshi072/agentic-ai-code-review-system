from pydantic import BaseModel, Field, field_validator, model_validator
from app.models.workflow_state import Severity
from typing import Optional
import re

FINDING_TYPES = ("security", "style", "quality")
SEVERITIES    = ("critical", "high", "medium", "low", "info")
class AgentFindingSchema(BaseModel):
    """Single agent finding — schema enforced by LLM structured output."""
    severity:        Severity = Field(
        description="Severity level: critical, high, medium, low, or info"
    )
    file:            str = Field(
        description="Path to the file where the issue was found"
    )
    code_snippet:    str = Field(
        description=(
            "Copy the EXACT full line from the diff INCLUDING the [line N] annotation exactly as shown. "
            "Example: '+[line 25] SECRET_KEY = \"abc\"' → copy '+[line 25] SECRET_KEY = \"abc\"'. "
            "The [line N] prefix is required to locate the finding. "
            "Do NOT copy just the line number. Copy the actual code."
            "If the issue spans multiple lines, copy only the first affected line."
        )
    )
    title:           str = Field(
        description="Short one-line summary of the issue — max 6 words"
    )
    description:     str = Field(
        description="1-2 sentences: what is wrong and why it matters"
    )
    fix_explanation: str = Field(
        description="One sentence: exactly what to change"
    )
    fix_code:        str = Field(
        default="",
        description=(
            "The corrected line(s) only — no explanation, no diff markers. "
            "Do NOT include leading '+' or '-' characters. "
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

class SecurityResponseSchema(BaseModel):
    """Top-level structured response from the security agent LLM"""
    findings: list[AgentFindingSchema] = Field(
        default_factory=list,
        description=(
            "ALL security issue findings — new, persisting, and resolved. "
            "Include every previously posted issue with its current status. "
            "Do not omit anything from the previous review."
        )
    )

class StyleResponseSchema(BaseModel):
    findings: list[AgentFindingSchema] = Field(
        default_factory=list,
        description=(
            "ALL Style issue findings — new, persisting, and resolved. "
            "Include every previously posted issue with its current status. "
            "Do not omit anything from the previous review."
        )
    )

class CuratedFinding(BaseModel):
    """Single finding after LLM judge curation."""
 
    finding_type:    str           = Field(description="One of: security, style, quality")
    severity:        str           = Field(description="One of: critical, high, medium, low, info")
    file:            str           = Field(description="File path where the issue was found")
    line:            int  = Field(description="Line number — MUST be copied from source finding if present")
    code_snippet:    str = Field(
        description=(
            "Copy the EXACT full line from the diff"
            "Do NOT copy just the number. Copy the actual code."
            "If the issue spans multiple lines, copy only the first affected line."
        )
    )
    title:           str           = Field(description="Short one-line summary of the issue")
    description:     str           = Field(description="Clear explanation of why this matters")
    fix_explanation: str           = Field(description="One sentence: what to change and why")
    fix_code:        str           = Field(default="", description="Corrected code snippet if applicable, do not include diff sections")
 
    @field_validator("finding_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        return v.lower() if v.lower() in FINDING_TYPES else "style"
 
    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        return v.lower() if v.lower() in SEVERITIES else "medium"
 
    @field_validator("fix_code", mode="before")
    @classmethod
    def clean_fix_code(cls, v: str) -> str:
        if not v or str(v).strip().upper() in ("EMPTY", "N/A", "NONE", ""):
            return ""
        # Reject if it looks like prompt content leaked in
        if any(marker in str(v) for marker in ("## Diff", "## PR diff", "### Security", "### Style")):
            return ""
        cleaned = []
        for line in str(v).splitlines():
            cleaned.append(line[1:] if line.startswith(("+", "-")) else line)
        return "\n".join(cleaned)
    
class JudgeOutput(BaseModel):
    findings: list[CuratedFinding]