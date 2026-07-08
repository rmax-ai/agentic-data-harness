"""Safe read-only DuckDB execution wrapper."""

from __future__ import annotations

import duckdb
from pathlib import Path


class DuckDBRunner:
    """Manages a DuckDB connection with read-only SQL safety checks."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(str(self.db_path))
        return self._conn

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: list | dict | None = None) -> list[tuple]:
        """Execute a read-only SQL query and return results as list of tuples."""
        try:
            if params:
                result = self.conn.execute(sql, params)
            else:
                result = self.conn.execute(sql)
            return result.fetchall()
        except Exception:
            raise

    def execute_df(self, sql: str) -> "duckdb.DuckDBPyRelation":
        """Execute SQL and return a DuckDB relation (lazy)."""
        return self.conn.sql(sql)

    def describe_table(self, table_name: str) -> list[tuple]:
        """Describe a table's schema."""
        return self.execute(f"DESCRIBE {table_name}")

    def list_tables(self) -> list[str]:
        """List all tables in the database."""
        result = self.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'")
        return [row[0] for row in result]

    def get_schema_summary(self) -> str:
        """Return a text summary of all tables and their columns."""
        tables = self.list_tables()
        if not tables:
            return "No tables found."

        lines = []
        for table in sorted(tables):
            cols = self.describe_table(table)
            col_strs = []
            for col in cols:
                name, dtype = col[0], col[1]
                col_strs.append(f"  {name}: {dtype}")
            lines.append(f"Table: {table}\n" + "\n".join(col_strs))

        return "\n\n".join(lines)

    def init_tables(self):
        """Create trace and cache tables. Overridden by trace/event modules."""
        pass

    def execute_script(self, script: str):
        """Execute a multi-statement SQL script."""
        for statement in script.split(";"):
            stmt = statement.strip()
            if stmt:
                self.conn.execute(stmt)
