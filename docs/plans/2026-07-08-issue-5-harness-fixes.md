# Issue #5 Implementation Plan: Benchmark Harness Reliability

## Goal

Harden `agentic-data-harness` so benchmark results are reproducible and explainable. The fixes below are ordered by dependency and match the priorities in [Issue #5](https://github.com/rmax-ai/agentic-data-harness/issues/5).

## Design Decisions

1. `generate-data` should keep its existing CLI entrypoint and gain an explicit `--reset` flag.
   Reason: silent auto-drop is too destructive for a benchmark harness; an explicit reset preserves safety and reproducibility.

2. Relative-time tasks should use a fixed benchmark date stored as benchmark metadata, not wall clock time and not a user-tunable runtime flag.
   Reason: expected answers are precomputed at `seed=42`; making the anchor configurable would let runs silently drift away from the checked-in answers.

3. `final_answer.value` should remain the canonical answer field and continue to allow strings.
   Reason: the evaluator, task YAML, and existing answer extraction already center on `expected_answer.value`. Adding a parallel `label` field would create two answer channels without solving the core failure, which is wrong-field selection.

4. Grouped-output tasks should be brought into evaluator alignment explicitly.
   Recommended path: add structured answer support for grouped tasks where the question is genuinely grouped, instead of forcing the question into a scalar shape.

## Phase 1: P0-1 Idempotent Dataset Generation

### Objective

Make repeated `uv run adh generate-data` executions deterministic and safe.

### Files to Modify

- `src/adh/datasets/generator.py`
- `src/adh/app.py`
- `README.md`
- `tests/test_generator.py` (new)

### Planned Changes

- Add a `reset: bool = False` argument to `DataGenerator.generate_all()`.
- Add explicit drop helpers per domain before schema creation when `reset=True`.
- Add a preflight check when `reset=False`:
  if any target table already exists with rows, raise a specific `DatasetAlreadyExistsError` with guidance to rerun with `--reset`.
- Keep `generate-data` as the public CLI; add `--reset`.
- Update README quickstart so reruns use `uv run adh generate-data --reset` instead of manual DB deletion.

### Before/After Diff Sketch

```diff
diff --git a/src/adh/datasets/generator.py b/src/adh/datasets/generator.py
@@
-class DataGenerator:
+class DatasetAlreadyExistsError(RuntimeError):
+    """Raised when dataset generation would append into an existing benchmark dataset."""
+
+
+class DataGenerator:
@@
-    def generate_all(self, domains: list[str] | None = None):
+    def generate_all(self, domains: list[str] | None = None, reset: bool = False) -> None:
         """Generate all domains or a subset."""
         all_domains = ["sales_analytics", "support_tickets", "product_usage"]
         targets = domains or all_domains
 
         conn = duckdb.connect(str(self.db_path))
+
+        self._ensure_generation_target_is_safe(conn, targets=targets, reset=reset)
 
         for domain in targets:
+            if reset:
+                self._drop_domain_tables(conn, domain)
             if domain == "sales_analytics":
                 self._generate_sales(conn)
@@
+    def _ensure_generation_target_is_safe(
+        self,
+        conn: duckdb.DuckDBPyConnection,
+        targets: list[str],
+        reset: bool,
+    ) -> None:
+        if reset:
+            return
+        existing = self._existing_nonempty_tables(conn, targets)
+        if existing:
+            joined = ", ".join(existing)
+            raise DatasetAlreadyExistsError(
+                f"Existing benchmark tables contain rows: {joined}. "
+                "Re-run with --reset to recreate them."
+            )
```

```diff
diff --git a/src/adh/app.py b/src/adh/app.py
@@
 def generate_data(
     ctx: typer.Context,
@@
+    reset: Annotated[
+        bool,
+        typer.Option(
+            "--reset",
+            help="Drop and recreate target benchmark tables before inserting rows.",
+        ),
+    ] = False,
 ):
@@
-    gen.generate_all(domains=domains)
+    gen.generate_all(domains=domains, reset=reset)
```

```diff
diff --git a/README.md b/README.md
@@
-# Generate benchmark data (requires a clean database — delete data/duckdb/benchmark.db first if re-running)
-rm -f data/duckdb/benchmark.db
+# Generate benchmark data
 uv run adh init-db
 uv run adh generate-data
+
+# Recreate benchmark data safely on later runs
+uv run adh generate-data --reset
```

### Acceptance Criteria

- [ ] Running `uv run adh generate-data` twice on the same DB no longer ends with a DuckDB primary-key `ConstraintException`.
- [ ] Running `uv run adh generate-data --reset` recreates only the selected benchmark domain tables and succeeds repeatedly.
- [ ] Running `uv run adh generate-data --domain sales_analytics --reset` does not drop unrelated benchmark domains.
- [ ] The CLI help and README document the reset path; manual DB deletion is no longer required.

## Phase 2: P0-2 Stable Relative-Time Semantics

### Objective

Eliminate wall-clock dependence from relative-time tasks, especially `product_001`.

### Files to Modify

- `src/adh/datasets/generator.py`
- `src/adh/db/duckdb_runner.py`
- `src/adh/agents/prompts.py`
- `src/adh/agents/openai_sql_agent.py`
- `tasks/small.yaml`
- `tasks/full.yaml`
- `tests/test_generator.py`
- `tests/test_agent_prompts.py` (new)

### Planned Changes

- Introduce a benchmark metadata concept written during generation, for example:
  `benchmark_date = "2026-06-30"`.
- Store it in a small metadata table so the runtime reads the same anchor the dataset was generated with.
- Expose benchmark date context to the agent prompt on every task.
- Rewrite `product_001` task wording and expected SQL to anchor on benchmark date rather than `CURRENT_TIMESTAMP`.
- Update generator comments so product events are described as a fixed benchmark window, not "last 30 days of data".

### Recommended Semantics

- `benchmark_date = 2026-06-30`
- Relative windows are interpreted against `benchmark_date`, not wall clock.
- Prompt wording should say this explicitly:
  "For relative dates like 'last 30 days', use the benchmark date shown below, not CURRENT_TIMESTAMP."

### Before/After Diff Sketch

```diff
diff --git a/src/adh/datasets/generator.py b/src/adh/datasets/generator.py
@@
-from datetime import datetime, timedelta
+from datetime import date, datetime, timedelta
@@
+BENCHMARK_DATE = date(2026, 6, 30)
+
+BENCHMARK_METADATA_SCHEMA = """
+CREATE TABLE IF NOT EXISTS benchmark_metadata (
+    key VARCHAR PRIMARY KEY,
+    value VARCHAR NOT NULL
+)
+"""
@@
     def generate_all(self, domains: list[str] | None = None, reset: bool = False) -> None:
@@
+        conn.execute(BENCHMARK_METADATA_SCHEMA)
+        self._write_benchmark_metadata(conn)
@@
-        # Generate events — last 30 days of data
+        # Generate events for the fixed benchmark window ending on BENCHMARK_DATE
         events = []
         event_id = 1
         base_date = datetime(2026, 5, 1)
```

```diff
diff --git a/src/adh/db/duckdb_runner.py b/src/adh/db/duckdb_runner.py
@@
+    def get_benchmark_metadata(self) -> dict[str, str]:
+        tables = set(self.list_tables())
+        if "benchmark_metadata" not in tables:
+            return {}
+        rows = self.execute("SELECT key, value FROM benchmark_metadata")
+        return {str(key): str(value) for key, value in rows}
```

```diff
diff --git a/src/adh/agents/prompts.py b/src/adh/agents/prompts.py
@@
 USER_MESSAGE_TEMPLATE = """## Task
 {question}
+
+## Benchmark Context
+Benchmark date: {benchmark_date}
+For relative dates such as "last 30 days", use the benchmark date above, not CURRENT_TIMESTAMP.
 
 ## Database Schema
 {schema_summary}
```

```diff
diff --git a/src/adh/agents/openai_sql_agent.py b/src/adh/agents/openai_sql_agent.py
@@
         schema_summary = self._gateway.get_schema_summary()
+        benchmark_metadata = self._db.get_benchmark_metadata()
+        benchmark_date = benchmark_metadata.get("benchmark_date", "unknown")
@@
             user_message = USER_MESSAGE_TEMPLATE.format(
                 question=question,
+                benchmark_date=benchmark_date,
                 schema_summary=schema_summary,
```

```diff
diff --git a/tasks/full.yaml b/tasks/full.yaml
@@
 - id: product_001
   domain: product_usage
-  question: How many events did pro-plan users generate in the last 30 days?
+  question: Using benchmark date 2026-06-30, how many events did pro-plan users generate in the last 30 days?
   expected_answer:
     type: numeric
     value: 190
     tolerance: 0
-    sql: "SELECT COUNT(*) AS event_count\nFROM events e\nJOIN users u ON e.user_id = u.user_id\nWHERE u.plan_code = 'pro'\n  AND e.event_ts >= '2026-05-01'\n"
+    sql: "SELECT COUNT(*) AS event_count\nFROM events e\nJOIN users u ON e.user_id = u.user_id\nWHERE u.plan_code = 'pro'\n  AND CAST(e.event_ts AS TIMESTAMP) >= TIMESTAMP '2026-06-30 00:00:00' - INTERVAL 30 DAY\n"
```

Apply the same task edit in `tasks/small.yaml`.

### Acceptance Criteria

- [ ] `product_001` evaluates the same way on July 8, 2026 and on any later run date because it no longer depends on wall clock time.
- [ ] The agent prompt explicitly instructs the model to use benchmark date instead of `CURRENT_TIMESTAMP`.
- [ ] Benchmark metadata exists in the generated DB and is readable through `DuckDBRunner`.
- [ ] The task YAML and prompt agree on the date anchor.

## Phase 3: P0-3 Final Answer Selection Contract

### Objective

Stop failures where the SQL result is correct but the agent returns the adjacent metric column instead of the asked-for label column.

### Files to Modify

- `src/adh/agents/prompts.py`
- `src/adh/agents/schemas.py`
- `src/adh/gateway/sql_gateway.py`
- `src/adh/db/duckdb_runner.py`
- `src/adh/agents/openai_sql_agent.py`
- `tests/test_agent_answers.py` (new)
- `tests/test_runner.py`

### Planned Changes

- Keep `final_answer.value` as the answer payload, but update schema descriptions so string values are first-class.
- Add provenance fields to `FinalAnswer`, for example:
  `source_column`, `source_row_index`, `supporting_value`.
- Capture query result column names in gateway/agent history so the model sees structured row/column context rather than a raw tuple preview only.
- Add a lightweight validation step before accepting `action="final"`:
  if the final answer claims to come from a prior query result, ensure the selected `value` exists in the referenced row/column when possible.
- Strengthen prompt instructions for "which X" tasks:
  return the label column, not the metric used for ranking.

### Before/After Diff Sketch

```diff
diff --git a/src/adh/agents/prompts.py b/src/adh/agents/prompts.py
@@
   "final_answer": {{
-    "value": <the numeric answer as a number, e.g. 15612.43>,
+    "value": <the answer value; string answers are allowed for 'which/what category/country/feature' questions>,
     "unit": "<EUR, count, percent, etc.>",
-    "explanation": "<how you computed it>"
+    "explanation": "<how you computed it>",
+    "source_column": "<column in the last successful result that directly answers the question>",
+    "source_row_index": <0-based row index from the last successful result, usually 0>
   }}
@@
-IMPORTANT:
- If action=final, final_answer.value MUST be a number (int or float), not a string.
- final_answer.value is the raw number, not formatted with commas or currency symbols.
+IMPORTANT:
+- If the question asks "which", "what country", "what segment", or "what feature", return that label as final_answer.value.
+- Do not return an adjacent metric column from the same row.
+- final_answer.value must come from the last successful query result when one exists.
+- Numeric answers must stay raw numbers without formatting.
```

```diff
diff --git a/src/adh/agents/schemas.py b/src/adh/agents/schemas.py
@@
 class FinalAnswer(BaseModel):
     """Final answer structure."""
 
-    value: float | str | int = Field(description="Answer value")
+    value: float | str | int = Field(
+        description="Answer value; may be numeric or categorical depending on the task."
+    )
     unit: str | None = Field(default=None, description="Unit of measurement")
     explanation: str = Field(default="", description="How the answer was derived")
+    source_column: str | None = Field(default=None, description="Column used for the answer")
+    source_row_index: int | None = Field(default=None, description="Row used for the answer")
+    supporting_value: float | str | int | None = Field(
+        default=None,
+        description="Optional ranking metric from the same row",
+    )
```

```diff
diff --git a/src/adh/gateway/sql_gateway.py b/src/adh/gateway/sql_gateway.py
@@
 class SQLResult:
@@
     rows: list[tuple] = field(default_factory=list)
+    columns: list[str] = field(default_factory=list)
@@
-            rows = self._runner.execute(sql)
+            rows, columns = self._runner.execute_with_columns(sql)
@@
                 rows=rows,
+                columns=columns,
```

```diff
diff --git a/src/adh/db/duckdb_runner.py b/src/adh/db/duckdb_runner.py
@@
+    def execute_with_columns(
+        self,
+        sql: str,
+        params: list | dict | None = None,
+    ) -> tuple[list[tuple], list[str]]:
+        result = self.conn.execute(sql, params) if params else self.conn.execute(sql)
+        columns = [desc[0] for desc in result.description or []]
+        return result.fetchall(), columns
```

```diff
diff --git a/src/adh/agents/openai_sql_agent.py b/src/adh/agents/openai_sql_agent.py
@@
                     query_entry["rows"] = len(result.rows)
-                    query_entry["preview"] = _format_rows(result.rows[:5])
+                    query_entry["columns"] = result.columns
+                    query_entry["preview"] = _format_rows(result.rows[:5], result.columns)
@@
-            if action == "final" and response.final_answer:
+            if action == "final" and response.final_answer:
+                validated_answer = self._validate_final_answer(
+                    response.final_answer,
+                    query_history=query_history,
+                )
+                if validated_answer is None:
+                    error_context = (
+                        "Your final answer did not map to the last successful query result. "
+                        "Return the asked-for column explicitly."
+                    )
+                    continue
```

### Acceptance Criteria

- [ ] The prompt no longer tells the model that `final_answer.value` must always be numeric.
- [ ] `sales_003`, `support_003`, and `product_002` can pass when the agent finds the correct grouped row and returns the asked-for label.
- [ ] Final-answer validation rejects obvious wrong-column selections when a structured previous result is available.
- [ ] Query history includes column names for debugging and prompt grounding.

## Phase 4: P1 Prompt Constraint Checklist

### Objective

Reduce failures caused by missed status filters, date windows, coded dimensions, and hidden constraints.

### Files to Modify

- `src/adh/agents/prompts.py`
- `src/adh/agents/openai_sql_agent.py`
- `tasks/small.yaml`
- `tasks/full.yaml`
- `tests/test_agent_prompts.py`

### Planned Changes

- Expand the system prompt with a short pre-query checklist:
  identify requested metric, entity, time window, status filter, grouping, and coded dimensions before finalizing SQL.
- Add a final-answer checklist:
  verify every stated filter appears in the last successful SQL or in a prior intermediate validation query.
- Review task wording for the known misses:
  `sales_001`, `sales_006`, and any other task where a required filter is implicit rather than explicit.
- Prefer clarifying task text over relying on `required_concepts`, because `required_concepts` are not shown to the model today.

### Before/After Diff Sketch

```diff
diff --git a/src/adh/agents/prompts.py b/src/adh/agents/prompts.py
@@
 Rules:
 - Use only the provided schema and SQL execution results.
 - Do not invent columns. Inspect the schema before writing queries.
+- Before writing SQL, identify: metric, entity, time window, status filter, grouping, and any coded fields.
+- If the question mentions a country, plan, segment, month, unresolved/resolved state, or date window, ensure the SQL contains the matching filter.
+- Before returning a final answer, verify the final SQL result answers the exact question asked, not a nearby metric.
```

```diff
diff --git a/tasks/full.yaml b/tasks/full.yaml
@@
 - id: sales_006
-  question: What is the gross revenue in euros from Spanish customers who are in the midmarket segment?
+  question: What is the gross revenue in euros from completed orders placed by Spanish customers in the midmarket segment?
```

Apply only where the current text is materially underspecified relative to the expected SQL.

### Acceptance Criteria

- [ ] Prompt text explicitly reminds the agent to check time, status, grouping, and coded-dimension constraints.
- [ ] Tasks with known missed filters are clarified in YAML when the question itself is underspecified.
- [ ] The checklist is short enough to avoid token bloat but specific enough to address the observed misses.

## Phase 5: P1 Grouped/Categorical Evaluator Alignment

### Objective

Make the evaluator reflect the question shape for grouped outputs such as `support_002` and `support_005`.

### Files to Modify

- `src/adh/datasets/schemas.py`
- `src/adh/agents/schemas.py`
- `src/adh/evals/runner.py`
- `tasks/small.yaml`
- `tasks/full.yaml`
- `tests/test_runner.py`

### Planned Changes

- Add a structured expected-answer type for grouped outputs, for example `type: mapping`.
- Allow `FinalAnswer.value` to hold grouped objects when the task is genuinely multi-value.
- Extend `_evaluate_answer()` to compare mappings with per-value numeric tolerance.
- Update grouped tasks so their `expected_answer` matches the question literally.

### Recommended Task Fixes

- `support_002`
  Current question is grouped: "in each category".
  Change expected answer from scalar `access` to a mapping of category -> average score.

- `support_005`
  Current question is grouped: "each month in 2026".
  Change expected answer from scalar `2026-01` to a mapping of month -> ticket count.

If maintainers prefer to keep the benchmark scalar-only, then rewrite those questions into scalar forms instead. The grouped-answer route is the better fit for the current wording and the stated benchmark goal of trustworthy evaluation.

### Before/After Diff Sketch

```diff
diff --git a/src/adh/datasets/schemas.py b/src/adh/datasets/schemas.py
@@
 class ExpectedAnswer(BaseModel):
@@
-    value: float | str | list[str]
+    value: float | str | list[str] | dict[str, float | int | str]
```

```diff
diff --git a/src/adh/agents/schemas.py b/src/adh/agents/schemas.py
@@
-    value: float | str | int = Field(
+    value: float | str | int | dict[str, float | int | str] = Field(
         description="Answer value; may be numeric or categorical depending on the task."
     )
```

```diff
diff --git a/src/adh/evals/runner.py b/src/adh/evals/runner.py
@@
+        elif expected_type == "mapping":
+            try:
+                actual_mapping = actual_value if isinstance(actual_value, dict) else None
+                if actual_mapping is None:
+                    return {"correct": False, "reason": "mapping_expected_but_not_returned"}
+                return _compare_mapping(actual_mapping, expected_value, tolerance)
+            except (TypeError, ValueError) as e:
+                return {"correct": False, "reason": f"mapping_comparison_failed: {e}"}
```

```diff
diff --git a/tasks/small.yaml b/tasks/small.yaml
@@
 - id: support_002
   expected_answer:
-    type: exact
-    value: access
+    type: mapping
+    value:
+      access: 4.0
+      billing: 2.5
+      feature_request: 3.0
+      general: 3.2
+      technical: 2.9
@@
 - id: support_005
   expected_answer:
-    type: exact
-    value: 2026-01
+    type: mapping
+    value:
+      "2026-01": 17
+      "2026-02": 14
+      "2026-03": 19
+      ...
```

Populate the mapping values from the checked-in seed-42 dataset, not placeholders.

### Acceptance Criteria

- [ ] Grouped tasks no longer fail because the evaluator expects a scalar while the question asks for grouped output.
- [ ] `support_002` and `support_005` have expected answers whose shape matches the question text.
- [ ] `_evaluate_answer()` supports numeric, exact, set, and mapping answers with deterministic behavior.

## Phase 6: P2 CLI and Regression Coverage

### Objective

Close the remaining reliability/documentation gaps and lock the fixes down with tests.

### Files to Modify

- `src/adh/app.py`
- `README.md`
- `tests/test_generator.py`
- `tests/test_agent_prompts.py`
- `tests/test_agent_answers.py`
- `tests/test_runner.py`

### Planned Changes

- Treat the CLI item as an enhancement, not a new command:
  the existing `generate_data()` function already registers as `adh generate-data`.
- Add regression tests covering the fixed failure modes.
- Update CLI help text and README examples so the supported workflow is discoverable.

### Test Strategy

Add the following tests.

- `tests/test_generator.py`
  - `test_generate_all_raises_clear_error_when_tables_exist_without_reset`
  - `test_generate_all_reset_recreates_target_domain_tables`
  - `test_generate_all_writes_benchmark_metadata`

- `tests/test_agent_prompts.py`
  - `test_user_prompt_includes_benchmark_date_and_relative_time_rule`
  - `test_system_prompt_includes_constraint_checklist`
  - `test_user_prompt_allows_string_final_answers_for_which_questions`

- `tests/test_agent_answers.py`
  - `test_final_answer_validation_accepts_label_column_from_ranked_result`
  - `test_final_answer_validation_rejects_adjacent_metric_column`
  - `test_format_rows_includes_column_names_for_prompt_grounding`

- `tests/test_runner.py`
  - `test_evaluate_answer_exact_accepts_string_value`
  - `test_evaluate_answer_mapping_compares_grouped_output`
  - `test_evaluate_answer_mapping_rejects_scalar_for_grouped_task`

### Acceptance Criteria

- [ ] New tests cover idempotent generation, benchmark date semantics, answer-field selection, and grouped evaluator behavior.
- [ ] Existing tests still pass.
- [ ] `uv run pytest tests/ -v` passes after all fixes.
- [ ] `uv run ruff check --fix && uv run ruff format` is clean.

## Risks

### 1. Reset semantics could become too broad

If table dropping is implemented with a blanket `DROP ALL` approach, the harness may delete cache, trace, or memory tables unexpectedly. Restrict reset to benchmark domain tables plus benchmark metadata only.

### 2. Benchmark date could drift from checked-in expected answers

If the benchmark date is configurable or duplicated in multiple places, `product_001` can become inconsistent again. Keep one source of truth and persist it into the DB.

### 3. Final-answer validation could reject valid answers

If validation assumes every answer must come from the last query row verbatim, legitimate derived numeric answers may be blocked. Restrict strict validation to cases where the model provides `source_column` / `source_row_index` or the task is clearly label-selection from a ranked result.

### 4. Grouped-answer support increases answer-shape complexity

Adding `mapping` support expands schema and evaluator logic. Keep comparison rules deterministic and test exact failure messages.

### 5. Task YAML edits can invalidate past benchmark artifacts

Changing task wording or expected answer shapes means older report files are no longer directly comparable. Note the benchmark version change in release notes or changelog when these fixes land.

## Execution Order Summary

1. Phase 1: make generation safe to rerun.
2. Phase 2: anchor relative time to benchmark metadata.
3. Phase 3: fix final-answer field selection and validation.
4. Phase 4: add prompt constraint checklist and clarify underspecified tasks.
5. Phase 5: align grouped-task evaluation with grouped question shapes.
6. Phase 6: finish regression coverage, docs, and CLI discoverability.

## Definition of Done

- The harness can regenerate data repeatedly without manual cleanup.
- Relative-time tasks are stable on any run date.
- Known wrong-column failures are fixed by prompt/schema/validation changes.
- Grouped tasks are evaluated in a shape that matches the question.
- Regression tests cover the July 8, 2026 failure patterns documented in Issue #5.
