"""Tests for benchmark runner repeat handling and per-task aggregation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import yaml

from adh.evals.runner import BenchmarkRunner

if TYPE_CHECKING:
    from pathlib import Path


class FakeAgent:
    def __init__(self):
        self.model_config = SimpleNamespace(model="test-model")
        self._trace = None
        self._calls: dict[str, int] = {}

    def solve(
        self,
        task_id: str,
        question: str,
        run_id: str,
        mode: str = "raw",
        domain: str | None = None,
    ) -> dict[str, Any]:
        del question, run_id, mode, domain
        repeat_index = self._calls.get(task_id, 0) + 1
        self._calls[task_id] = repeat_index

        return {
            "task_id": task_id,
            "success": True,
            "answer": {"value": 1},
            "steps": repeat_index,
            "query_history": [
                {
                    "sql": f"SELECT {repeat_index}",
                    "cache_status": "miss" if repeat_index == 1 else "hit",
                }
            ],
            "retrieved_memory_ids": [] if repeat_index == 1 else [f"mem-{task_id}-{repeat_index}"],
            "created_memory_ids": [],
        }


class FakeGateway:
    def __init__(self):
        self.clear_calls = 0

    def clear_cache(self):
        self.clear_calls += 1

    def cache_stats(self) -> dict[str, Any]:
        return {"enabled": True, "total_entries": 2, "total_hits": 4, "hit_rate": 2 / 3}


class FakeMemoryStore:
    def __init__(self):
        self.cleared = 0
        self.marked_success: list[str] = []

    def clear(self):
        self.cleared += 1

    def stats(self) -> dict[str, Any]:
        return {"total_memories": 2, "avg_confidence": 0.8, "total_successes": 4}

    def mark_success(self, memory_id: str):
        self.marked_success.append(memory_id)


class FakeRunner:
    pass


def test_benchmark_runner_repeats_tasks_and_aggregates_per_task_stats(tmp_path: Path) -> None:
    tasks_path = tmp_path / "tasks.yaml"
    tasks_path.write_text(
        yaml.safe_dump(
            {
                "tasks": [
                    {
                        "id": "task_1",
                        "domain": "domain_a",
                        "question": "First question",
                        "expected_answer": {"type": "numeric", "value": 1, "tolerance": 1.0},
                    },
                    {
                        "id": "task_2",
                        "domain": "domain_b",
                        "question": "Second question",
                        "expected_answer": {"type": "numeric", "value": 1, "tolerance": 2.0},
                    },
                ]
            }
        )
    )

    agent = FakeAgent()
    gateway = FakeGateway()
    memory_store = FakeMemoryStore()
    benchmark = BenchmarkRunner(
        agent=agent,
        db_runner=FakeRunner(),
        gateway=gateway,
        mode="cached_memory",
        output_dir=str(tmp_path / "reports"),
        memory_store=memory_store,
        repeat=3,
        cache_db_path="data/cache.db",
    )

    summary = benchmark.run(str(tasks_path))

    assert gateway.clear_calls == 1
    assert memory_store.cleared == 1
    assert summary["repeat_count"] == 3
    assert summary["unique_task_count"] == 2
    assert summary["total_tasks"] == 6
    assert len(summary["results"]) == 6
    assert summary["cache_db_path"] == "data/cache.db"

    task_1_stats = summary["per_task_stats"]["task_1"]
    task_2_stats = summary["per_task_stats"]["task_2"]
    assert task_1_stats["repeats"] == 3
    assert task_1_stats["cache_hits"] == 2
    assert task_1_stats["cache_misses"] == 1
    assert task_1_stats["cache_hit_rate"] == 2 / 3
    assert task_1_stats["memory_hits"] == 2
    assert task_1_stats["memory_retrievals"] == 3
    assert task_1_stats["memory_hit_rate"] == 2 / 3
    assert task_2_stats["cache_hit_rate"] == 2 / 3

    repeat_indices = [
        result["repeat_index"] for result in summary["results"] if result["task_id"] == "task_1"
    ]
    assert repeat_indices == [1, 2, 3]
    assert sorted(memory_store.marked_success) == [
        "mem-task_1-2",
        "mem-task_1-3",
        "mem-task_2-2",
        "mem-task_2-3",
    ]
