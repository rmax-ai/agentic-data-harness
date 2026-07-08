"""Benchmark runner that executes tasks and evaluates results."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from adh.agents.openai_sql_agent import OpenAISQLAgent
from adh.db.duckdb_runner import DuckDBRunner
from adh.gateway.sql_gateway import SQLGateway
from adh.tracing.events import TraceStore

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
    ):
        self.agent = agent
        self._db = db_runner
        self._gateway = gateway
        self.mode = mode
        self.seed = seed
        self.output_dir = Path(output_dir)

    def run(self, tasks_path: str) -> list[dict[str, Any]]:
        """Run all tasks from a YAML file and return results."""
        with open(tasks_path) as f:
            tasks_data = yaml.safe_load(f)

        tasks = tasks_data.get("tasks", [])
        if not tasks:
            console.print("[red]No tasks found in task file.[/]")
            return []

        run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
        run_dir = self.output_dir / f"{run_id}-{self.mode}"
        run_dir.mkdir(parents=True, exist_ok=True)

        trace_store = TraceStore(run_dir)
        self.agent._trace = trace_store  # Inject trace store

        results = []
        success_count = 0

        console.print(f"\n[bold]Benchmark Run[/] [{self.mode}] — {len(tasks)} tasks")
        console.print(f"Run ID: {run_id}\n")

        for i, task in enumerate(tasks, 1):
            task_id = task["id"]
            question = task["question"]
            expected = task.get("expected_answer", {})

            console.print(f"  [{i}/{len(tasks)}] {task_id}: {question[:80]}...")

            result = self.agent.solve(
                task_id=task_id,
                question=question,
                run_id=run_id,
                mode=self.mode,
            )

            # Evaluate answer
            evaluation = self._evaluate_answer(result.get("answer"), expected, task)
            result["evaluation"] = evaluation

            if evaluation.get("correct", False):
                success_count += 1
                console.print(f"    [green]PASS[/] — {result.get('steps', '?')} steps")
            else:
                console.print(f"    [red]FAIL[/] — {evaluation.get('reason', 'unknown')}")

            results.append(result)

        # Save results
        result_path = run_dir / f"{self.mode}.json"
        with open(result_path, "w") as f:
            json.dump({
                "run_id": run_id,
                "mode": self.mode,
                "seed": self.seed,
                "total_tasks": len(tasks),
                "success_count": success_count,
                "success_rate": success_count / len(tasks) if tasks else 0,
                "results": results,
            }, f, indent=2)

        # Flush traces
        trace_store.flush(f"{run_id}-{self.mode}")

        console.print(f"\n[bold]Summary:[/] {success_count}/{len(tasks)} ({success_count/len(tasks)*100:.1f}%)")
        console.print(f"[dim]Results saved to: {result_path}[/]")

        return results

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

        actual_value = answer.get("value")

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
                actual_set = set(str(actual_value).split(",")) if isinstance(actual_value, str) else set(actual_value or [])
                expected_set = set(expected_value) if isinstance(expected_value, list) else set(str(expected_value).split(","))
                if actual_set == expected_set:
                    return {"correct": True, "reason": "set_match"}
                return {
                    "correct": False,
                    "reason": f"set_mismatch: got {actual_set}, expected {expected_set}",
                }
            except Exception as e:
                return {"correct": False, "reason": f"set_comparison_failed: {e}"}

        return {"correct": False, "reason": f"unknown_type: {expected_type}"}
