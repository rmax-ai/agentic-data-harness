"""Trace event schemas and storage."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from adh.db.duckdb_runner import DuckDBRunner


class EventType(StrEnum):
    MODEL_CALL = "model_call"
    SQL_EXECUTION = "sql_execution"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"
    FAILURE_CLASSIFIED = "failure_classified"
    MEMORY_RETRIEVED = "memory_retrieved"
    MEMORY_WRITTEN = "memory_written"
    FINAL_ANSWER = "final_answer"
    TASK_FAILED = "task_failed"
    TASK_COMPLETE = "task_complete"


class TraceEvent(BaseModel):
    run_id: str
    task_id: str
    mode: str
    step: int
    event_type: EventType
    model: str = "gpt-5.4-mini"
    prompt_tokens: int = 0
    output_tokens: int = 0
    sql: str | None = None
    sql_fingerprint: str | None = None
    cache_status: str | None = None
    success: bool = True
    error_type: str | None = None
    error_message: str | None = None
    result_row_count: int = 0
    latency_ms: int = 0
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    extra: dict[str, Any] = Field(default_factory=dict)


class TraceStore:
    """Writes trace events to JSONL and optionally to DuckDB."""

    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._events: list[TraceEvent] = []

    def record(self, event: TraceEvent):
        self._events.append(event)

    def flush(self, run_id: str):
        """Write all events to JSONL file."""

        output_path = self.output_dir / f"traces.{run_id}.jsonl"
        with open(output_path, "w") as f:
            for event in self._events:
                f.write(event.model_dump_json() + "\n")
        return output_path

    @property
    def event_count(self) -> int:
        return len(self._events)


def init_traces(runner: DuckDBRunner):
    """Create trace-related tables in DuckDB."""
    runner.execute_script("""
    CREATE TABLE IF NOT EXISTS trace_events (
        run_id VARCHAR,
        task_id VARCHAR,
        mode VARCHAR,
        step INTEGER,
        event_type VARCHAR,
        model VARCHAR,
        prompt_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        sql VARCHAR,
        sql_fingerprint VARCHAR,
        cache_status VARCHAR,
        success BOOLEAN DEFAULT TRUE,
        error_type VARCHAR,
        error_message VARCHAR,
        result_row_count INTEGER DEFAULT 0,
        latency_ms INTEGER DEFAULT 0,
        timestamp VARCHAR,
        extra JSON,
        inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
