"""Agent output schemas, structured JSON for model responses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FinalAnswer(BaseModel):
    """Final answer structure."""

    value: float | str | int = Field(
        description=(
            "Answer value. Strings are valid for categorical answers such as a country, "
            "segment, or feature."
        )
    )
    unit: str | None = Field(default=None, description="Unit of measurement")
    explanation: str = Field(default="", description="How the answer was derived")
    source_column: str | None = Field(
        default=None,
        description="Column that directly answered the question",
    )
    source_row_index: int | None = Field(
        default=None,
        description="Row index in the final result set that contained the answer",
    )
    supporting_value: float | str | int | None = Field(
        default=None,
        description="Adjacent metric from the same row, if helpful for context",
    )


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
    final_answer: FinalAnswer | None = Field(
        default=None,
        description=(
            "Final answer with value, unit, explanation, and optional source metadata "
            "(when action=final)"
        ),
    )
