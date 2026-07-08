"""Tests for agent prompt templates."""

from __future__ import annotations

from adh.agents.prompts import USER_MESSAGE_TEMPLATE


def test_user_prompt_includes_benchmark_date_and_relative_time_rule() -> None:
    prompt = USER_MESSAGE_TEMPLATE.format(
        question="How many events happened recently?",
        benchmark_date="2026-06-30",
        schema_summary="Table: events",
        query_history="No queries executed yet.",
        step=1,
        max_steps=8,
        error_context="",
        memory_context="",
    )

    assert "Benchmark date: 2026-06-30" in prompt
    assert 'For relative dates such as "last 30 days", use the benchmark date above' in prompt
