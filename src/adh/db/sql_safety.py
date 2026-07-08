"""Read-only SQL safety validation."""

from __future__ import annotations

# SQL statement prefixes that are explicitly allowed
_ALLOWED_PREFIXES = (
    "SELECT",
    "WITH",
    "DESCRIBE",
    "SHOW",
    "PRAGMA TABLE_INFO",
    "EXPLAIN",
)

# SQL statement prefixes that are explicitly blocked
_BLOCKED_PREFIXES = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "COPY",
    "EXPORT",
    "ATTACH",
    "INSTALL",
    "LOAD",
    "GRANT",
    "REVOKE",
    "TRUNCATE",
    "SET",
    "BEGIN",
    "COMMIT",
    "ROLLBACK",
    "VACUUM",
    "CHECKPOINT",
)


def validate_sql(sql: str) -> tuple[bool, str | None]:
    """Validate that SQL is read-only.

    Returns (is_valid, error_message).
    """
    stripped = sql.strip().upper()

    if not stripped:
        return False, "Empty SQL statement"

    # Check blocked prefixes first
    for prefix in _BLOCKED_PREFIXES:
        if stripped.startswith(prefix):
            # Allow DESCRIBE even though it starts with D
            if prefix.startswith("D") and stripped.startswith("DESCRIBE"):
                continue
            return False, f"Blocked SQL: {prefix} statements are not allowed"

    # Check allowed prefixes
    for prefix in _ALLOWED_PREFIXES:
        if stripped.startswith(prefix):
            return True, None

    return False, f"Unknown SQL statement type. Allowed: SELECT, WITH, DESCRIBE, SHOW, PRAGMA"
