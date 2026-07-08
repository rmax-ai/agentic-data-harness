"""Tests for query cache."""

from pathlib import Path

import pytest

from adh.db.duckdb_runner import DuckDBRunner
from adh.gateway.cache import QueryCache


@pytest.fixture
def cache():
    db_path = Path("/tmp/test_cache.db")
    runner = DuckDBRunner(db_path)
    cache = QueryCache(runner)
    yield cache
    runner.close()
    db_path.unlink(missing_ok=True)


class TestQueryCache:
    def test_put_and_get_success(self, cache):
        cache.put(
            fingerprint="abc123",
            normalized_sql="SELECT 1",
            result_rows=[(1,)],
            row_count=1,
            latency_ms=10,
        )

        result = cache.get("abc123")
        assert result is not None
        assert result["row_count"] == 1
        assert result["result_json"] is not None

    def test_get_missing_returns_none(self, cache):
        assert cache.get("nonexistent") is None

    def test_put_and_get_error(self, cache):
        cache.put(
            fingerprint="err123",
            normalized_sql="SELECT bad_column",
            error_msg="Column not found",
            error_type="missing_column",
        )

        result = cache.get("err123")
        assert result is not None
        assert result["error_json"] is not None
        assert result["result_json"] is None

    def test_hit_count_increments(self, cache):
        cache.put(
            fingerprint="hit_test",
            normalized_sql="SELECT 1",
            result_rows=[(1,)],
            row_count=1,
        )

        cache.get("hit_test")
        cache.get("hit_test")
        result = cache.get("hit_test")
        # hit_count starts at 0, 3 gets = 3
        assert result["hit_count"] == 3

    def test_stats(self, cache):
        cache.put("a", "SELECT 1", result_rows=[(1,)], row_count=1)
        cache.put("b", "SELECT 2", result_rows=[(2,)], row_count=1)
        cache.get("a")

        stats = cache.stats()
        assert stats["total_entries"] == 2
        assert stats["total_hits"] == 1

    def test_clear(self, cache):
        cache.put("a", "SELECT 1", result_rows=[(1,)], row_count=1)
        cache.clear()
        stats = cache.stats()
        assert stats["total_entries"] == 0
