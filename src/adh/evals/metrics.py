"""Eval metrics computation."""

from __future__ import annotations

from typing import Any


def compute_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary metrics from benchmark results."""
    total = len(results)
    if total == 0:
        return {"total_tasks": 0}

    success_count = sum(1 for r in results if r.get("evaluation", {}).get("correct", False))
    steps = [r.get("steps", 0) for r in results]
    queries = [sum(1 for q in r.get("query_history", []) if q.get("sql")) for r in results]

    error_types: dict[str, int] = {}
    for r in results:
        for q in r.get("query_history", []):
            err = q.get("error_type")
            if err:
                error_types[err] = error_types.get(err, 0) + 1

    return {
        "total_tasks": total,
        "success_count": success_count,
        "success_rate": success_count / total if total > 0 else 0,
        "avg_steps": sum(steps) / len(steps) if steps else 0,
        "avg_queries": sum(queries) / len(queries) if queries else 0,
        "median_queries": _median(queries) if queries else 0,
        "total_queries": sum(queries),
        "error_counts": error_types,
    }


def _median(values: list[int]) -> float:
    if not values:
        return 0
    sorted_vals = sorted(values)
    mid = len(sorted_vals) // 2
    if len(sorted_vals) % 2 == 0:
        return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
    return sorted_vals[mid]
