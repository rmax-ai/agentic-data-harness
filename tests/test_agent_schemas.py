"""Tests for agent response schemas."""

from __future__ import annotations

from adh.agents.schemas import AgentAction, FinalAnswer


def test_final_answer_allows_string_values_with_source_metadata() -> None:
    answer = FinalAnswer(
        value="DE",
        unit=None,
        explanation="Top country by gross order value.",
        source_column="country_code",
        source_row_index=0,
        supporting_value=104014.32,
    )

    assert answer.value == "DE"
    assert answer.source_column == "country_code"
    assert answer.source_row_index == 0
    assert answer.supporting_value == 104014.32


def test_agent_action_validates_final_answer_schema() -> None:
    action = AgentAction.model_validate(
        {
            "thought_summary": "I have the answer.",
            "action": "final",
            "sql": None,
            "final_answer": {
                "value": "midmarket",
                "unit": None,
                "explanation": "Highest ticket count segment from the top row.",
                "source_column": "segment",
                "source_row_index": 0,
                "supporting_value": 18,
            },
        }
    )

    assert action.final_answer is not None
    assert action.final_answer.value == "midmarket"
    assert action.final_answer.source_column == "segment"
    assert action.final_answer.supporting_value == 18
