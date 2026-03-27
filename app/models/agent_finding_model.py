from pydantic import BaseModel, Field
from app.models.workflow_state import Severity
from enum import Enum
class FindingStatus(str, Enum):
    NEW                    = "new"
    PERSISTS               = "persists"        # was posted, still exists
    RESOLVED               = "resolved"        # was posted, no longer exists

class AgentFindingSchema(BaseModel):
    """Single agent finding — schema enforced by LLM structured output."""
    severity:    Severity = Field(description="Severity level: critical, high, medium, low, or info")
    file:        str      = Field(description="Path to the file where the issue was found")
    code_snippet: str = Field(
        description="Copy the exact line of code from the diff that contains the issue, "
                    "as it appears after the + sign. Used to locate the precise line number."
    )
    title:       str      = Field(description="Short one-line summary of the issue")
    description: str      = Field(description="Clear explanation of why this is a security risk")
    fix_explanation: str = Field(
        description=(
            "One sentence explaining what to change. "
            "Example: 'Remove trailing whitespace after the comma.'"
        )
    )
    fix_code: str = Field(
        description=(
            "The corrected code only — no explanation, no prose, no diff markers. "
            "Do NOT include leading '+' or '-' characters. "
            "For simple single-line fixes (remove trailing whitespace, remove unused import): "
            "write just the corrected line. "
            "For structural fixes (line too long, restructure block): "
            "include 2-3 lines of surrounding context so the location is clear. "
            "Write plain Python exactly as it should appear in the file."
        ),
        default=""
    )
    status: FindingStatus = Field(
        description=(
            "new — not in previous review. "
            "persists — was in previous review, still exists in current diff. "
            "resolved — was in previous review, no longer exists in current diff."
        )
    )

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

class StyleFindingSchema(BaseModel):
    severity:     Severity = Field(description="Severity: high, medium, low, or info")
    file:         str      = Field(description="Path to the file where the issue was found")
    code_snippet: str      = Field(
        description=(
            "REQUIRED. Copy the exact line from the diff after the '+' sign "
            "where the issue occurs. Example: '+    def x():'"
        )
    )
    title:       str = Field(description="Short one-line summary of the style issue")
    description: str = Field(description="Clear explanation of why this is a style or quality problem")
    fix_explanation: str = Field(
        description=(
            "One sentence explaining what to change. "
            "Example: 'Remove trailing whitespace after the comma.'"
        )
    )
    fix_code: str = Field(
        description=(
            "The corrected code only — no explanation, no prose, no diff markers. "
            "Do NOT include leading '+' or '-' characters. "
            "For simple single-line fixes (remove trailing whitespace, remove unused import): "
            "write just the corrected line. "
            "For structural fixes (line too long, restructure block): "
            "include 2-3 lines of surrounding context so the location is clear. "
            "Write plain Python exactly as it should appear in the file."
        ),
        default=""
    )
    status: FindingStatus = Field(
        description=(
            "new — not in previous review. "
            "persists — was in previous review, still exists in current diff. "
            "resolved — was in previous review, no longer exists in current diff."
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