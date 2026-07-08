"""OpenAI-powered SQL agent with structured JSON output."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from openai import OpenAI

from adh.agents.prompts import SYSTEM_PROMPT_RAW, USER_MESSAGE_TEMPLATE
from adh.agents.schemas import AgentAction
from adh.memory.distiller import distill_from_failure
from adh.tracing.events import EventType, TraceEvent, TraceStore

if TYPE_CHECKING:
    from adh.config import ModelConfig
    from adh.db.duckdb_runner import DuckDBRunner
    from adh.gateway.sql_gateway import SQLGateway
    from adh.memory.store import CorrectiveMemory


class OpenAISQLAgent:
    """Data-analysis agent using OpenAI Responses API with structured JSON output."""

    def __init__(
        self,
        model_config: ModelConfig,
        db_runner: DuckDBRunner,
        gateway: SQLGateway,
        max_steps: int = 8,
        trace_store: TraceStore | None = None,
        memory_items: list[str] | None = None,
        memory_store: CorrectiveMemory | None = None,
    ):
        self.model_config = model_config
        self._db = db_runner
        self._gateway = gateway
        self.max_steps = max_steps
        self._trace = trace_store
        self._memory = memory_items or []
        self._memory_store = memory_store

        api_key = os.getenv("OPENAI_API_KEY") or ""
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY not set. Set it via environment variable or .env file."
            )

        base_url = os.getenv("OPENAI_BASE_URL")
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url

        self._client = OpenAI(**kwargs)

    def solve(
        self,
        task_id: str,
        question: str,
        run_id: str,
        mode: str = "raw",
        domain: str | None = None,
    ) -> dict[str, Any]:
        """Run the agent loop for one task. Return result dict."""
        query_history: list[dict] = []
        schema_summary = self._gateway.get_schema_summary()
        error_context = ""
        retrieved_memories = self._retrieve_memories(
            run_id=run_id,
            task_id=task_id,
            question=question,
            domain=domain,
            mode=mode,
        )
        created_memory_ids: list[str] = []
        memory_context = _format_memory_context(retrieved_memories, self._memory)

        for step in range(1, self.max_steps + 1):
            user_message = USER_MESSAGE_TEMPLATE.format(
                question=question,
                schema_summary=schema_summary,
                query_history=json.dumps(query_history, indent=2)
                if query_history
                else "No queries executed yet.",
                step=step,
                max_steps=self.max_steps,
                error_context=error_context,
                memory_context=memory_context,
            )

            response = self._call_model(user_message, mode, memory_context)

            action = response.action
            thought = response.thought_summary or ""

            if action == "final" and response.final_answer:
                self._record_event(
                    run_id,
                    task_id,
                    mode,
                    step,
                    EventType.FINAL_ANSWER,
                    prompt_tokens=self._last_prompt_tokens,
                    output_tokens=self._last_output_tokens,
                    extra={"final_answer": response.final_answer},
                )
                return {
                    "task_id": task_id,
                    "success": True,
                    "answer": response.final_answer,
                    "steps": step,
                    "query_history": query_history,
                    "retrieved_memory_ids": [item["memory_id"] for item in retrieved_memories],
                    "created_memory_ids": created_memory_ids,
                }

            elif action == "query" and response.sql:
                sql = response.sql
                result = self._gateway.execute(sql)

                cache_status = result.cache_status or "executed"
                event_type = (
                    EventType.CACHE_HIT
                    if cache_status == "hit"
                    else EventType.CACHE_MISS
                    if cache_status == "miss"
                    else EventType.SQL_EXECUTION
                )

                self._record_event(
                    run_id,
                    task_id,
                    mode,
                    step,
                    event_type,
                    sql=sql,
                    sql_fingerprint=result.fingerprint,
                    prompt_tokens=self._last_prompt_tokens,
                    output_tokens=self._last_output_tokens,
                    success=result.success,
                    error_type=result.error_type,
                    error_message=result.error_message,
                    result_row_count=result.row_count,
                    latency_ms=result.latency_ms,
                    cache_status=cache_status,
                )

                query_entry = {
                    "step": step,
                    "thought": thought,
                    "sql": sql,
                    "success": result.success,
                    "cache_status": cache_status,
                    "latency_ms": result.latency_ms,
                }

                if result.success:
                    query_entry["rows"] = len(result.rows)
                    query_entry["preview"] = _format_rows(result.rows[:5])
                    query_history.append(query_entry)
                    error_context = ""

                    # If rows are empty, provide diagnostic feedback via why-not
                    if result.row_count == 0:
                        fb = result.feedback or {}
                        diag = fb.get("diagnostics", {})
                        hint = fb.get("hint", "")
                        error_context = "Query returned zero rows.\n"
                        if hint:
                            error_context += f"Hint: {hint}\n"
                        if diag:
                            error_context += f"Available values: {json.dumps(diag)[:300]}\n"
                        self._record_failure_feedback(
                            run_id=run_id,
                            task_id=task_id,
                            mode=mode,
                            step=step,
                            feedback=fb,
                        )
                        _extend_unique(
                            created_memory_ids,
                            self._distill_failure(
                                run_id=run_id,
                                task_id=task_id,
                                mode=mode,
                                step=step,
                                domain=domain,
                                feedback=fb,
                                attempted_sql=sql,
                            ),
                        )
                else:
                    query_entry["error"] = result.error_message
                    query_entry["error_type"] = result.error_type
                    query_history.append(query_entry)

                    error_context = (
                        f"Last query failed: {result.error_type} - {result.error_message}\n"
                    )
                    if result.feedback:
                        fb = result.feedback
                        hint = fb.get("hint", "")
                        if hint:
                            error_context += f"Hint: {hint}\n"
                        # Show available columns
                        avail_cols = fb.get("available_columns")
                        if avail_cols:
                            error_context += f"Available columns in referenced table: {', '.join(avail_cols[:20])}\n"
                        # Show suggested columns
                        suggested = fb.get("suggested_columns")
                        if suggested:
                            error_context += f"Did you mean: {', '.join(suggested)}?\n"
                        # Show diagnostics (sample values, date ranges)
                        diag = fb.get("diagnostics", {})
                        if diag:
                            error_context += f"Diagnostics: {json.dumps(diag)[:300]}\n"
                        self._record_failure_feedback(
                            run_id=run_id,
                            task_id=task_id,
                            mode=mode,
                            step=step,
                            feedback=fb,
                        )
                        _extend_unique(
                            created_memory_ids,
                            self._distill_failure(
                                run_id=run_id,
                                task_id=task_id,
                                mode=mode,
                                step=step,
                                domain=domain,
                                feedback=fb,
                                attempted_sql=sql,
                            ),
                        )

                continue

            else:
                # Invalid action — force retry
                query_history.append(
                    {
                        "step": step,
                        "thought": thought,
                        "error": f"Invalid action: {action}. Must be 'query' with SQL or 'final' with answer.",
                    }
                )
                error_context = "Invalid response format. Respond with valid JSON: action=query with sql, or action=final with final_answer."
                continue

        # Ran out of steps
        self._record_event(
            run_id,
            task_id,
            mode,
            self.max_steps,
            EventType.TASK_FAILED,
            extra={"reason": "max_steps_exceeded"},
        )
        return {
            "task_id": task_id,
            "success": False,
            "answer": None,
            "steps": self.max_steps,
            "query_history": query_history,
            "error": "max_steps_exceeded",
            "retrieved_memory_ids": [item["memory_id"] for item in retrieved_memories],
            "created_memory_ids": created_memory_ids,
        }

    def _call_model(self, user_message: str, mode: str, memory_context: str) -> AgentAction:
        """Call the OpenAI API and parse structured JSON response."""
        self._last_prompt_tokens = 0
        self._last_output_tokens = 0

        system = SYSTEM_PROMPT_RAW
        if mode == "cached_memory":
            from adh.agents.prompts import SYSTEM_PROMPT_CACHED_MEMORY

            system = SYSTEM_PROMPT_CACHED_MEMORY.format(
                memory_items=memory_context or "No prior corrective memory."
            )

        try:
            completion = self._client.chat.completions.create(
                model=self.model_config.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
                temperature=self.model_config.temperature,
                max_completion_tokens=self.model_config.max_output_tokens,
                timeout=self.model_config.timeout_seconds,
                response_format={"type": "json_object"},
            )

            self._last_prompt_tokens = completion.usage.prompt_tokens if completion.usage else 0
            self._last_output_tokens = completion.usage.completion_tokens if completion.usage else 0

            raw = completion.choices[0].message.content
            if not raw:
                raise ValueError("Empty response from model")

            # Extract JSON from potentially noisy output (trailing text, markdown fences)
            data = _extract_json(raw)
            return AgentAction.model_validate(data)

        except (json.JSONDecodeError, ValueError) as e:
            # Model returned invalid JSON — treat as a retry signal
            return AgentAction(
                thought_summary=f"Invalid response format: {str(e)[:100]}",
                action="query",
                sql="SELECT 1",
            )

    def _retrieve_memories(
        self,
        run_id: str,
        task_id: str,
        question: str,
        domain: str | None,
        mode: str,
    ) -> list[dict[str, Any]]:
        if mode != "cached_memory" or self._memory_store is None or not domain:
            return []

        tables, columns = _infer_memory_filters(self._db, question)
        memories = self._memory_store.retrieve(
            domain=domain,
            tables=tables or None,
            columns=columns or None,
            failure_modes=[
                "missing_column",
                "type_mismatch",
                "empty_result",
                "ambiguous_column",
                "syntax_error",
                "wrong_table",
                "unknown",
            ],
            limit=3,
        )
        self._record_event(
            run_id=run_id,
            task_id=task_id,
            mode=mode,
            step=0,
            event_type=EventType.MEMORY_RETRIEVED,
            extra={
                "memory_ids": [item["memory_id"] for item in memories],
                "tables": tables,
                "columns": columns,
                "count": len(memories),
            },
        )
        return memories

    def _distill_failure(
        self,
        run_id: str,
        domain: str | None,
        task_id: str,
        mode: str,
        step: int,
        feedback: dict[str, Any],
        attempted_sql: str,
    ) -> list[str]:
        if self._memory_store is None or not domain:
            return []
        memory_ids = distill_from_failure(
            domain=domain,
            task_id=task_id,
            feedback=feedback,
            attempted_sql=attempted_sql,
            memory=self._memory_store,
        )
        if memory_ids:
            self._record_event(
                run_id,
                task_id,
                mode,
                step,
                EventType.MEMORY_WRITTEN,
                success=True,
                error_type=feedback.get("error_type"),
                error_message=feedback.get("message"),
                extra={"memory_ids": memory_ids, "feedback": feedback},
            )
        return memory_ids

    def _record_failure_feedback(
        self,
        run_id: str,
        task_id: str,
        mode: str,
        step: int,
        feedback: dict[str, Any],
    ) -> None:
        error_type = feedback.get("error_type")
        self._record_event(
            run_id,
            task_id,
            mode,
            step,
            EventType.FAILURE_CLASSIFIED,
            success=False,
            error_type=error_type,
            error_message=feedback.get("message"),
            extra={"feedback": feedback},
        )

    def _record_event(
        self,
        run_id: str,
        task_id: str,
        mode: str,
        step: int,
        event_type: EventType,
        **kwargs: Any,
    ):
        if self._trace:
            self._trace.record(
                TraceEvent(
                    run_id=run_id,
                    task_id=task_id,
                    mode=mode,
                    step=step,
                    event_type=event_type,
                    model=self.model_config.model,
                    **kwargs,
                )
            )

    @property
    def _last_prompt_tokens(self) -> int:
        return getattr(self, "__last_prompt_tokens", 0)

    @_last_prompt_tokens.setter
    def _last_prompt_tokens(self, value: int):
        setattr(self, "__last_prompt_tokens", value)

    @property
    def _last_output_tokens(self) -> int:
        return getattr(self, "__last_output_tokens", 0)

    @_last_output_tokens.setter
    def _last_output_tokens(self, value: int):
        setattr(self, "__last_output_tokens", value)


def _format_rows(rows: list[tuple]) -> str:
    if not rows:
        return "[]"
    return json.dumps([list(r) for r in rows])[:500]


def _format_memory_context(
    memories: list[dict[str, Any]],
    fallback_items: list[str],
) -> str:
    lines: list[str] = []
    for item in memories[:3]:
        scope = _format_memory_scope(item)
        lines.append(
            f"- [TRAP] {item['failure_mode']} on {scope}. correction: {item['correction']}"
        )

    remaining = max(0, 3 - len(lines))
    lines.extend(f"- [TRAP] note. correction: {item}" for item in fallback_items[:remaining])

    if not lines:
        return ""
    return "Previous failures to avoid:\n" + "\n".join(lines)


def _format_memory_scope(memory: dict[str, Any]) -> str:
    table_name = memory.get("table_name")
    column_name = memory.get("column_name")
    domain = memory.get("domain", "domain")
    if table_name and column_name:
        return f"{domain}.{table_name}.{column_name}"
    if table_name:
        return f"{domain}.{table_name}"
    return domain


def _infer_memory_filters(
    runner: DuckDBRunner,
    question: str,
) -> tuple[list[str], list[str]]:
    tokens = _normalize_tokens(question)
    matched_tables: list[str] = []
    matched_columns: list[str] = []

    for table_name in runner.list_tables():
        table_tokens = _normalize_tokens(table_name)
        if tokens & table_tokens:
            matched_tables.append(table_name)

        for column in runner.describe_table(table_name):
            column_name = str(column[0])
            if tokens & _normalize_tokens(column_name):
                matched_columns.append(column_name)
                if table_name not in matched_tables:
                    matched_tables.append(table_name)

    return matched_tables[:5], matched_columns[:10]


def _normalize_tokens(text: str) -> set[str]:
    raw_tokens = {token.lower() for token in text.replace("_", " ").split()}
    normalized: set[str] = set()
    for token in raw_tokens:
        cleaned = "".join(ch for ch in token if ch.isalnum())
        if not cleaned:
            continue
        normalized.add(cleaned)
        if cleaned.endswith("s") and len(cleaned) > 3:
            normalized.add(cleaned[:-1])
    return normalized


def _extend_unique(target: list[str], values: list[str]) -> None:
    seen = set(target)
    for value in values:
        if value not in seen:
            target.append(value)
            seen.add(value)


def _extract_json(text: str) -> dict[str, Any]:
    """Extract JSON object from text that may have trailing content or markdown fences.

    Handles:
    - {'key': 'value'} followed by extra text
    - ```json ... ``` blocks
    - Trailing newlines and whitespace
    """
    text = text.strip()

    # Try stripping markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove opening fence
        if lines[0].startswith("```"):
            lines = lines[1:]
        # Remove closing fence
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from first { to matching }
    start = text.find("{")
    if start == -1:
        raise json.JSONDecodeError("No JSON object found", text, 0)

    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])

    raise json.JSONDecodeError("Unclosed JSON object", text, start)
