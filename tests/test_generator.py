"""Tests for dataset generator idempotency and benchmark metadata."""

from pathlib import Path

import pytest

from adh.datasets.generator import BENCHMARK_DATE, DataGenerator, DatasetAlreadyExistsError


def test_generate_all_errors_when_tables_exist_without_reset(tmp_path: Path):
    """Second run without reset should raise DatasetAlreadyExistsError."""
    db_path = tmp_path / "test.db"
    gen = DataGenerator(db_path=db_path, seed=42)

    # First run succeeds
    gen.generate_all()
    assert db_path.exists()

    # Second run without reset should error
    gen2 = DataGenerator(db_path=db_path, seed=42)
    with pytest.raises(DatasetAlreadyExistsError, match="Re-run with reset"):
        gen2.generate_all(reset=False)


def test_generate_all_reset_succeeds_repeatedly(tmp_path: Path):
    """Run with reset flag succeeds every time."""
    db_path = tmp_path / "test.db"

    for _ in range(3):
        gen = DataGenerator(db_path=db_path, seed=42)
        gen.generate_all(reset=True)
        assert db_path.exists()


def test_generate_all_reset_drops_only_target_domain(tmp_path: Path):
    """Resetting one domain should not drop tables from other domains."""
    db_path = tmp_path / "test.db"
    gen = DataGenerator(db_path=db_path, seed=42)

    # Generate all domains first
    gen.generate_all()

    import duckdb

    conn = duckdb.connect(str(db_path))
    tables_before = {
        row[0]
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert "customers" in tables_before
    assert "accounts" in tables_before

    # Reset only sales_analytics
    gen2 = DataGenerator(db_path=db_path, seed=42)
    gen2.generate_all(domains=["sales_analytics"], reset=True)

    tables_after = {
        row[0]
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    # support_tickets domain tables should survive
    assert "accounts" in tables_after, "Non-target domain tables should not be dropped"
    assert "tickets" in tables_after, "Non-target domain tables should not be dropped"
    conn.close()


def test_generate_all_writes_benchmark_metadata(tmp_path: Path):
    """Generated DB has benchmark_metadata table with date and seed."""
    db_path = tmp_path / "test.db"
    gen = DataGenerator(db_path=db_path, seed=42)
    gen.generate_all()

    from adh.db.duckdb_runner import DuckDBRunner

    runner = DuckDBRunner(db_path)
    meta = runner.get_benchmark_metadata()
    assert meta["benchmark_date"] == BENCHMARK_DATE.isoformat()
    assert meta["seed"] == "42"
