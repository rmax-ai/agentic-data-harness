"""Corrective memory store, retrieval, and distillation.

Phase 5: persistent memory of schema traps and corrections learned from failures.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from adh.db.duckdb_runner import DuckDBRunner

MEMORY_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS corrective_memory (
    memory_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    table_name TEXT,
    column_name TEXT,
    failure_mode TEXT NOT NULL,
    trigger_pattern TEXT NOT NULL,
    correction TEXT NOT NULL,
    evidence_count INTEGER DEFAULT 1,
    success_count INTEGER DEFAULT 0,
    confidence DOUBLE DEFAULT 0.5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_on_schema_hash TEXT
)
"""


class CorrectiveMemory:
    """Stores and retrieves corrective memories for the agent."""

    def __init__(self, runner: DuckDBRunner):
        self._runner = runner
        self._init_table()

    def _init_table(self):
        self._runner.execute_script(MEMORY_TABLE_DDL)

    def store(
        self,
        domain: str,
        failure_mode: str,
        correction: str,
        table_name: str | None = None,
        column_name: str | None = None,
        trigger_pattern: str = "",
        schema_hash: str = "",
    ) -> str:
        """Store a corrective memory. Returns memory_id."""
        memory_id = uuid.uuid4().hex[:12]

        # Check if a similar memory already exists
        existing = self._find_similar(domain, failure_mode, table_name, column_name)
        if existing:
            # Update existing and reinforce confidence without counting a success yet.
            self._runner.execute(
                """UPDATE corrective_memory
                SET evidence_count = evidence_count + 1,
                    confidence = LEAST(1.0, confidence + 0.1),
                    updated_at = ?
                WHERE memory_id = ?""",
                [datetime.now(UTC).isoformat(), existing],
            )
            return existing

        self._runner.execute(
            """INSERT INTO corrective_memory
            (memory_id, domain, table_name, column_name, failure_mode,
             trigger_pattern, correction, evidence_count, success_count, confidence,
             created_at, updated_at, expires_on_schema_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0, 0.5, ?, ?, ?)""",
            [
                memory_id,
                domain,
                table_name,
                column_name,
                failure_mode,
                trigger_pattern,
                correction,
                datetime.now(UTC).isoformat(),
                datetime.now(UTC).isoformat(),
                schema_hash if schema_hash else "",
            ],
        )
        return memory_id

    def retrieve(
        self,
        domain: str,
        tables: list[str] | None = None,
        columns: list[str] | None = None,
        failure_modes: list[str] | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant corrective memories.

        Matches by: domain, table name, column name, failure mode.
        Orders by confidence descending.
        """
        conditions = ["domain = ?"]
        params: list[Any] = [domain]

        if tables:
            placeholders = ",".join(["?" for _ in tables])
            conditions.append(f"(table_name IN ({placeholders}) OR table_name IS NULL)")
            params.extend(tables)

        if columns:
            placeholders = ",".join(["?" for _ in columns])
            conditions.append(f"(column_name IN ({placeholders}) OR column_name IS NULL)")
            params.extend(columns)

        if failure_modes:
            placeholders = ",".join(["?" for _ in failure_modes])
            conditions.append(f"failure_mode IN ({placeholders})")
            params.extend(failure_modes)

        where = " AND ".join(f"({c})" for c in conditions)
        sql = f"""SELECT memory_id, domain, table_name, column_name, failure_mode,
                         trigger_pattern, correction, evidence_count, success_count,
                         confidence
                  FROM corrective_memory
                  WHERE {where}
                  ORDER BY confidence DESC, success_count DESC, evidence_count DESC
                  LIMIT ?"""
        params.append(limit)

        try:
            rows = self._runner.execute(sql, params)
        except Exception:
            return []

        return [
            {
                "memory_id": r[0],
                "domain": r[1],
                "table_name": r[2],
                "column_name": r[3],
                "failure_mode": r[4],
                "trigger_pattern": r[5],
                "correction": r[6],
                "evidence_count": r[7],
                "success_count": r[8],
                "confidence": r[9],
            }
            for r in rows
        ]

    def mark_success(self, memory_id: str):
        """Mark a memory as having contributed to a successful query."""
        self._runner.execute(
            """UPDATE corrective_memory
            SET success_count = success_count + 1,
                confidence = LEAST(1.0, confidence + 0.05),
                updated_at = ?
            WHERE memory_id = ?""",
            [datetime.now(UTC).isoformat(), memory_id],
        )

    def _find_similar(
        self,
        domain: str,
        failure_mode: str,
        table_name: str | None,
        column_name: str | None,
    ) -> str | None:
        """Find an existing memory with similar characteristics."""
        rows = self._runner.execute(
            """SELECT memory_id FROM corrective_memory
            WHERE domain = ? AND failure_mode = ?
              AND (table_name = ? OR (table_name IS NULL AND ? IS NULL))
              AND (column_name = ? OR (column_name IS NULL AND ? IS NULL))
            LIMIT 1""",
            [domain, failure_mode, table_name, table_name, column_name, column_name],
        )
        if rows:
            return rows[0][0]
        return None

    def stats(self) -> dict[str, Any]:
        """Return memory statistics."""
        rows = self._runner.execute(
            "SELECT COUNT(*), AVG(confidence), SUM(success_count) FROM corrective_memory"
        )
        total = rows[0][0] if rows else 0
        avg_conf = rows[0][1] if rows and rows[0][1] else 0
        successes = rows[0][2] if rows and rows[0][2] else 0
        return {
            "total_memories": total,
            "avg_confidence": float(avg_conf),
            "total_successes": successes,
        }

    def clear(self):
        """Clear all corrective memories."""
        self._runner.execute("DELETE FROM corrective_memory")
