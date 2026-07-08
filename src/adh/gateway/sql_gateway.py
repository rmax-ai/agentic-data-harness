"""SQL gateway with validation, fingerprinting, caching, and execution."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from adh.db.sql_safety import validate_sql
from adh.gateway.cache import QueryCache
from adh.gateway.fingerprint import compute_fingerprints
from adh.gateway.why_not import build_why_not_feedback

if TYPE_CHECKING:
    from adh.db.duckdb_runner import DuckDBRunner


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
    """Validates, fingerprints, caches, and executes SQL queries.

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
        self._cache = QueryCache(runner) if cache_enabled else None

    def execute(self, sql: str) -> SQLResult:
        """Validate, fingerprint, check cache, and execute a SQL query."""
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

        # 2. Compute fingerprints
        fps = compute_fingerprints(sql)
        fp = fps["normalized"]

        # 3. Check cache
        if self._cache is not None:
            cached = self._cache.get(fp)
            if cached is not None:
                latency = _elapsed(t0)
                result = self._cached_to_result(cached, fp, latency)
                return result

        # 4. Execute
        try:
            rows = self._runner.execute(sql)
            latency = _elapsed(t0)

            # Cache successful result
            if self._cache is not None:
                self._cache.put(
                    fingerprint=fp,
                    normalized_sql=sql,
                    result_rows=rows,
                    row_count=len(rows),
                    latency_ms=latency,
                )

            return SQLResult(
                success=True,
                rows=rows,
                row_count=len(rows),
                fingerprint=fp,
                cache_status="miss" if self._cache is not None else "executed",
                latency_ms=latency,
                feedback=_empty_feedback_if_needed(rows, sql, self._runner),
            )
        except Exception as e:
            latency = _elapsed(t0)
            error_msg = str(e)
            error_type = _classify_error(error_msg)

            # Cache error result for deterministic errors
            if self._cache is not None and error_type not in ("unknown", "timeout"):
                self._cache.put(
                    fingerprint=fp,
                    normalized_sql=sql,
                    error_msg=error_msg,
                    error_type=error_type,
                    latency_ms=latency,
                )

            return SQLResult(
                success=False,
                error_type=error_type,
                error_message=error_msg,
                fingerprint=fp,
                cache_status="miss" if self._cache is not None else "executed",
                latency_ms=latency,
                feedback=build_why_not_feedback(error_type, error_msg, self._runner, sql),
            )

    def _cached_to_result(
        self, cached: dict[str, Any], fingerprint: str, latency_ms: int
    ) -> SQLResult:
        """Convert a cached entry back to an SQLResult."""
        if cached["result_json"] is not None:
            rows_raw = json.loads(cached["result_json"])
            rows = [tuple(r) for r in rows_raw]
            return SQLResult(
                success=True,
                rows=rows,
                row_count=cached["row_count"],
                fingerprint=fingerprint,
                cache_status="hit",
                latency_ms=latency_ms,
            )
        elif cached["error_json"] is not None:
            error_data = json.loads(cached["error_json"])
            return SQLResult(
                success=False,
                error_type=error_data.get("error_type", "unknown"),
                error_message=error_data.get("error_message", ""),
                fingerprint=fingerprint,
                cache_status="hit",
                latency_ms=latency_ms,
            )
        return SQLResult(
            success=False,
            error_type="unknown",
            error_message="Corrupt cache entry",
            fingerprint=fingerprint,
            cache_status="error",
            latency_ms=latency_ms,
        )

    def cache_stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        if self._cache is None:
            return {"enabled": False}
        return self._cache.stats()

    def clear_cache(self):
        """Clear the query cache."""
        if self._cache is not None:
            self._cache.clear()

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


def _empty_feedback_if_needed(
    rows: list[tuple],
    sql: str,
    runner: DuckDBRunner,
) -> dict[str, Any] | None:
    """Generate why-not feedback if query returns zero rows."""
    if len(rows) > 0:
        return None
    return build_why_not_feedback("empty_result", "Query returned zero rows", runner, sql)
