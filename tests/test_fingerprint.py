"""Tests for SQL fingerprinting."""

import pytest
from adh.gateway.fingerprint import (
    raw_fingerprint,
    normalized_fingerprint,
    compute_fingerprints,
)


class TestRawFingerprint:
    def test_same_sql_same_hash(self):
        sql = "SELECT * FROM users WHERE id = 1"
        assert raw_fingerprint(sql) == raw_fingerprint(sql)

    def test_different_sql_different_hash(self):
        a = "SELECT * FROM users"
        b = "SELECT * FROM orders"
        assert raw_fingerprint(a) != raw_fingerprint(b)

    def test_whitespace_changes_hash(self):
        """Raw hash is sensitive to whitespace — that's intentional."""
        a = "SELECT * FROM users"
        b = "SELECT  *  FROM  users"
        assert raw_fingerprint(a) != raw_fingerprint(b)


class TestNormalizedFingerprint:
    def test_whitespace_normalized(self):
        """Normalized hash should be insensitive to whitespace."""
        a = "SELECT * FROM users WHERE id = 1"
        b = "SELECT  *  FROM  users  WHERE  id  =  1"
        assert normalized_fingerprint(a) == normalized_fingerprint(b)

    def test_case_not_normalized_by_default(self):
        """sqlglot preserves identifier casing — this is correct SQL behavior.
        Same casing produces same hash; different casing produces different hash.
        """
        # Same casing → same fingerprint
        assert normalized_fingerprint("SELECT * FROM users") == normalized_fingerprint("SELECT * FROM users")
        # Different casing → different fingerprint (identifier names differ)
        assert normalized_fingerprint("select * from users") != normalized_fingerprint("SELECT * FROM USERS")

    def test_different_queries_different_hashes(self):
        a = "SELECT * FROM users WHERE id = 1"
        b = "SELECT * FROM users WHERE id = 2"
        assert normalized_fingerprint(a) != normalized_fingerprint(b)

    def test_formatting_normalized(self):
        """Different formatting of the same logical query should match."""
        a = "SELECT a, b FROM t WHERE x = 1"
        b = "SELECT a,\n       b\nFROM t\nWHERE x = 1"
        assert normalized_fingerprint(a) == normalized_fingerprint(b)

    def test_unparseable_sql_falls_back_to_raw(self):
        """When sqlglot can't parse, fall back to raw hash."""
        sql = "THIS IS NOT VALID SQL AT ALL !!!"
        fp = normalized_fingerprint(sql)
        assert fp == raw_fingerprint(sql)


class TestComputeFingerprints:
    def test_returns_both_levels(self):
        fps = compute_fingerprints("SELECT 1")
        assert "raw" in fps
        assert "normalized" in fps
        assert len(fps["raw"]) == 16
        assert len(fps["normalized"]) == 16
