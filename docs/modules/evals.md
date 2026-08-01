# evals/ - Evaluation Harness

## What Is This Module?

The evals module runs **real AgentV2 tasks** against a curated suite of coding scenarios, verifies outcomes with machine-checkable assertions, and optionally scores answers with LLM-as-judge. Results can be saved, compared against baselines, and rendered as markdown reports.

**Design goals (Phase 1):**

- Measure **RxyCode** (AgentV2 + tools + graph), not just the underlying model
- Keep bugfix/refactor/feature tasks in **isolated temp workdirs** so the repo is never mutated
- Catch bad task definitions early via `scripts/lint_eval_tasks.py`

## Architecture

### Key Files

| File | Purpose |
|------|---------|
| `backends.py` | `RawLLMBackend` (baseline) and `AgentBackend` (default) |
| `runner.py` | `TaskResult`, `SuiteReport`, `run_task()`, `run_suite()`, CLI `main()` |
| `cli.py` | Alias entry: `python -m evals.cli` |
| `judge.py` | LLM-as-judge scoring |
| `report.py` | Markdown reports + baseline diff |
| `tasks.py` | Task loading, schema validation, 7 check types |
| `tasks/*.yaml` | One YAML file per task |
| `baselines/` | Saved baseline snapshots (`latest-agent.json`, etc.) |
| `results/` | Persisted run results (`{tag}.json`) |

### Backends

| Backend | CLI flag | What it measures |
|---------|----------|------------------|
| **agent** (default) | `--backend agent` | Full AgentV2 pipeline: LangGraph, tools, memory, safety gate |
| **raw-llm** | `--backend raw-llm` | Direct `llm.ainvoke()` — underlying model only |

The delta between the two backends is RxyCode's incremental value over bare LLM.

**Model configuration:** The CLI reads the **active model from `config.yaml`** via `get_active_model_config()`. Override with `--model <name>` or fall back to `OPENAI_API_KEY` when no key is in config.

### Check Types (7)

| Type | Needs workdir? | Asserts on |
|------|----------------|------------|
| `file_exists` | Yes | File present in task workdir |
| `file_contains` | Yes | Substring in workdir file |
| `file_not_contains` | Yes | Substring absent from workdir file |
| `command_succeeds` | Yes | Shell command exit code 0 in workdir |
| `output_contains` | No | Substring in agent's final text answer |
| `tool_used` | No | Named tool appeared in `tools_used` (agent backend) |
| `tool_not_used` | No | Named tool did **not** appear in `tools_used` |

### Workdir Rules (`evals/tasks.py`)

A task gets an **empty isolated temp directory** when:

1. It defines `setup.files`, **or**
2. Any check type is in `{file_exists, file_contains, file_not_contains, command_succeeds}`

**Historical lesson:** Do **not** use `file_exists` to check paths under the repo root (e.g. `core/prompts/registry.py`). Those checks run in an empty tempdir and **always fail**. Repo-structure assertions belong in `tests/`, not eval YAML.

`readcode` tasks typically have only `output_contains` / `tool_used` checks and run against the live repo via Agent tools.

## Adding a New Task

1. Create `evals/tasks/my-task.yaml`:

```yaml
id: my-task
category: bugfix
prompt: |
  Fix the bug in calc.py ...
setup:
  files:
    calc.py: |
      def broken(): ...
checks:
  - type: file_contains
    path: calc.py
    pattern: "fixed"
  - type: tool_used
    tool: write
```

2. Run the linter (required before every PR):

```powershell
python scripts\lint_eval_tasks.py
```

3. Dry-run schema validation:

```powershell
python -m evals.run --dry
```

4. Smoke-test with agent backend:

```powershell
python -m evals.run --backend agent --task-ids my-task
```

5. Confirm `git status --short` is clean after the run (no repo pollution).

## CLI

```powershell
# Full suite (agent backend, project model from config.yaml)
python -m evals.run

# Same via alias
python -m evals.cli run

# Raw LLM baseline comparison
python -m evals.run --backend raw-llm --tag raw-baseline

# Single task smoke test
python -m evals.run --backend agent --task-ids bugfix-off-by-one

# Save / compare baselines
python -m evals.run --backend agent --save-baseline latest-agent
python -m evals.run --backend agent --compare-baseline evals\baselines\latest-agent.json

# Limit task count (smoke)
python -m evals.run --max-tasks 3

# Dry run (no LLM)
python -m evals.run --dry
```

**Exit codes:**

- `0` — all tasks passed (and no baseline regression if `--compare-baseline` set)
- `1` — one or more tasks failed
- `2` — pass rate regressed vs baseline

## Baselines

Baselines live in `evals/baselines/` as JSON snapshots from `SuiteReport.to_dict()`.

**When to update:**

- After a deliberate harness or task change that should shift scores
- After a model switch that is the new production target
- Via nightly CI (`evals-nightly` job) on schedule

**Do not** update baselines to hide regressions.

## CI Integration

| When | What runs |
|------|-----------|
| Every PR | `python scripts/lint_eval_tasks.py` (in `lint` job) |
| Weekly schedule / manual `run_live` | `evals-nightly` compares agent run vs `latest-agent.json` |

Evals with real LLM calls are **not** in the PR gate (cost + latency).

## Dependencies

- **Internal**: `core/agent_v2.py`, `core/session_runtime.py`, `config/settings.py`
- **External**: `langchain_openai`, `pyyaml`

Unit tests for the harness live in `tests/test_core/test_evals_runner.py` and `tests/test_prompt_registry.py`. Full eval runs require API credentials and are executed explicitly or via nightly CI.
