"""SQL gateway with validation, execution, and (future) caching."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from adh.db.duckdb_runner import DuckDBRunner
from adh.db.sql_safety import validate_sql


@dataclass
class SQLResult:
    """Result of SQL execution through the gateway."""

    success: bool
    rows: list[tuple] = field(default_factory=list)
    row_count: int = 0
    error_type: str | None = None
    error_message: str | None = None
    fingerprint: str | None = None
    cache_status: str | None = None
    latency_ms: int = 0
    # Feedback for the agent
    feedback: dict[str, Any] | None = None


class SQLGateway:
    """Validates, fingerprints (future), and executes SQL queries.

    Phase 2 (MVP): validation + execution only.
    Phase 3: adds fingerprinting and caching.
    Phase 4: adds failure classification and why-not feedback.
    """

    def __init__(
        self,
        runner: DuckDBRunner,
        cache_enabled: bool = False,
    ):
        self._runner = runner
        self.cache_enabled = cache_enabled

    def execute(self, sql: str) -> SQLResult:
        """Validate and execute a SQL query. Return structured result."""
        t0 = time.monotonic()

        # 1. Validate read-only
        is_valid, error = validate_sql(sql)
        if not is_valid:
            return SQLResult(
                success=False,
                error_type="blocked_sql",
                error_message=error,
                latency_ms=_elapsed(t0),
                feedback={"error_type": "blocked_sql", "message": error} if error else None,
            )

        # 2. Execute (caching will be Phase 3)
        try:
            rows = self._runner.execute(sql)
            latency = _elapsed(t0)
            return SQLResult(
                success=True,
                rows=rows,
                row_count=len(rows),
                cache_status="executed",
                latency_ms=latency,
            )
        except Exception as e:
            latency = _elapsed(t0)
            error_msg = str(e)
            error_type = _classify_error(error_msg)
            return SQLResult(
                success=False,
                error_type=error_type,
                error_message=error_msg,
                cache_status="executed",
                latency_ms=latency,
                feedback=_build_feedback(error_type, error_msg, self._runner, sql),
            )

    def get_schema_summary(self) -> str:
        return self._runner.get_schema_summary()


def _elapsed(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _classify_error(error_msg: str) -> str:
    """Deterministic error classification from DuckDB error messages."""
    msg_lower = error_msg.lower()

    if "referenced column" in msg_lower or "not found in from clause" in msg_lower:
        return "missing_column"
    if "table with name" in msg_lower and "does not exist" in msg_lower:
        return "missing_table"
    if "parser error" in msg_lower:
        return "syntax_error"
    if "ambiguous reference" in msg_lower or "ambiguous" in msg_lower:
        return "ambiguous_column"
    if "type" in msg_lower and ("mismatch" in msg_lower or "cannot be cast" in msg_lower):
        return "type_mismatch"
    if "timeout" in msg_lower:
        return "timeout"
    return "unknown"


def _build_feedback(
    error_type: str,
    error_msg: str,
    runner: DuckDBRunner,
    sql: str,
) -> dict[str, Any]:
    """Build structured feedback for the agent."""
    feedback: dict[str, Any] = {
        "error_type": error_type,
        "message": error_msg,
    }

    if error_type == "missing_column":
        # Try to extract table name from the SQL and list available columns
        feedback["hint"] = "Check the schema for available columns."

    elif error_type == "empty_result":
        feedback["hint"] = "The query returned zero rows. Check your filter conditions."

    return feedback
