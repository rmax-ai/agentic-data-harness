"""CLI entry point for agentic-data-harness."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from adh.config import HarnessConfig, load_config

app = typer.Typer(no_args_is_help=True, name="adh")
console = Console()


def _resolve_path(path_str: str) -> Path:
    """Resolve path relative to project root (where pyproject.toml lives)."""
    return Path(path_str)


def _normalize_mode(mode: str) -> str:
    return mode.replace("-", "_")


def _display_mode(mode: str) -> str:
    return mode.replace("_", "-")


def _run_single_mode(
    cfg: HarnessConfig,
    tasks_file: str,
    run_mode: str,
    output_dir: str,
    max_steps: int,
    seed: int,
    repeat: int,
    cache_db_path: str | None,
) -> dict:
    from adh.agents.openai_sql_agent import OpenAISQLAgent
    from adh.db.duckdb_runner import DuckDBRunner
    from adh.evals.runner import BenchmarkRunner
    from adh.gateway.sql_gateway import SQLGateway
    from adh.memory.store import CorrectiveMemory

    db_runner = DuckDBRunner(cfg.database.path)
    gateway = None
    try:
        gateway = SQLGateway(
            db_runner,
            cache_enabled=(run_mode != "raw"),
            cache_db_path=cache_db_path,
        )
        memory_store = CorrectiveMemory(db_runner) if run_mode == "cached_memory" else None

        agent = OpenAISQLAgent(
            model_config=cfg.agent.to_model_config(),
            db_runner=db_runner,
            gateway=gateway,
            max_steps=max_steps,
            memory_store=memory_store,
        )

        runner = BenchmarkRunner(
            agent=agent,
            db_runner=db_runner,
            gateway=gateway,
            mode=run_mode,
            seed=seed,
            output_dir=output_dir,
            memory_store=memory_store,
            repeat=repeat,
            cache_db_path=cache_db_path,
        )
        return runner.run(tasks_file)
    finally:
        if gateway is not None:
            gateway.close()
        db_runner.close()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to config YAML file"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Override model name"),
    ] = None,
    mode: Annotated[
        str,
        typer.Option("--mode", help="Execution mode: raw | cached | cached-memory | all"),
    ] = "raw",
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose output"),
    ] = False,
):
    """agentic-data-harness — benchmark data-agent workloads."""
    ctx.ensure_object(dict)
    cfg = load_config(config_path=config, model_override=model, mode=_normalize_mode(mode))
    ctx.obj["config"] = cfg
    ctx.obj["verbose"] = verbose


@app.command()
def init_db(
    ctx: typer.Context,
    db_path: Annotated[
        str | None,
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
        str | None,
        typer.Option(
            "--domain",
            help="Domain to generate (sales_analytics, support_tickets, product_usage, or 'all')",
        ),
    ] = None,
    db_path: Annotated[
        str | None,
        typer.Option("--db-path", help="Path to DuckDB database file"),
    ] = None,
    seed: Annotated[
        int | None,
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
        str | None,
        typer.Option("--tasks", help="Path to tasks YAML file"),
    ] = None,
    mode: Annotated[
        str | None,
        typer.Option("--mode", help="Execution mode: raw | cached | cached-memory | all"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Override model name"),
    ] = None,
    output_dir: Annotated[
        str | None,
        typer.Option("--output-dir", "-o", help="Output directory for reports"),
    ] = None,
    max_steps: Annotated[
        int | None,
        typer.Option("--max-steps", help="Max SQL attempts per task"),
    ] = None,
    seed: Annotated[
        int | None,
        typer.Option("--seed", help="Random seed"),
    ] = None,
    repeat: Annotated[
        int,
        typer.Option("--repeat", min=1, help="Run each task N times in sequence"),
    ] = 1,
    cache_db: Annotated[
        str | None,
        typer.Option("--cache-db", help="Path to file-backed cache DuckDB"),
    ] = None,
):
    """Run benchmark tasks against the agent."""
    cfg: HarnessConfig = ctx.obj["config"]
    tasks_file = tasks_path or cfg.run.tasks
    run_mode = _normalize_mode(mode or cfg.run.mode)
    out_dir = output_dir or cfg.run.output_dir
    steps = max_steps if max_steps is not None else cfg.agent.max_steps
    s = seed if seed is not None else cfg.run.seed
    if model:
        cfg.agent.model = model

    console.print("[bold cyan]Running benchmark[/]")
    console.print(f"  Tasks: {tasks_file}")
    console.print(f"  Mode:  {_display_mode(run_mode)}")
    console.print(f"  Model: {cfg.agent.model}")
    console.print(f"  Seed:  {s}")
    console.print(f"  Repeat: {repeat}")
    if cache_db:
        console.print(f"  Cache DB: {cache_db}")

    if run_mode not in ("raw", "cached", "cached_memory", "all"):
        console.print(
            f"[red]Invalid mode: {run_mode}. Must be raw, cached, cached-memory, or all.[/]"
        )
        raise typer.Exit(1)

    if run_mode == "all":
        from adh.evals.report import generate_comparison_report

        summaries = {}
        for submode in ("raw", "cached", "cached_memory"):
            console.print(f"\n[bold]Running mode:[/] {_display_mode(submode)}")
            summaries[submode] = _run_single_mode(
                cfg=cfg,
                tasks_file=tasks_file,
                run_mode=submode,
                output_dir=out_dir,
                max_steps=steps,
                seed=s,
                repeat=repeat,
                cache_db_path=cache_db,
            )

        comparison_dir = Path(out_dir) / (
            datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ") + "-comparison"
        )
        report = generate_comparison_report(
            raw_results=summaries["raw"]["result_path"],
            cached_results=summaries["cached"]["result_path"],
            memory_results=summaries["cached_memory"]["result_path"],
            output_dir=comparison_dir,
        )
        console.print("\n[bold green]Benchmark comparison complete.[/]")
        console.print(f"[dim]Comparison report: {report['markdown_path']}[/]")
        return

    summary = _run_single_mode(
        cfg=cfg,
        tasks_file=tasks_file,
        run_mode=run_mode,
        output_dir=out_dir,
        max_steps=steps,
        seed=s,
        repeat=repeat,
        cache_db_path=cache_db,
    )

    if summary.get("results"):
        console.print("\n[bold green]Benchmark complete.[/]")
    else:
        console.print("\n[bold red]No tasks completed.[/]")


@app.command()
def compare(
    result_inputs: Annotated[
        list[str],
        typer.Argument(help="Result JSON files, directories, or glob patterns"),
    ],
    output_dir: Annotated[
        str | None,
        typer.Option("--output-dir", "-o", help="Directory for comparison artifacts"),
    ] = None,
):
    """Generate a 3-mode comparison report from result files."""
    from adh.evals.report import generate_comparison_report, resolve_result_inputs

    if not result_inputs:
        console.print("[red]Provide result files, directories, or glob patterns.[/]")
        raise typer.Exit(1)

    resolved = resolve_result_inputs(result_inputs)
    if output_dir:
        comparison_dir = Path(output_dir)
    else:
        comparison_dir = Path("reports") / (
            datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ") + "-comparison"
        )

    generate_comparison_report(
        raw_results=resolved["raw"],
        cached_results=resolved["cached"],
        memory_results=resolved["cached_memory"],
        output_dir=comparison_dir,
    )


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
        str | None,
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
