"""Query result cache — DuckDB-backed with fingerprint-based lookup."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from adh.db.duckdb_runner import DuckDBRunner

CACHE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS query_cache (
    fingerprint TEXT PRIMARY KEY,
    normalized_sql TEXT NOT NULL,
    result_json TEXT,
    error_json TEXT,
    row_count INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    hit_count INTEGER DEFAULT 0
)
"""


class QueryCache:
    """Fingerprint-based query result cache."""

    def __init__(self, runner: DuckDBRunner):
        self._runner = runner
        self._init_table()

    def _init_table(self):
        self._runner.execute_script(CACHE_TABLE_DDL)

    def get(self, fingerprint: str) -> dict[str, Any] | None:
        """Look up a cached result by fingerprint.

        Returns None if not found.
        """
        rows = self._runner.execute(
            "SELECT result_json, error_json, row_count, latency_ms, hit_count "
            "FROM query_cache WHERE fingerprint = ?",
            [fingerprint],
        )
        if not rows:
            return None

        result_json, error_json, row_count, latency_ms, hit_count = rows[0]

        # Increment hit count
        self._runner.execute(
            "UPDATE query_cache SET hit_count = hit_count + 1 WHERE fingerprint = ?",
            [fingerprint],
        )

        return {
            "result_json": result_json,
            "error_json": error_json,
            "row_count": row_count,
            "latency_ms": latency_ms,
            "hit_count": hit_count + 1,
        }

    def put(
        self,
        fingerprint: str,
        normalized_sql: str,
        result_rows: list[tuple] | None = None,
        error_msg: str | None = None,
        error_type: str | None = None,
        row_count: int = 0,
        latency_ms: int = 0,
    ):
        """Store a query result in the cache."""
        result_json = None
        if result_rows is not None:
            result_json = json.dumps([list(r) for r in result_rows[:100]])

        error_json = None
        if error_msg:
            error_json = json.dumps(
                {
                    "error_type": error_type,
                    "error_message": error_msg,
                }
            )

        self._runner.execute(
            """INSERT OR REPLACE INTO query_cache
            (fingerprint, normalized_sql, result_json, error_json, row_count, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?)""",
            [fingerprint, normalized_sql, result_json, error_json, row_count, latency_ms],
        )

    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        rows = self._runner.execute(
            "SELECT COUNT(*) AS total, SUM(hit_count) AS hits FROM query_cache"
        )
        total = rows[0][0] if rows else 0
        hits = rows[0][1] if rows and rows[0][1] is not None else 0
        return {
            "total_entries": total,
            "total_hits": hits,
            "hit_rate": hits / (hits + total) if (hits + total) > 0 else 0,
        }

    def clear(self):
        """Clear the entire cache."""
        self._runner.execute("DELETE FROM query_cache")
