"""SQL query fingerprinting — raw and normalized hashes."""

from __future__ import annotations

import hashlib

import sqlglot


def raw_fingerprint(sql: str) -> str:
    """Level 1: SHA-256 of the raw SQL string.

    Useful for exact duplicate detection.
    """
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16]


def normalized_fingerprint(sql: str) -> str:
    """Level 2: parse + normalize SQL with sqlglot, then hash.

    Handles:
    - Whitespace differences
    - Identifier casing
    - Formatting variations
    """
    try:
        normalized = _normalize_sql(sql)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    except Exception:
        # If sqlglot can't parse, fall back to raw hash
        return raw_fingerprint(sql)


def _normalize_sql(sql: str) -> str:
    """Parse and format SQL to a canonical form using sqlglot."""
    parsed = sqlglot.parse_one(sql)
    if parsed is None:
        return sql.strip().lower()

    # Transform to canonical form:
    # - Lowercase all identifiers and keywords
    # - Consistent whitespace
    normalized = parsed.sql(
        dialect="duckdb",
        pretty=False,
        normalize_functions="upper",
    )
    return normalized


def compute_fingerprints(sql: str) -> dict[str, str]:
    """Return both Level 1 and Level 2 fingerprints."""
    return {
        "raw": raw_fingerprint(sql),
        "normalized": normalized_fingerprint(sql),
    }
