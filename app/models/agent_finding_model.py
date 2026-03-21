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
    suggestion:  str      = Field(description="Concrete fix recommendation with code example if possible")
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
    suggestion:  str = Field(description="Concrete improvement with example if possible")
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