"""Why-not feedback generator — structured diagnostics for failed queries."""

from __future__ import annotations

from typing import Any

from adh.db.duckdb_runner import DuckDBRunner
from adh.db.schema_introspect import get_table_columns, get_sample_values, get_date_range


def build_why_not_feedback(
    error_type: str,
    error_msg: str,
    runner: DuckDBRunner,
    attempted_sql: str,
) -> dict[str, Any]:
    """Build structured feedback for the agent after a failed or empty query.

    Returns a dict with error_type, message, available_columns, diagnostics, and hint.
    """
    feedback: dict[str, Any] = {
        "error_type": error_type,
        "message": error_msg,
    }

    # Extract table name from the SQL if possible
    table = _extract_first_table(attempted_sql)

    if error_type == "missing_column":
        feedback.update(_missing_column_feedback(runner, table, error_msg))
    elif error_type == "missing_table":
        feedback.update(_missing_table_feedback(runner))
    elif error_type == "empty_result":
        feedback.update(_empty_result_feedback(runner, table, attempted_sql))
    elif error_type == "type_mismatch":
        feedback.update(_type_mismatch_feedback(runner, table))
    elif error_type == "ambiguous_column":
        feedback.update(_ambiguous_column_feedback(runner, table))
    else:
        feedback["hint"] = "Check your SQL syntax and column references against the schema."

    return feedback


def _extract_first_table(sql: str) -> str | None:
    """Extract the first FROM/JOIN table from a SQL query."""
    import re
    match = re.search(
        r"(?:FROM|JOIN)\s+(\w+)",
        sql,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def _extract_filter_columns(sql: str) -> list[str]:
    """Extract column names used in WHERE clauses."""
    import re
    # Find columns after WHERE / AND
    matches = re.findall(r"WHERE|AND\s+(\w+)\.(\w+)", sql, re.IGNORECASE)
    # Also handle bare column references: WHERE column_name =
    bare_matches = re.findall(r"WHERE\s+(\w+)\s*=", sql, re.IGNORECASE)
    columns = [f"{t}.{c}" for t, c in matches] + bare_matches
    return list(set(columns))


def _missing_column_feedback(
    runner: DuckDBRunner,
    table: str | None,
    error_msg: str,
) -> dict[str, Any]:
    """Feedback for missing column errors."""
    result: dict[str, Any] = {}

    if table:
        cols = get_table_columns(runner, table)
        if cols:
            col_names = [c["name"] for c in cols]
            result["available_columns"] = col_names

            # Try to suggest the right column
            missing_col = _extract_missing_column(error_msg)
            if missing_col:
                suggestions = _find_similar_columns(missing_col, col_names)
                if suggestions:
                    result["suggested_columns"] = suggestions

    result["hint"] = "Use one of the available columns listed above. Check the schema."
    return result


def _missing_table_feedback(runner: DuckDBRunner) -> dict[str, Any]:
    """Feedback for missing table errors."""
    tables = runner.list_tables()
    return {
        "available_tables": tables,
        "hint": f"Available tables: {', '.join(tables)}",
    }


def _empty_result_feedback(
    runner: DuckDBRunner,
    table: str | None,
    sql: str,
) -> dict[str, Any]:
    """Feedback for queries that return zero rows."""
    result: dict[str, Any] = {
        "hint": "The query returned zero rows. Check your filter conditions.",
    }

    if table:
        # Show sample values from the filtered columns
        filter_cols = _extract_filter_columns(sql)
        diagnostics: dict[str, Any] = {}

        # Show sample values for each filtered column
        for col_ref in filter_cols:
            parts = col_ref.split(".", 1)
            col = parts[-1]
            samples = get_sample_values(runner, table, col, limit=5)
            if samples:
                diagnostics[f"{table}.{col}_samples"] = samples

        # Show date ranges if relevant
        for col_ref in filter_cols:
            parts = col_ref.split(".", 1)
            col = parts[-1]
            date_range = get_date_range(runner, table, col)
            if date_range:
                diagnostics[f"{table}.{col}_range"] = [date_range[0], date_range[1]]

        if diagnostics:
            result["diagnostics"] = diagnostics

    return result


def _type_mismatch_feedback(
    runner: DuckDBRunner,
    table: str | None,
) -> dict[str, Any]:
    """Feedback for type mismatch errors."""
    result: dict[str, Any] = {
        "hint": "Type mismatch. Check that the column type matches the operation.",
    }

    if table:
        cols = get_table_columns(runner, table)
        if cols:
            result["column_types"] = {c["name"]: c["type"] for c in cols}

    return result


def _ambiguous_column_feedback(
    runner: DuckDBRunner,
    table: str | None,
) -> dict[str, Any]:
    """Feedback for ambiguous column references."""
    result: dict[str, Any] = {
        "hint": "Use fully qualified column names (table.column) when joining tables with overlapping column names.",
    }

    if table:
        cols = get_table_columns(runner, table)
        if cols:
            result["columns_in_table"] = [f"{table}.{c['name']}" for c in cols]

    return result


def _extract_missing_column(error_msg: str) -> str | None:
    """Extract the name of the missing column from the error message."""
    import re
    # DuckDB: "Referenced column \"total_amount\" not found"
    match = re.search(r'"([^"]+)"', error_msg)
    if match:
        return match.group(1)

    # DuckDB: "Column total_amount not found in any table"
    match = re.search(r"Column (\w+) not found", error_msg, re.IGNORECASE)
    if match:
        return match.group(1)

    return None


def _find_similar_columns(missing: str, available: list[str]) -> list[str]:
    """Find similar column names using simple edit distance heuristic."""
    suggestions = []
    missing_lower = missing.lower()

    for col in available:
        col_lower = col.lower()
        # Check common prefix/suffix
        if col_lower.startswith(missing_lower[:4]) or missing_lower.startswith(col_lower[:4]):
            suggestions.append(col)
        # Check substring overlap
        elif len(set(missing_lower) & set(col_lower)) >= min(len(missing_lower), len(col_lower)) // 2:
            suggestions.append(col)

    return suggestions[:3]  # Top 3 suggestions
