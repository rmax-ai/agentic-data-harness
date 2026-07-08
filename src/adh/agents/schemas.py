"""Agent output schemas — structured JSON for model responses."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentAction(BaseModel):
    """Structured output from the agent."""

    thought_summary: str = Field(
        default="",
        description="Short summary of reasoning",
    )
    action: Literal["query", "final"] = Field(
        ...,
        description="Next action: issue a query or provide final answer",
    )
    sql: str | None = Field(
        default=None,
        description="SQL query to execute (when action=query)",
    )
    final_answer: dict[str, Any] | None = Field(
        default=None,
        description="Final answer with value, unit, and explanation (when action=final)",
    )


class FinalAnswer(BaseModel):
    """Final answer structure."""

    value: float | str | int = Field(description="Answer value")
    unit: str | None = Field(default=None, description="Unit of measurement")
    explanation: str = Field(default="", description="How the answer was derived")
