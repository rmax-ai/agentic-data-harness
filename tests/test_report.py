"""Tests for 3-mode comparison report generation."""

from __future__ import annotations

import json
from pathlib import Path

from adh.evals.report import generate_comparison_report, resolve_result_inputs


def test_generate_comparison_report_writes_markdown_and_json(tmp_path: Path) -> None:
    raw_path = _write_run(
        tmp_path=tmp_path,
        mode="raw",
        results=[
            _result("task_1", True, 2, 1),
            _result("task_2", False, 4, 2),
        ],
        trace_events=[],
    )
    cached_path = _write_run(
        tmp_path=tmp_path,
        mode="cached",
        results=[
            _result("task_1", True, 2, 1, cache_statuses=["miss"]),
            _result("task_1", True, 1, 1, cache_statuses=["hit"]),
            _result("task_2", True, 3, 1, cache_statuses=["miss"]),
        ],
        trace_events=[
            {"task_id": "task_1", "event_type": "cache_hit", "extra": {}},
            {"task_id": "task_1", "event_type": "cache_miss", "extra": {}},
            {"task_id": "task_2", "event_type": "cache_miss", "extra": {}},
        ],
    )
    memory_path = _write_run(
        tmp_path=tmp_path,
        mode="cached_memory",
        results=[
            _result(
                "task_1",
                True,
                1,
                1,
                retrieved_memory_ids=["mem_1"],
                cache_statuses=["miss"],
            ),
            _result(
                "task_1",
                True,
                1,
                1,
                retrieved_memory_ids=["mem_1"],
                cache_statuses=["hit"],
            ),
            _result("task_2", True, 2, 1, retrieved_memory_ids=[], cache_statuses=["hit"]),
        ],
        trace_events=[
            {"task_id": "task_1", "event_type": "cache_hit", "extra": {}},
            {"task_id": "task_1", "event_type": "cache_hit", "extra": {}},
            {"task_id": "task_1", "event_type": "cache_miss", "extra": {}},
            {"task_id": "task_1", "event_type": "memory_retrieved", "extra": {"count": 1}},
            {"task_id": "task_1", "event_type": "memory_retrieved", "extra": {"count": 1}},
            {"task_id": "task_2", "event_type": "memory_retrieved", "extra": {"count": 0}},
        ],
    )

    output_dir = tmp_path / "comparison"
    report = generate_comparison_report(
        raw_results=raw_path,
        cached_results=cached_path,
        memory_results=memory_path,
        output_dir=output_dir,
    )

    markdown = (output_dir / "comparison.md").read_text()
    payload = json.loads((output_dir / "comparison.json").read_text())

    assert Path(report["markdown_path"]).exists()
    assert Path(report["json_path"]).exists()
    assert "| cached-memory | 3/3 (100.0%) | 1.33 | 1.00 | 66.7% | 66.7% |" in markdown
    assert "### cached" in markdown
    assert "| task_1 | 2 | 100.0% | 50.0% (1/2) | 0.0% (0/0) |" in markdown
    assert payload["comparison"]["cached"]["cache_hit_rate"] == 1 / 3
    assert payload["comparison"]["cached_memory"]["memory_hit_rate"] == 2 / 3
    assert payload["comparison"]["raw"]["avg_steps"] == 3.0


def test_resolve_result_inputs_supports_glob_patterns(tmp_path: Path) -> None:
    prefix = "2026-07-08T210000Z"
    raw_path = _write_run(
        tmp_path=tmp_path, mode="raw", results=[_result("t1", True, 1, 1)], trace_events=[]
    )
    cached_path = _write_run(
        tmp_path=tmp_path,
        mode="cached",
        results=[_result("t1", True, 1, 1)],
        trace_events=[],
    )
    memory_path = _write_run(
        tmp_path=tmp_path,
        mode="cached_memory",
        results=[_result("t1", True, 1, 1, retrieved_memory_ids=[])],
        trace_events=[],
    )

    raw_alias = tmp_path / f"{prefix}-raw.json"
    cached_alias = tmp_path / f"{prefix}-cached.json"
    memory_alias = tmp_path / f"{prefix}-cached_memory.json"
    raw_alias.write_text(raw_path.read_text())
    cached_alias.write_text(cached_path.read_text())
    memory_alias.write_text(memory_path.read_text())

    resolved = resolve_result_inputs([str(tmp_path / f"{prefix}*.json")])

    assert resolved["raw"] == raw_alias
    assert resolved["cached"] == cached_alias
    assert resolved["cached_memory"] == memory_alias


def _write_run(
    tmp_path: Path,
    mode: str,
    results: list[dict],
    trace_events: list[dict],
) -> Path:
    trace_path = tmp_path / f"traces.{mode}.jsonl"
    with trace_path.open("w") as handle:
        for event in trace_events:
            handle.write(json.dumps(event) + "\n")

    result_path = tmp_path / f"{mode}.json"
    payload = {
        "run_id": f"run-{mode}",
        "mode": mode,
        "seed": 42,
        "total_tasks": len(results),
        "success_count": sum(1 for result in results if result["evaluation"]["correct"]),
        "success_rate": sum(1 for result in results if result["evaluation"]["correct"])
        / len(results),
        "result_path": str(result_path),
        "trace_path": str(trace_path),
        "results": results,
    }
    result_path.write_text(json.dumps(payload, indent=2))
    return result_path


def _result(
    task_id: str,
    correct: bool,
    steps: int,
    query_count: int,
    retrieved_memory_ids: list[str] | None = None,
    cache_statuses: list[str] | None = None,
) -> dict:
    return {
        "task_id": task_id,
        "steps": steps,
        "query_history": [
            {
                "sql": f"SELECT {index + 1}",
                **(
                    {"cache_status": cache_statuses[index]}
                    if cache_statuses is not None and index < len(cache_statuses)
                    else {}
                ),
            }
            for index in range(query_count)
        ],
        "evaluation": {"correct": correct, "reason": "test"},
        "retrieved_memory_ids": retrieved_memory_ids or [],
    }
