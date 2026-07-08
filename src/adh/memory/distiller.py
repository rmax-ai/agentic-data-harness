"""Corrective-memory distillation from why-not feedback."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from adh.memory.store import CorrectiveMemory

_TASK_QUESTIONS: dict[str, str] = {}
_ACTIVE_MEMORY: CorrectiveMemory | None = None
_STOPWORDS = {
    "a",
    "all",
    "an",
    "and",
    "are",
    "as",
    "by",
    "did",
    "each",
    "for",
    "from",
    "had",
    "has",
    "have",
    "how",
    "in",
    "is",
    "last",
    "many",
    "of",
    "on",
    "or",
    "per",
    "the",
    "to",
    "was",
    "were",
    "what",
    "which",
    "who",
}
_GENERIC_FAILURE_MODES = {"syntax_error", "wrong_table", "unknown"}


def configure_memory_store(memory: CorrectiveMemory | None) -> None:
    """Configure the default corrective-memory store used by distillation."""
    global _ACTIVE_MEMORY
    _ACTIVE_MEMORY = memory


def register_task_question(task_id: str, question: str) -> None:
    """Register a task question so trigger patterns can reuse its keywords."""
    _TASK_QUESTIONS[task_id] = question


def clear_task_questions() -> None:
    """Clear all registered task questions."""
    _TASK_QUESTIONS.clear()


def distill_from_failure(
    domain: str,
    task_id: str,
    feedback: dict[str, Any],
    attempted_sql: str,
    memory: CorrectiveMemory | None = None,
) -> list[str]:
    """Create corrective-memory entries from structured failure feedback."""
    store = memory or _ACTIVE_MEMORY
    if store is None or not feedback:
        return []

    raw_failure_mode = str(feedback.get("error_type") or "unknown")
    if raw_failure_mode == "blocked_sql":
        return []

    failure_mode = "wrong_table" if raw_failure_mode == "missing_table" else raw_failure_mode
    question = _TASK_QUESTIONS.get(task_id, task_id)
    trigger_pattern = " ".join(_extract_keywords(question))
    table_name = _extract_first_table(attempted_sql)

    memory_ids: list[str] = []

    if failure_mode == "missing_column":
        column_name = _extract_missing_column_name(feedback.get("message", ""))
        available_columns = feedback.get("available_columns") or []
        suggested_columns = feedback.get("suggested_columns") or []
        correction = _build_missing_column_correction(
            table_name=table_name,
            column_name=column_name,
            available_columns=available_columns,
            suggested_columns=suggested_columns,
        )
        memory_ids.append(
            _store_memory(
                store=store,
                domain=domain,
                failure_mode=failure_mode,
                correction=correction,
                trigger_pattern=trigger_pattern,
                table_name=table_name,
                column_name=column_name,
            )
        )

    elif failure_mode == "type_mismatch":
        column_types = feedback.get("column_types") or {}
        relevant_columns = _extract_sql_columns(attempted_sql)
        matched_columns = [column for column in relevant_columns if column in column_types]
        target_columns = matched_columns or list(column_types)[:1] or [None]

        type_summary = ", ".join(
            f"{name}={dtype}" for name, dtype in list(column_types.items())[:10]
        )
        correction = (
            f"Check column types before filtering or casting. "
            f"{table_name or 'This table'} types: {type_summary or 'unknown'}."
        )

        memory_ids.extend(
            _store_memory(
                store=store,
                domain=domain,
                failure_mode=failure_mode,
                correction=correction,
                trigger_pattern=trigger_pattern,
                table_name=table_name,
                column_name=column_name,
            )
            for column_name in target_columns
        )

    elif failure_mode == "empty_result":
        diagnostics = feedback.get("diagnostics") or {}
        grouped = _group_empty_result_diagnostics(diagnostics)
        if not grouped:
            correction = (
                feedback.get("hint")
                or "Zero rows returned. Recheck filters against real sample values."
            )
            memory_ids.append(
                _store_memory(
                    store=store,
                    domain=domain,
                    failure_mode=failure_mode,
                    correction=correction,
                    trigger_pattern=trigger_pattern,
                    table_name=table_name,
                    column_name=None,
                )
            )
        else:
            for qualified_name, payload in grouped.items():
                diag_table, column_name = qualified_name.split(".", 1)
                samples = payload.get("samples") or []
                value_range = payload.get("range") or []
                parts = [f"Filters on {qualified_name} returned no rows."]
                if samples:
                    parts.append(f"Try real values such as {', '.join(samples[:5])}.")
                if value_range:
                    parts.append(f"Observed range: {value_range[0]} to {value_range[1]}.")
                memory_ids.append(
                    _store_memory(
                        store=store,
                        domain=domain,
                        failure_mode=failure_mode,
                        correction=" ".join(parts),
                        trigger_pattern=trigger_pattern,
                        table_name=diag_table,
                        column_name=column_name,
                    )
                )

    elif failure_mode == "ambiguous_column":
        column_name = _extract_quoted_identifier(feedback.get("message", ""))
        qualified_columns = feedback.get("columns_in_table") or []
        correction = (
            "Qualify overlapping column names explicitly. "
            f"Examples: {', '.join(qualified_columns[:8]) or 'table.column'}."
        )
        memory_ids.append(
            _store_memory(
                store=store,
                domain=domain,
                failure_mode=failure_mode,
                correction=correction,
                trigger_pattern=trigger_pattern,
                table_name=table_name,
                column_name=column_name,
            )
        )

    elif failure_mode in _GENERIC_FAILURE_MODES:
        correction = (
            "Avoid repeating this trap. "
            f"Raw error: {feedback.get('message', 'Unknown SQL failure')}."
        )
        memory_ids.append(
            _store_memory(
                store=store,
                domain=domain,
                failure_mode=failure_mode,
                correction=correction,
                trigger_pattern=trigger_pattern,
                table_name=table_name if failure_mode == "wrong_table" else None,
                column_name=None,
            )
        )

    return _unique(memory_ids)


def _store_memory(
    store: CorrectiveMemory,
    domain: str,
    failure_mode: str,
    correction: str,
    trigger_pattern: str,
    table_name: str | None,
    column_name: str | None,
) -> str:
    return store.store(
        domain=domain,
        failure_mode=failure_mode,
        correction=correction,
        table_name=table_name,
        column_name=column_name,
        trigger_pattern=trigger_pattern,
    )


def _build_missing_column_correction(
    table_name: str | None,
    column_name: str | None,
    available_columns: list[str],
    suggested_columns: list[str],
) -> str:
    location = (
        f"{table_name}.{column_name}" if table_name and column_name else (column_name or "column")
    )
    parts = [f"{location} does not exist."]
    if suggested_columns:
        parts.append(f"Try {', '.join(suggested_columns[:3])} instead.")
    if available_columns:
        parts.append(f"Available columns: {', '.join(available_columns[:10])}.")
    return " ".join(parts)


def _group_empty_result_diagnostics(diagnostics: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    grouped: dict[str, dict[str, list[str]]] = {}
    for key, value in diagnostics.items():
        if key.endswith("_samples"):
            qualified_name = key.removesuffix("_samples")
            grouped.setdefault(qualified_name, {})["samples"] = [str(item) for item in value]
        elif key.endswith("_range"):
            qualified_name = key.removesuffix("_range")
            grouped.setdefault(qualified_name, {})["range"] = [str(item) for item in value]
    return grouped


def _extract_first_table(sql: str) -> str | None:
    match = re.search(r"(?:FROM|JOIN)\s+([a-zA-Z_][\w]*)", sql, re.IGNORECASE)
    return match.group(1) if match else None


def _extract_sql_columns(sql: str) -> list[str]:
    qualified = re.findall(r"\b[a-zA-Z_][\w]*\.([a-zA-Z_][\w]*)\b", sql)
    bare = re.findall(
        r"\b(?:WHERE|AND|OR|SELECT|GROUP BY|ORDER BY)\s+([a-zA-Z_][\w]*)", sql, re.IGNORECASE
    )
    return _unique([*qualified, *bare])


def _extract_missing_column_name(message: str) -> str | None:
    return _extract_quoted_identifier(message) or _extract_named_column(message)


def _extract_quoted_identifier(message: str) -> str | None:
    match = re.search(r'"([^"]+)"', message)
    return match.group(1) if match else None


def _extract_named_column(message: str) -> str | None:
    match = re.search(r"column\s+([a-zA-Z_][\w]*)", message, re.IGNORECASE)
    return match.group(1) if match else None


def _extract_keywords(question: str, limit: int = 6) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9_]+", question.lower())
    keywords: list[str] = []
    for token in tokens:
        if token in _STOPWORDS or len(token) < 3:
            continue
        if token not in keywords:
            keywords.append(token)
        if len(keywords) >= limit:
            break
    return keywords


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
