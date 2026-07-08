"""Tests for OpenAI SQL agent final-answer validation."""

from __future__ import annotations

from types import MethodType, SimpleNamespace

from adh.agents.openai_sql_agent import OpenAISQLAgent, _validate_final_answer
from adh.agents.schemas import AgentAction, FinalAnswer


def test_validate_final_answer_warns_when_label_question_returns_metric() -> None:
    warning = _validate_final_answer(
        question="Which country had the highest total gross order value (in euros)?",
        final_answer=FinalAnswer(
            value=104014.32,
            unit="EUR",
            explanation="Top row metric.",
            source_column="total_eur",
            source_row_index=0,
        ),
        query_history=[
            {
                "success": True,
                "preview": '[["DE", 104014.32]]',
            }
        ],
    )

    assert warning is not None
    assert "label" in warning
    assert "adjacent metric" in warning


def test_validate_final_answer_allows_label_value_for_label_question() -> None:
    warning = _validate_final_answer(
        question="Which country had the highest total gross order value (in euros)?",
        final_answer=FinalAnswer(
            value="DE",
            unit=None,
            explanation="Top row label.",
            source_column="country_code",
            source_row_index=0,
            supporting_value=104014.32,
        ),
        query_history=[
            {
                "success": True,
                "preview": '[["DE", 104014.32]]',
            }
        ],
    )

    assert warning is None


def test_solve_retries_once_after_advisory_final_answer_warning() -> None:
    responses = iter(
        [
            AgentAction(
                thought_summary="Run the grouped query.",
                action="query",
                sql="SELECT country_code, total_eur FROM results LIMIT 1",
                final_answer=None,
            ),
            AgentAction(
                thought_summary="I have the top row.",
                action="final",
                sql=None,
                final_answer=FinalAnswer(
                    value=104014.32,
                    unit="EUR",
                    explanation="Using the top row metric.",
                    source_column="total_eur",
                    source_row_index=0,
                ),
            ),
            AgentAction(
                thought_summary="The question asks for the country label.",
                action="final",
                sql=None,
                final_answer=FinalAnswer(
                    value="DE",
                    unit=None,
                    explanation="Top row country label.",
                    source_column="country_code",
                    source_row_index=0,
                    supporting_value=104014.32,
                ),
            ),
        ]
    )

    agent = object.__new__(OpenAISQLAgent)
    agent.model_config = SimpleNamespace(
        model="test-model",
        temperature=0,
        max_output_tokens=200,
        timeout_seconds=30,
    )
    agent._db = SimpleNamespace(get_benchmark_metadata=lambda: {"benchmark_date": "2026-06-30"})
    agent._gateway = SimpleNamespace(
        get_schema_summary=lambda: "Table: results(country_code, total_eur)",
        execute=lambda sql: SimpleNamespace(
            cache_status="miss",
            success=True,
            fingerprint="fp-1",
            error_type=None,
            error_message=None,
            row_count=1,
            latency_ms=2,
            rows=[("DE", 104014.32)],
            feedback=None,
        ),
    )
    agent.max_steps = 4
    agent._trace = None
    agent._memory = []
    agent._memory_store = None
    agent._last_prompt_tokens = 0
    agent._last_output_tokens = 0

    def fake_call_model(
        self: OpenAISQLAgent,
        user_message: str,
        mode: str,
        memory_context: str,
    ) -> AgentAction:
        del self, user_message, mode, memory_context
        return next(responses)

    agent._call_model = MethodType(fake_call_model, agent)

    result = agent.solve(
        task_id="sales_003",
        question="Which country had the highest total gross order value (in euros)?",
        run_id="run-1",
        mode="raw",
        domain="sales_analytics",
    )

    assert result["success"] is True
    assert result["steps"] == 3
    assert result["answer"]["value"] == "DE"
    assert result["answer"]["source_column"] == "country_code"
    assert result["answer"]["supporting_value"] == 104014.32
    warning_entries = [entry for entry in result["query_history"] if "warning" in entry]
    assert len(warning_entries) == 1
    assert "adjacent metric" in warning_entries[0]["warning"]
