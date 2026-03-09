from pydantic import BaseModel, Field
from app.models.workflow_state import Severity

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

class SecurityResponseSchema(BaseModel):
    """Top-level structured response from the security agent LLM"""
    findings: list[AgentFindingSchema] = Field(
        default_factory=list,
        description="List of security findings. Empty list if no issues found."
    )