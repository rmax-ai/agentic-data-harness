"""Dataset schemas and model definitions."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Task(BaseModel):
    """A benchmark task definition."""

    id: str
    domain: str
    question: str
    expected_answer: ExpectedAnswer
    tolerance: float = 0.01
    required_concepts: list[str] = Field(default_factory=list)
    difficulty: str = "medium"


class ExpectedAnswer(BaseModel):
    """Expected answer for a benchmark task."""

    type: str = Field(default="numeric", description="Answer type: numeric, exact, set, or mapping")
    value: float | str | list[str] | dict[str, float | int | str]
    tolerance: float = 0.01
    sql: str | None = None  # Reference SQL for verification
