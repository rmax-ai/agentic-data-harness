"""Report generation — placeholder for Phase 6."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from adh.evals.metrics import compute_metrics

console = Console()


def generate_report(run_dir: str | Path):
    """Generate a comparison report from JSON result files in a run directory."""
    path = Path(run_dir)
    if not path.exists():
        console.print(f"[red]Directory not found: {run_dir}[/]")
        return

    # Look for mode-specific JSON files
    modes = []
    for mode in ("raw", "cached", "cached_memory"):
        mode_path = path / f"{mode}.json"
        if mode_path.exists():
            with open(mode_path) as f:
                data = json.load(f)
                modes.append((mode, data))

    if not modes:
        console.print("[yellow]No result JSON files found in directory.[/]")
        return

    # Build comparison table
    table = Table(title="Benchmark Comparison")
    table.add_column("Metric", style="cyan")
    for mode_name, _ in modes:
        table.add_column(mode_name.capitalize(), justify="right")

    for label, key in [
        ("Success Rate", "success_count"),
        ("Avg Queries", "avg_queries"),
        ("Total Tasks", "total_tasks"),
    ]:
        row = [label]
        for _, data in modes:
            results = data.get("results", [])
            if results:
                metrics = compute_metrics(results)
                if key == "success_rate":
                    row.append(f"{metrics['success_rate']:.1%}")
                elif key == "success_count":
                    row.append(f"{metrics['success_count']}/{metrics['total_tasks']}")
                elif key == "avg_queries":
                    row.append(f"{metrics['avg_queries']:.1f}")
                else:
                    row.append(str(metrics.get(key, "N/A")))
            else:
                row.append("N/A")
        table.add_row(*row)

    console.print(table)
