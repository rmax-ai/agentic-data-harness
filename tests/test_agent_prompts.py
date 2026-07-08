"""Tests for agent prompt templates."""

from __future__ import annotations

from adh.agents.prompts import (
    SYSTEM_PROMPT_CACHED_MEMORY,
    SYSTEM_PROMPT_RAW,
    USER_MESSAGE_TEMPLATE,
)


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


def test_user_prompt_final_answer_examples_allow_labels_and_source_fields() -> None:
    assert 'use a string for "which/what category/country/feature" questions' in USER_MESSAGE_TEMPLATE
    assert '"source_column": "<column that directly answered the question, e.g. country_code>"' in (
        USER_MESSAGE_TEMPLATE
    )
    assert '"source_row_index": <row index that contained the answer, usually 0>' in (
        USER_MESSAGE_TEMPLATE
    )
    assert (
        '- If the question asks "which", "what country", "what segment", or "what feature", return that label.'
        in USER_MESSAGE_TEMPLATE
    )
    assert "- Do not return an adjacent metric column from the same row." in USER_MESSAGE_TEMPLATE
    assert "MUST be a number" not in USER_MESSAGE_TEMPLATE


def test_system_prompts_include_constraint_checklist_and_final_answer_verification() -> None:
    checklist = (
        "Before writing SQL, identify the metric, entity, time window, status filter, "
        "grouping, and any coded fields (country_code, plan_code, segment)."
    )
    clause_rule = (
        "If the question mentions a date window, status, or grouping, make sure the SQL "
        "includes the corresponding WHERE or GROUP BY clause."
    )
    final_check = (
        "Before returning a final answer, verify the value answers the exact question "
        "asked, not a nearby metric."
    )

    for prompt in (SYSTEM_PROMPT_RAW, SYSTEM_PROMPT_CACHED_MEMORY):
        assert checklist in prompt
        assert clause_rule in prompt
        assert final_check in prompt
