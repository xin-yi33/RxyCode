# evals/ - Evaluation Harness

## What Is This Module?
The evals module provides a real-task evaluation suite for RxyCode. It runs the full agent pipeline against a set of predefined coding tasks, checks the results with machine-verifiable assertions, and optionally scores them with an LLM-as-judge. Results can be saved, compared against baselines, and rendered as markdown reports.

**Design stitched from:**
- **SWE-bench**: task definition -> run -> verify flow; per-instance structured result records (passed / timing / cost)
- **Terminal-Bench**: task directory + instruction + check script; flattened into a single YAML per task
- **OpenHands eval/**: serial run loop with per-task isolation, result collection, and a separate report step
- **OpenAI evals**: LLM-as-judge scoring template pattern (fixed rubric, JSON output, dimension scores)

## Architecture

### Key Files
| File | Purpose |
|------|---------|
| `runner.py` | Core runner: `TaskResult`, `SuiteReport`, `run_task()`, `run_suite()`, CLI `main()` |
| `judge.py` | LLM-as-judge: `JudgeScore` dataclass, `judge_task()`, judge prompt template |
| `report.py` | Markdown report generation + baseline diff (`save_baseline`, `load_baseline`, `diff_baseline`) |
| `tasks.py` | Task definition loading & validation: `EvalTask`, `Check`, `load_tasks()`, schema validation |
| `tasks/*.yaml` | 18 task definition files (readcode, bugfix, refactor, feature categories) |
| `baselines/` | Saved baseline snapshots for diff comparison |
| `results/` | Persisted run results (`{tag}.json`) |
| `__init__.py` | Package metadata and CLI usage docs |
| `__main__.py` | Thin wrapper so `python -m evals` works |
| `run.py` | Entry point so `python -m evals.run` works |

### Core Code: tasks.py (Task Definitions)

**Dataclasses:**
- `Check` — One verification assertion. Types: `file_exists`, `file_contains`, `file_not_contains`, `command_succeeds`, `output_contains`
- `EvalTask` — A single evaluation task with `id`, `category`, `prompt`, `setup_files`, `checks`. The `needs_workdir` property auto-detects whether a task requires an isolated temp directory.

**Task Categories:** `readcode`, `bugfix`, `refactor`, `feature`

**Task YAML Schema:**
```yaml
id: bugfix-off-by-one
category: bugfix
prompt: |
  Fix the off-by-one error in the loop...
setup:
  files:
    calc.py: |
      ...
checks:
  - type: file_exists
    path: calc.py
  - type: file_contains
    path: calc.py
    pattern: "return total"
  - type: command_succeeds
    run: "python -m pytest {workdir}/test_calc.py -q"
  - type: output_contains
    pattern: "validator"
```

**Functions:**
- `load_task(path) -> EvalTask`: Load and validate one task YAML
- `load_tasks(tasks_dir, task_ids, category) -> list[EvalTask]`: Batch load with filtering

### Core Code: runner.py (Suite Runner)

**Dataclasses:**
- `TaskResult` — Result of a single eval task: `task_id`, `category`, `passed`, `duration_s`, `token_usage`, `judge_score`, `error`, `agent_answer`, `check_details`
- `SuiteReport` — Aggregated report: `results` list + `compute_summary()` with pass_rate, mean_judge_score, total_tokens, per-category breakdown

**Core Functions:**
- `run_task(task, llm, workdir) -> TaskResult`: Execute one task — build prompt, call LLM, extract code blocks, apply to workdir, run checks
- `run_suite(tasks, llm, judge_llm, tag) -> SuiteReport`: Run all tasks **serially** (avoids API rate limits), with optional LLM-as-judge scoring
- `setup_workdir(task, base) -> Path`: Create isolated temp workdir with setup files
- `apply_code_blocks(text, workdir) -> list[str]`: Extract fenced code blocks from LLM response and write to workdir
- `run_checks(task, workdir, agent_answer) -> (bool, list[dict])`: Execute all verification checks
- `save_results(report, tag) / load_results(tag)`: Persist/load results as JSON

### Core Code: judge.py (LLM-as-Judge)

- `JudgeScore` dataclass: `correctness` (1-5), `style` (1-5), `efficiency` (1-5), `rationale`, `ok`, `raw`
- `judge_task(llm, task_prompt, agent_answer, artifacts) -> JudgeScore`: Run one judge call through the usage-tracked LLM
- `parse_judge_output(text) -> JudgeScore`: Tolerant JSON extraction (never raises — a judge hiccup must not kill a run)
- `resolve_judge_model_name(cfg) -> Optional[str]`: Read `evals.judge_model` from config (None = use active model)
- Judge prompt uses a fixed rubric: correctness, style, efficiency — each 1-5 with anchored descriptions

### Core Code: report.py (Markdown Report + Baseline Diff)

- `generate_markdown(report) -> str`: Render a SuiteReport as human-readable markdown (summary, per-category table, per-task table)
- `save_baseline(report, name) / load_baseline(name) / list_baselines()`: Baseline snapshot management
- `diff_baseline(current, baseline_name) -> str`: Compare current run against a saved baseline — highlights summary metric deltas, per-task regressions (PASS -> FAIL), and improvements (FAIL -> PASS)

## Work Flow

1. Load tasks from `evals/tasks/*.yaml` (with schema validation)
2. For each task:
   - Create an isolated temp workdir if `needs_workdir` is True
   - Build the prompt (include setup file context for workdir tasks)
   - Call `llm.ainvoke()` with the prompt
   - Extract code blocks from the response and write to workdir
   - Run all verification checks (`file_exists`, `file_contains`, `command_succeeds`, `output_contains`)
   - If judge LLM is available, score the result with `judge_task()`
3. Aggregate into `SuiteReport`, compute summary (pass rate, mean judge score, tokens, duration, per-category breakdown)
4. Optionally persist to `evals/results/{tag}.json`
5. Optionally generate markdown report or diff against a baseline

## CLI

```bash
# Run full suite with a tag
python -m evals.run --tag myrun

# Run specific tasks
python -m evals.run --task-ids bugfix-off-by-one readcode-pipeline-nodes

# Filter by category
python -m evals.run --category bugfix

# Enable LLM-as-judge scoring
python -m evals.run --tag myrun --judge

# Dry run: validate task setup without calling LLM
python -m evals.run --dry
```

**Environment variables:**
- `OPENAI_API_KEY`: Required for LLM calls
- `EVAL_MODEL`: Model name (default: `gpt-4o`)
- `EVAL_BASE_URL`: Custom API base URL
- `EVAL_JUDGE_MODEL`: Separate model for judge scoring

## Dependencies
- **Internal**: `core/prompts` registry (judge prompt is version-managed), `config/settings.py` (evals config)
- **External**: `langchain_openai` (ChatOpenAI), `pyyaml` (task YAML loading), `numpy`
- This package runs REAL LLM calls and is kept OUT of the pytest suite — run it explicitly
