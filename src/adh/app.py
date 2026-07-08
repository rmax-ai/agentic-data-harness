"""CLI entry point for agentic-data-harness."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from adh.config import HarnessConfig, load_config

app = typer.Typer(no_args_is_help=True, name="adh")
console = Console()


def _resolve_path(path_str: str) -> Path:
    """Resolve path relative to project root (where pyproject.toml lives)."""
    return Path(path_str)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", "-c", help="Path to config YAML file"),
    ] = None,
    model: Annotated[
        Optional[str],
        typer.Option("--model", "-m", help="Override model name"),
    ] = None,
    mode: Annotated[
        str,
        typer.Option("--mode", help="Execution mode: raw | cached | cached_memory"),
    ] = "raw",
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose output"),
    ] = False,
):
    """agentic-data-harness — benchmark data-agent workloads."""
    ctx.ensure_object(dict)
    cfg = load_config(config_path=config, model_override=model, mode=mode)
    ctx.obj["config"] = cfg
    ctx.obj["verbose"] = verbose


@app.command()
def init_db(
    ctx: typer.Context,
    db_path: Annotated[
        Optional[str],
        typer.Option("--db-path", help="Path to DuckDB database file"),
    ] = None,
):
    """Initialize the DuckDB database with benchmark tables."""
    cfg: HarnessConfig = ctx.obj["config"]
    db = db_path or cfg.database.path
    console.print(f"[bold cyan]Initializing database:[/] {db}")

    from adh.db.duckdb_runner import DuckDBRunner

    runner = DuckDBRunner(db)
    runner.init_tables()
    console.print("[green]Tables created.[/]")

    # Create trace tables
    from adh.tracing.events import init_traces

    init_traces(runner)
    console.print("[green]Trace tables created.[/]")

    console.print("[bold green]Database initialized.[/]")


@app.command()
def generate_data(
    ctx: typer.Context,
    domain: Annotated[
        Optional[str],
        typer.Option("--domain", help="Domain to generate (sales_analytics, support_tickets, product_usage, or 'all')"),
    ] = None,
    db_path: Annotated[
        Optional[str],
        typer.Option("--db-path", help="Path to DuckDB database file"),
    ] = None,
    seed: Annotated[
        Optional[int],
        typer.Option("--seed", help="Random seed for reproducibility"),
    ] = None,
):
    """Generate synthetic benchmark datasets."""
    cfg: HarnessConfig = ctx.obj["config"]
    db = db_path or cfg.database.path
    s = seed if seed is not None else cfg.run.seed

    console.print(f"[bold cyan]Generating data[/] (seed={s}, db={db})")

    from adh.datasets.generator import DataGenerator

    gen = DataGenerator(db_path=db, seed=s)

    domains = [domain] if domain and domain != "all" else None
    gen.generate_all(domains=domains)
    console.print("[bold green]Datasets generated.[/]")


@app.command()
def run(
    ctx: typer.Context,
    tasks_path: Annotated[
        Optional[str],
        typer.Option("--tasks", help="Path to tasks YAML file"),
    ] = None,
    mode: Annotated[
        Optional[str],
        typer.Option("--mode", help="Execution mode: raw | cached | cached_memory"),
    ] = None,
    model: Annotated[
        Optional[str],
        typer.Option("--model", "-m", help="Override model name"),
    ] = None,
    output_dir: Annotated[
        Optional[str],
        typer.Option("--output-dir", "-o", help="Output directory for reports"),
    ] = None,
    max_steps: Annotated[
        Optional[int],
        typer.Option("--max-steps", help="Max SQL attempts per task"),
    ] = None,
    seed: Annotated[
        Optional[int],
        typer.Option("--seed", help="Random seed"),
    ] = None,
):
    """Run benchmark tasks against the agent."""
    cfg: HarnessConfig = ctx.obj["config"]
    tasks_file = tasks_path or cfg.run.tasks
    run_mode = mode or cfg.run.mode
    out_dir = output_dir or cfg.run.output_dir
    steps = max_steps if max_steps is not None else cfg.agent.max_steps
    s = seed if seed is not None else cfg.run.seed

    console.print(f"[bold cyan]Running benchmark[/]")
    console.print(f"  Tasks: {tasks_file}")
    console.print(f"  Mode:  {run_mode}")
    console.print(f"  Model: {model or cfg.agent.model}")
    console.print(f"  Seed:  {s}")

    if run_mode not in ("raw", "cached", "cached_memory"):
        console.print(f"[red]Invalid mode: {run_mode}. Must be raw, cached, or cached_memory.[/]")
        raise typer.Exit(1)

    from adh.evals.runner import BenchmarkRunner
    from adh.agents.openai_sql_agent import OpenAISQLAgent
    from adh.db.duckdb_runner import DuckDBRunner
    from adh.gateway.sql_gateway import SQLGateway

    db_runner = DuckDBRunner(cfg.database.path)
    gateway = SQLGateway(db_runner, cache_enabled=(run_mode != "raw"))

    agent = OpenAISQLAgent(
        model_config=cfg.agent.to_model_config(),
        db_runner=db_runner,
        gateway=gateway,
        max_steps=steps,
    )

    runner = BenchmarkRunner(
        agent=agent,
        db_runner=db_runner,
        gateway=gateway,
        mode=run_mode,
        seed=s,
        output_dir=out_dir,
    )

    results = runner.run(tasks_file)

    if results:
        console.print(f"\n[bold green]Benchmark complete.[/]")
    else:
        console.print(f"\n[bold red]No tasks completed.[/]")


@app.command()
def report(
    ctx: typer.Context,
    run_dir: Annotated[
        str,
        typer.Argument(help="Path to run directory containing JSON result files"),
    ],
):
    """Generate comparison report from benchmark results."""
    console.print(f"[bold cyan]Generating report from:[/] {run_dir}")

    from adh.evals.report import generate_report

    generate_report(run_dir)


@app.command()
def check_task(
    ctx: typer.Context,
    task_id: Annotated[str, typer.Argument(help="Task ID to check (e.g. sales_001)")],
    tasks_path: Annotated[
        Optional[str],
        typer.Option("--tasks", help="Path to tasks YAML file"),
    ] = None,
):
    """Verify a single task's expected answer against the database."""
    cfg: HarnessConfig = ctx.obj["config"]
    tasks_file = tasks_path or cfg.run.tasks

    import yaml

    with open(tasks_file) as f:
        tasks_data = yaml.safe_load(f)

    task = None
    for t in tasks_data.get("tasks", []):
        if t["id"] == task_id:
            task = t
            break

    if not task:
        console.print(f"[red]Task not found: {task_id}[/]")
        raise typer.Exit(1)

    from adh.db.duckdb_runner import DuckDBRunner

    runner = DuckDBRunner(cfg.database.path)

    console.print(f"[bold]Task:[/] {task['id']} - {task['question']}")
    console.print(f"[bold]Expected answer:[/] {task['expected_answer']}")

    # If the task has an expected SQL query, run it
    expected_sql = task.get("expected_answer", {}).get("sql")
    if expected_sql:
        try:
            result = runner.execute(expected_sql)
            console.print(f"[green]Query result:[/] {result}")
        except Exception as e:
            console.print(f"[red]Query error:[/] {e}")
    else:
        console.print("[yellow]No expected SQL query defined for this task.[/]")


if __name__ == "__main__":
    app()
