"""Comparison report generation for raw, cached, and cached-memory runs."""

from __future__ import annotations

import glob
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from adh.evals.metrics import compute_metrics

console = Console()


def generate_comparison_report(
    raw_results: str | Path | dict[str, Any],
    cached_results: str | Path | dict[str, Any],
    memory_results: str | Path | dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    """Generate markdown and JSON comparison artifacts for all three modes."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    runs = {
        "raw": _load_results(raw_results),
        "cached": _load_results(cached_results),
        "cached_memory": _load_results(memory_results),
    }
    comparison = {mode: _build_mode_summary(data) for mode, data in runs.items()}

    markdown = _build_markdown_report(comparison, runs)
    markdown_path = output_path / "comparison.md"
    markdown_path.write_text(markdown)

    payload = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "comparison": comparison,
        "runs": runs,
    }
    json_path = output_path / "comparison.json"
    json_path.write_text(json.dumps(payload, indent=2))

    _print_comparison_table(comparison)
    console.print(f"[green]Markdown report:[/] {markdown_path}")
    console.print(f"[green]JSON report:[/] {json_path}")

    return {
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
        "comparison": comparison,
    }


def generate_report(run_dir: str | Path) -> dict[str, Any] | None:
    """Generate a comparison report from result JSONs under a directory."""
    try:
        mode_paths = resolve_result_inputs([str(run_dir)])
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        return None
    return generate_comparison_report(
        raw_results=mode_paths["raw"],
        cached_results=mode_paths["cached"],
        memory_results=mode_paths["cached_memory"],
        output_dir=Path(run_dir),
    )


def resolve_result_inputs(inputs: list[str]) -> dict[str, Path]:
    """Resolve directories, files, or glob patterns into one result file per mode."""
    discovered: dict[str, list[Path]] = {"raw": [], "cached": [], "cached_memory": []}

    for entry in inputs:
        for path in _expand_input(entry):
            if not path.is_file() or path.suffix != ".json":
                continue
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            mode = _normalize_mode(data.get("mode"))
            if mode in discovered and "results" in data:
                discovered[mode].append(path)

    missing = [mode for mode, paths in discovered.items() if not paths]
    if missing:
        raise ValueError("Missing result files for mode(s): " + ", ".join(sorted(missing)))

    resolved: dict[str, Path] = {}
    for mode, paths in discovered.items():
        resolved[mode] = max(paths, key=lambda path: path.stat().st_mtime)
    return resolved


def _expand_input(entry: str) -> list[Path]:
    if any(char in entry for char in "*?[]"):
        return [Path(path) for path in glob.glob(entry, recursive=True)]

    path = Path(entry)
    if path.is_dir():
        return sorted(path.rglob("*.json"))
    if path.exists():
        return [path]
    return []


def _load_results(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, dict):
        return source
    path = Path(source)
    return json.loads(path.read_text())


def _build_mode_summary(data: dict[str, Any]) -> dict[str, Any]:
    metrics = compute_metrics(data.get("results", []))
    trace_metrics = _trace_metrics(data)
    per_task_stats = _get_per_task_stats(data)
    return {
        "mode": _normalize_mode(data.get("mode")),
        "success_count": metrics.get("success_count", 0),
        "total_tasks": metrics.get("total_tasks", 0),
        "success_rate": metrics.get("success_rate", 0.0),
        "avg_steps": metrics.get("avg_steps", 0.0),
        "avg_queries": metrics.get("avg_queries", 0.0),
        "cache_hit_rate": trace_metrics["cache_hit_rate"],
        "cache_hits": trace_metrics["cache_hits"],
        "cache_misses": trace_metrics["cache_misses"],
        "memory_hit_rate": trace_metrics["memory_hit_rate"],
        "memory_hits": trace_metrics["memory_hits"],
        "memory_retrievals": trace_metrics["memory_retrievals"],
        "per_task_stats": per_task_stats,
    }


def _trace_metrics(data: dict[str, Any]) -> dict[str, Any]:
    cache_hits = 0
    cache_misses = 0
    memory_hits = 0
    memory_retrievals = 0

    trace_path = data.get("trace_path")
    if trace_path and Path(trace_path).exists():
        for line in Path(trace_path).read_text().splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            event_type = event.get("event_type")
            if event_type == "cache_hit":
                cache_hits += 1
            elif event_type == "cache_miss":
                cache_misses += 1
            elif event_type == "memory_retrieved":
                memory_retrievals += 1
                extra = event.get("extra") or {}
                if int(extra.get("count", 0)) > 0:
                    memory_hits += 1
    else:
        for result in data.get("results", []):
            if result.get("retrieved_memory_ids"):
                memory_hits += 1
            if "retrieved_memory_ids" in result:
                memory_retrievals += 1

    cache_denominator = cache_hits + cache_misses
    memory_denominator = memory_retrievals
    return {
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "cache_hit_rate": cache_hits / cache_denominator if cache_denominator else 0.0,
        "memory_hits": memory_hits,
        "memory_retrievals": memory_retrievals,
        "memory_hit_rate": memory_hits / memory_denominator if memory_denominator else 0.0,
    }


def _build_markdown_report(
    comparison: dict[str, dict[str, Any]],
    runs: dict[str, dict[str, Any]],
) -> str:
    lines = [
        "# Benchmark Comparison",
        "",
        "| Mode | Success | Avg Steps | Avg Queries | Cache Hit Rate | Memory Hit Rate |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for mode in ("raw", "cached", "cached_memory"):
        summary = comparison[mode]
        lines.append(
            "| "
            f"{_display_mode(mode)} | "
            f"{summary['success_count']}/{summary['total_tasks']} ({summary['success_rate']:.1%}) | "
            f"{summary['avg_steps']:.2f} | "
            f"{summary['avg_queries']:.2f} | "
            f"{summary['cache_hit_rate']:.1%} | "
            f"{summary['memory_hit_rate']:.1%} |"
        )

    lines.extend(
        [
            "",
            "## Inputs",
            "",
        ]
    )
    lines.extend(
        f"- `{_display_mode(mode)}`: `{runs[mode].get('result_path', 'in-memory')}`"
        for mode in ("raw", "cached", "cached_memory")
    )
    lines.append("")

    lines.extend(
        [
            "## Per-task hit rates",
            "",
            "Cache and memory rates below are aggregated across repeats for each task ID.",
            "",
        ]
    )

    for mode in ("raw", "cached", "cached_memory"):
        lines.extend(
            [
                f"### {_display_mode(mode)}",
                "",
                "| Task | Repeats | Success Rate | Cache Hit Rate | Memory Hit Rate |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        per_task_stats = comparison[mode].get("per_task_stats", {})
        for task_id, stats in sorted(per_task_stats.items()):
            lines.append(
                "| "
                f"{task_id} | "
                f"{stats['repeats']} | "
                f"{stats['success_rate']:.1%} | "
                f"{stats['cache_hit_rate']:.1%} "
                f"({stats['cache_hits']}/{stats['cache_hits'] + stats['cache_misses']}) | "
                f"{stats['memory_hit_rate']:.1%} "
                f"({stats['memory_hits']}/{stats['memory_retrievals']}) |"
            )
        lines.append("")
    return "\n".join(lines)


def _print_comparison_table(comparison: dict[str, dict[str, Any]]) -> None:
    table = Table(title="Benchmark Comparison")
    table.add_column("Mode", style="cyan")
    table.add_column("Success", justify="right")
    table.add_column("Avg Steps", justify="right")
    table.add_column("Avg Queries", justify="right")
    table.add_column("Cache Hit Rate", justify="right")
    table.add_column("Memory Hit Rate", justify="right")

    for mode in ("raw", "cached", "cached_memory"):
        summary = comparison[mode]
        table.add_row(
            _display_mode(mode),
            f"{summary['success_count']}/{summary['total_tasks']} ({summary['success_rate']:.1%})",
            f"{summary['avg_steps']:.2f}",
            f"{summary['avg_queries']:.2f}",
            f"{summary['cache_hit_rate']:.1%}",
            f"{summary['memory_hit_rate']:.1%}",
        )

    console.print(table)


def _normalize_mode(mode: Any) -> str:
    return str(mode or "").replace("-", "_")


def _display_mode(mode: str) -> str:
    return mode.replace("_", "-")


def _get_per_task_stats(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    existing = data.get("per_task_stats")
    if isinstance(existing, dict) and existing:
        return existing
    return _derive_per_task_stats(data)


def _derive_per_task_stats(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mode = _normalize_mode(data.get("mode"))
    per_task: dict[str, dict[str, Any]] = {}

    for result in data.get("results", []):
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

    trace_path = data.get("trace_path")
    if trace_path and Path(trace_path).exists():
        traced_cache = any(
            stats["cache_hits"] or stats["cache_misses"] for stats in per_task.values()
        )
        traced_memory = any(stats["memory_retrievals"] for stats in per_task.values())
        if not traced_cache or (mode == "cached_memory" and not traced_memory):
            for line in Path(trace_path).read_text().splitlines():
                if not line.strip():
                    continue
                event = json.loads(line)
                task_id = event.get("task_id")
                if not task_id:
                    continue
                stats = per_task.setdefault(
                    task_id,
                    {
                        "task_id": task_id,
                        "domain": None,
                        "repeats": 0,
                        "successes": 0,
                        "cache_hits": 0,
                        "cache_misses": 0,
                        "memory_hits": 0,
                        "memory_retrievals": 0,
                    },
                )
                event_type = event.get("event_type")
                if event_type == "cache_hit" and not traced_cache:
                    stats["cache_hits"] += 1
                elif event_type == "cache_miss" and not traced_cache:
                    stats["cache_misses"] += 1
                elif (
                    event_type == "memory_retrieved"
                    and mode == "cached_memory"
                    and not traced_memory
                ):
                    stats["memory_retrievals"] += 1
                    extra = event.get("extra") or {}
                    if int(extra.get("count", 0)) > 0:
                        stats["memory_hits"] += 1

    for stats in per_task.values():
        cache_total = stats["cache_hits"] + stats["cache_misses"]
        memory_total = stats["memory_retrievals"]
        stats["cache_hit_rate"] = stats["cache_hits"] / cache_total if cache_total else 0.0
        stats["memory_hit_rate"] = stats["memory_hits"] / memory_total if memory_total else 0.0
        stats["success_rate"] = stats["successes"] / stats["repeats"] if stats["repeats"] else 0.0

    return dict(sorted(per_task.items()))
