"""DuckDB schema introspection helpers."""

from __future__ import annotations

from adh.db.duckdb_runner import DuckDBRunner


def get_table_columns(runner: DuckDBRunner, table: str) -> list[dict]:
    """Return list of {name, type} for a table."""
    try:
        rows = runner.describe_table(table)
        return [{"name": row[0], "type": row[1]} for row in rows]
    except Exception:
        return []


def get_sample_values(
    runner: DuckDBRunner, table: str, column: str, limit: int = 10
) -> list[str]:
    """Return sample distinct values for a column."""
    try:
        rows = runner.execute(
            f"SELECT DISTINCT {column} FROM {table} LIMIT {limit}"
        )
        return [str(row[0]) for row in rows]
    except Exception:
        return []


def get_date_range(
    runner: DuckDBRunner, table: str, column: str
) -> tuple[str, str] | None:
    """Return (min, max) date values for a column."""
    try:
        rows = runner.execute(
            f"SELECT MIN({column}), MAX({column}) FROM {table}"
        )
        return (str(rows[0][0]), str(rows[0][1]))
    except Exception:
        return None
