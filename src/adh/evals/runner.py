"""Benchmark runner that executes tasks and evaluates results."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from rich.console import Console

from adh.memory.distiller import (
    clear_task_questions,
    configure_memory_store,
    register_task_question,
)
from adh.tracing.events import EventType, TraceEvent, TraceStore

if TYPE_CHECKING:
    from adh.agents.openai_sql_agent import OpenAISQLAgent
    from adh.db.duckdb_runner import DuckDBRunner
    from adh.gateway.sql_gateway import SQLGateway
    from adh.memory.store import CorrectiveMemory

console = Console()


class BenchmarkRunner:
    """Runs benchmark tasks through an agent and collects results."""

    def __init__(
        self,
        agent: OpenAISQLAgent,
        db_runner: DuckDBRunner,
        gateway: SQLGateway,
        mode: str = "raw",
        seed: int = 42,
        output_dir: str = "reports",
        memory_store: CorrectiveMemory | None = None,
        repeat: int = 1,
        cache_db_path: str | None = None,
    ):
        self.agent = agent
        self._db = db_runner
        self._gateway = gateway
        self.mode = mode
        self.seed = seed
        self.output_dir = Path(output_dir)
        self._memory_store = memory_store
        self.repeat = repeat
        self.cache_db_path = cache_db_path

    def run(self, tasks_path: str) -> dict[str, Any]:
        """Run all tasks from a YAML file and return the saved summary payload."""
        with open(tasks_path) as f:
            tasks_data = yaml.safe_load(f)

        tasks = tasks_data.get("tasks", [])
        if not tasks:
            console.print("[red]No tasks found in task file.[/]")
            return {}

        run_id = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
        run_dir = self.output_dir / f"{run_id}-{self.mode}"
        run_dir.mkdir(parents=True, exist_ok=True)

        self._gateway.clear_cache()
        if self._memory_store is not None:
            self._memory_store.clear()
        clear_task_questions()
        for task in tasks:
            register_task_question(task["id"], task["question"])
        configure_memory_store(self._memory_store)

        trace_store = TraceStore(run_dir)
        self.agent._trace = trace_store  # Inject trace store

        results = []
        success_count = 0
        total_executions = len(tasks) * self.repeat

        console.print(
            f"\n[bold]Benchmark Run[/] [{self.mode}] — "
            f"{len(tasks)} tasks x {self.repeat} repeats = {total_executions} executions"
        )
        console.print(f"Run ID: {run_id}\n")

        execution_index = 0
        for task in tasks:
            task_id = task["id"]
            question = task["question"]
            expected = task.get("expected_answer", {})
            domain = task.get("domain")

            for repeat_index in range(1, self.repeat + 1):
                execution_index += 1
                console.print(
                    f"  [{execution_index}/{total_executions}] "
                    f"{task_id} (repeat {repeat_index}/{self.repeat}): {question[:80]}..."
                )

                result = self.agent.solve(
                    task_id=task_id,
                    question=question,
                    run_id=run_id,
                    mode=self.mode,
                    domain=domain,
                )

                # Evaluate answer
                evaluation = self._evaluate_answer(result.get("answer"), expected, task)
                result["evaluation"] = evaluation
                result["domain"] = domain
                result["repeat_index"] = repeat_index
                result["repeat_count"] = self.repeat

                used_memory_ids: list[str] = []
                if evaluation.get("correct", False) and self._memory_store is not None:
                    used_memory_ids = _unique_memory_ids(
                        [
                            *result.get("retrieved_memory_ids", []),
                            *result.get("created_memory_ids", []),
                        ]
                    )
                    for memory_id in used_memory_ids:
                        self._memory_store.mark_success(memory_id)
                result["used_memory_ids"] = used_memory_ids

                if evaluation.get("correct", False):
                    success_count += 1
                    console.print(f"    [green]PASS[/] — {result.get('steps', '?')} steps")
                elif evaluation.get("correct") is None:
                    console.print(f"    [yellow]SKIP[/] — {evaluation.get('reason', 'unknown')}")
                else:
                    console.print(f"    [red]FAIL[/] — {evaluation.get('reason', 'unknown')}")

                trace_store.record(
                    TraceEvent(
                        run_id=run_id,
                        task_id=task_id,
                        mode=self.mode,
                        step=result.get("steps", 0),
                        event_type=EventType.TASK_COMPLETE,
                        model=self.agent.model_config.model,
                        success=bool(evaluation.get("correct", False)),
                        error_type=None
                        if evaluation.get("correct", False)
                        else evaluation.get("reason"),
                        extra={
                            "evaluation": evaluation,
                            "used_memory_ids": used_memory_ids,
                            "repeat_index": repeat_index,
                            "repeat_count": self.repeat,
                        },
                    )
                )
                results.append(result)

        cache_stats = self._gateway.cache_stats()
        memory_stats = (
            {"enabled": True, **self._memory_store.stats()}
            if self._memory_store is not None
            else {"enabled": False}
        )

        trace_path = trace_store.flush(f"{run_id}-{self.mode}")
        result_path = run_dir / f"{self.mode}.json"
        summary = {
            "run_id": run_id,
            "mode": self.mode,
            "seed": self.seed,
            "repeat_count": self.repeat,
            "unique_task_count": len(tasks),
            "total_tasks": len(results),
            "success_count": success_count,
            "success_rate": success_count / len(results) if results else 0,
            "result_path": str(result_path),
            "trace_path": str(trace_path),
            "cache_db_path": self.cache_db_path,
            "cache_stats": cache_stats,
            "memory_stats": memory_stats,
            "per_task_stats": _build_per_task_stats(results, self.mode),
            "results": results,
        }
        with open(result_path, "w") as f:
            json.dump(summary, f, indent=2)

        alias_path = self.output_dir / f"{run_id}-{self.mode}.json"
        with open(alias_path, "w") as f:
            json.dump(summary, f, indent=2)

        console.print(
            f"\n[bold]Summary:[/] {success_count}/{len(results)} "
            f"({success_count / len(results) * 100:.1f}%)"
        )
        console.print(f"[dim]Results saved to: {result_path}[/]")
        console.print(f"[dim]Result alias: {alias_path}[/]")

        configure_memory_store(None)
        return summary

    def _evaluate_answer(
        self,
        answer: dict[str, Any] | None,
        expected: dict[str, Any],
        task: dict[str, Any],
    ) -> dict[str, Any]:
        """Compare agent answer to expected answer."""
        if answer is None:
            return {"correct": False, "reason": "no_answer_provided"}

        expected_type = expected.get("type", "numeric")
        expected_value = expected.get("value")
        tolerance = expected.get("tolerance", 0.01)

        if expected_value is None:
            return {"correct": False, "reason": "no_expected_value"}

        # Extract actual value — handle model using different field names
        actual_value = answer.get("value")
        if actual_value is None:
            # Model may use "answer", "result" instead of "value"
            actual_value = answer.get("answer") or answer.get("result")
            # If still None, try extracting a number from any string field
            if actual_value is None:
                for val in answer.values():
                    if isinstance(val, (int, float)):
                        actual_value = val
                        break
                    if isinstance(val, str):
                        extracted = _extract_number(val)
                        if extracted is not None:
                            actual_value = extracted
                            break

        if actual_value is None:
            return {"correct": False, "reason": "no_value_in_answer"}

        # Skip tasks with placeholder expected values ("??")
        if expected_value == "??":
            # Tasks with "??" expected values need computed results — skip evaluation
            return {
                "correct": None,
                "reason": "skipped_placeholder_value",
                "note": "Expected value not precomputed for this task type",
            }

        if expected_type == "numeric":
            try:
                actual = float(actual_value)
                expected_float = float(expected_value)
                diff = abs(actual - expected_float)

                if expected_float != 0:
                    relative_diff = diff / abs(expected_float)
                else:
                    relative_diff = diff if diff > 0 else 0

                if relative_diff <= tolerance:
                    return {"correct": True, "reason": "within_tolerance"}
                else:
                    return {
                        "correct": False,
                        "reason": f"outside_tolerance (got {actual}, expected {expected_float}, diff={diff:.4f})",
                    }
            except (TypeError, ValueError) as e:
                return {"correct": False, "reason": f"cannot_compare: {e}"}

        elif expected_type == "exact":
            if str(actual_value).strip() == str(expected_value).strip():
                return {"correct": True, "reason": "exact_match"}
            return {
                "correct": False,
                "reason": f"mismatch: got '{actual_value}', expected '{expected_value}'",
            }

        elif expected_type == "set":
            try:
                actual_set = (
                    set(str(actual_value).split(","))
                    if isinstance(actual_value, str)
                    else set(actual_value or [])
                )
                expected_set = (
                    set(expected_value)
                    if isinstance(expected_value, list)
                    else set(str(expected_value).split(","))
                )
                if actual_set == expected_set:
                    return {"correct": True, "reason": "set_match"}
                return {
                    "correct": False,
                    "reason": f"set_mismatch: got {actual_set}, expected {expected_set}",
                }
            except Exception as e:
                return {"correct": False, "reason": f"set_comparison_failed: {e}"}

        return {"correct": False, "reason": f"unknown_type: {expected_type}"}


def _extract_number(text: str) -> float | None:
    """Extract a numeric value from a text string.

    Handles formats like: '€15,612.43', '25 orders', '42.5%', '15,612.43'
    """
    import re

    # Remove currency symbols, spaces, and text — keep digits, commas, dots, minus
    cleaned = re.sub(r"[^\d,.\-]", "", text.strip())
    # Remove thousand separators (commas between digits)
    cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _unique_memory_ids(memory_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for memory_id in memory_ids:
        if memory_id and memory_id not in seen:
            seen.add(memory_id)
            deduped.append(memory_id)
    return deduped


def _build_per_task_stats(results: list[dict[str, Any]], mode: str) -> dict[str, dict[str, Any]]:
    per_task: dict[str, dict[str, Any]] = {}

    for result in results:
        task_id = result.get("task_id")
        if not task_id:
            continue

        stats = per_task.setdefault(
            task_id,
            {
                "task_id": task_id,
                "domain": result.get("domain"),
                "repeats": 0,
                "successes": 0,
                "cache_hits": 0,
                "cache_misses": 0,
                "memory_hits": 0,
                "memory_retrievals": 0,
            },
        )
        stats["repeats"] += 1
        if result.get("evaluation", {}).get("correct", False):
            stats["successes"] += 1

        for query in result.get("query_history", []):
            cache_status = query.get("cache_status")
            if cache_status == "hit":
                stats["cache_hits"] += 1
            elif cache_status == "miss":
                stats["cache_misses"] += 1

        if mode == "cached_memory":
            stats["memory_retrievals"] += 1
            if result.get("retrieved_memory_ids"):
                stats["memory_hits"] += 1

    for stats in per_task.values():
        cache_total = stats["cache_hits"] + stats["cache_misses"]
        memory_total = stats["memory_retrievals"]
        stats["cache_hit_rate"] = stats["cache_hits"] / cache_total if cache_total else 0.0
        stats["memory_hit_rate"] = stats["memory_hits"] / memory_total if memory_total else 0.0
        stats["success_rate"] = stats["successes"] / stats["repeats"] if stats["repeats"] else 0.0

    return dict(sorted(per_task.items()))
