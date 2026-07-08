"""Tests for corrective-memory distillation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from adh.db.duckdb_runner import DuckDBRunner
from adh.memory.distiller import clear_task_questions, distill_from_failure, register_task_question
from adh.memory.store import CorrectiveMemory

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def memory_store(tmp_path: Path) -> CorrectiveMemory:
    db_path = tmp_path / "distiller.db"
    runner = DuckDBRunner(db_path)
    memory = CorrectiveMemory(runner)
    yield memory
    clear_task_questions()
    runner.close()


def test_distill_missing_column_creates_corrective_memory(memory_store: CorrectiveMemory) -> None:
    register_task_question(
        "sales_006",
        "What is the gross revenue in euros from completed orders by Spanish customers in the midmarket segment?",
    )
    feedback = {
        "error_type": "missing_column",
        "message": 'Referenced column "total_amount" not found in FROM clause',
        "available_columns": ["order_id", "customer_id", "total_cents", "status"],
        "suggested_columns": ["total_cents"],
    }

    memory_ids = distill_from_failure(
        domain="sales_analytics",
        task_id="sales_006",
        feedback=feedback,
        attempted_sql="SELECT total_amount FROM orders",
        memory=memory_store,
    )

    assert len(memory_ids) == 1
    memories = memory_store.retrieve(
        domain="sales_analytics",
        tables=["orders"],
        columns=["total_amount"],
        failure_modes=["missing_column"],
        limit=5,
    )
    assert len(memories) == 1
    assert memories[0]["column_name"] == "total_amount"
    assert "total_cents" in memories[0]["correction"]
    assert "spanish" in memories[0]["trigger_pattern"]


def test_distill_empty_result_creates_column_specific_memories(
    memory_store: CorrectiveMemory,
) -> None:
    register_task_question(
        "sales_001",
        "What was the total net revenue in euros from completed orders by Dutch customers in Q1 2026?",
    )
    feedback = {
        "error_type": "empty_result",
        "message": "Query returned zero rows",
        "diagnostics": {
            "orders.status_samples": ["completed", "pending"],
            "orders.order_date_range": ["2026-01-01", "2026-06-30"],
        },
    }

    memory_ids = distill_from_failure(
        domain="sales_analytics",
        task_id="sales_001",
        feedback=feedback,
        attempted_sql=("SELECT * FROM orders WHERE status = 'done' AND order_date >= '2027-01-01'"),
        memory=memory_store,
    )

    assert len(memory_ids) == 2
    memories = memory_store.retrieve(
        domain="sales_analytics",
        tables=["orders"],
        columns=["status", "order_date"],
        failure_modes=["empty_result"],
        limit=10,
    )
    by_column = {memory["column_name"]: memory for memory in memories}
    assert "completed" in by_column["status"]["correction"]
    assert "2026-01-01 to 2026-06-30" in by_column["order_date"]["correction"]


def test_distill_skips_blocked_sql_and_reinforces_duplicates(
    memory_store: CorrectiveMemory,
) -> None:
    register_task_question(
        "support_001",
        "How many P0 tickets were created by enterprise accounts?",
    )
    blocked_feedback = {
        "error_type": "blocked_sql",
        "message": "Only SELECT statements are allowed",
    }
    assert (
        distill_from_failure(
            domain="support_tickets",
            task_id="support_001",
            feedback=blocked_feedback,
            attempted_sql="DELETE FROM tickets",
            memory=memory_store,
        )
        == []
    )

    feedback = {
        "error_type": "missing_column",
        "message": 'Referenced column "customer_id" not found',
        "available_columns": ["ticket_id", "account_id", "priority"],
        "suggested_columns": ["account_id"],
    }

    first_ids = distill_from_failure(
        domain="support_tickets",
        task_id="support_001",
        feedback=feedback,
        attempted_sql="SELECT customer_id FROM tickets",
        memory=memory_store,
    )
    second_ids = distill_from_failure(
        domain="support_tickets",
        task_id="support_001",
        feedback=feedback,
        attempted_sql="SELECT customer_id FROM tickets",
        memory=memory_store,
    )

    assert first_ids == second_ids
    memories = memory_store.retrieve(
        domain="support_tickets",
        tables=["tickets"],
        columns=["customer_id"],
        failure_modes=["missing_column"],
        limit=5,
    )
    assert memories[0]["evidence_count"] == 2
    assert memories[0]["success_count"] == 0
    assert memories[0]["confidence"] == pytest.approx(0.6)
