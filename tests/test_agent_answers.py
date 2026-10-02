"""Tests for agent answer schemas and grouped-answer helpers."""

from __future__ import annotations

from adh.agents.openai_sql_agent import _format_rows
from adh.agents.schemas import FinalAnswer


def test_final_answer_accepts_string_value() -> None:
    """FinalAnswer.model_validate works with string values."""
    answer = FinalAnswer.model_validate(
        {
            "value": "midmarket",
            "unit": None,
            "explanation": "Top segment from the grouped query result.",
        }
    )

    assert answer.value == "midmarket"


def test_final_answer_accepts_dict_value() -> None:
    """FinalAnswer.model_validate works with dict values for grouped tasks."""
    answer = FinalAnswer.model_validate(
        {
            "value": {
                "2026-01": 22,
                "2026-02": 16,
            },
            "unit": "count",
            "explanation": "Monthly grouped ticket counts for 2026.",
        }
    )

    assert answer.value == {
        "2026-01": 22,
        "2026-02": 16,
    }


def test_format_rows_includes_columns_when_available() -> None:
    """Query history rendering handles column names when available."""
    preview = _format_rows(
        rows=[("access", 3.44), ("billing", 2.40)],
        columns=["category", "avg_score"],
    )

    assert preview == (
        '[{"category": "access", "avg_score": 3.44}, {"category": "billing", "avg_score": 2.4}]'
    )
