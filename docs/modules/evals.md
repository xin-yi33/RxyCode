# evals/ - Evaluation Harness

## What Is This Module?

The evals module runs **real AgentV2 tasks** against a curated suite of coding scenarios, verifies outcomes with machine-checkable assertions, and optionally scores answers with LLM-as-judge. Results can be saved, compared against baselines, and rendered as markdown reports.

Evals is a **source-checkout harness**. The published CLI wheel / sdist and the
Desktop bundled `app/` tree do not ship `evals/`. Run it from a git clone:
`python -m evals.run`.

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

## Web Search Tasks

`websearch-summary` and `websearch-save-report` cover the agent's web-search
capability end to end. They live in the `feature` category (reusing the existing
four categories — no runner/CLI change needed) and rely on the stable
`tool_used: websearch` assertion, which passes as long as the agent actually
invoked the websearch tool, regardless of whether the external engine returned
results.

**Network sensitivity:** these tasks hit live DuckDuckGo / Baidu / Bing / Google
endpoints. Search engines sometimes rate-limit or block scrapers, so a web task
may fail in the nightly run for reasons unrelated to the agent's code. Do **not**
change harness code or baselines based on a single flaky web-task failure; treat
it as an external-network signal and re-run before investigating.

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

- `0` — all tasks passed, no baseline regression, **or** the baseline gate
  skipped because the provider returned auth/quota/circuit-breaker errors
- `1` — one or more tasks failed
- `2` — pass rate regressed vs baseline

## Baselines

Baselines live in `evals/baselines/` as JSON snapshots from `SuiteReport.to_dict()`.

**When to update:**

- After a deliberate harness or task change that should shift scores
- After a model switch that is the new production target

**Do not** update baselines to hide regressions.

## CI Integration

| When | What runs |
|------|-----------|
| Every PR | `python scripts/lint_eval_tasks.py` (in `lint` job) |

Evals with real LLM calls are **not** in GitHub Actions (they need a local API
key). Run them on a machine you control:

```powershell
python -m evals.cli run --backend agent --compare-baseline evals/baselines/latest-agent.json
```

## Dependencies

- **Internal**: `core/agent_v2.py`, `core/session_runtime.py`, `config/settings.py`
- **External**: `langchain_openai`, `pyyaml`

Unit tests for the harness live in `tests/test_core/test_evals_runner.py` and `tests/test_prompt_registry.py`. Full eval runs require API credentials on a local machine; they are not executed on GitHub Actions.
## A10: Per-Model Comparison Matrix (2026-08-06)

`--models <id1,id2,...>` runs a full 17/19-task suite per model and saves per-model baselines; `--models-report <DATE>` regenerates the comparison matrix from existing baselines without re-running (see PHASE-A §A10).

### Results (agent backend, full suite, official/zen/ark gateways)

| Model | Channel | Pass rate | Notes |
|---|---|---|---|
| zen/deepseek-v4-flash | zen | **17/17 (100%)** | default model; strongest on this suite |
| deepseek/deepseek-v4-pro | official | 16/17 (94%) | failed feature-multi-file-cache |
| ark/glm-5.2 | ark | 17/19 (89%) | failed feature-cli-parser + websearch-summary |
| zen/gpt-5.6-luna | zen | 15/17 (88%) | readcode x2 (17-task suite; websearch tasks not covered) |
| ark/minimax-m3 | ark | 15/19 (79%) | readcode (2) + refactor-extract-function + websearch-summary |
| zen/kimi-k2.7-code | zen | 13/19 (68%) | readcode x4 + websearch x2 |
| **ark/doubao-seed-2.1-turbo** | ark | 16/19 (84%) | new DoubaoProvider (A23); failed feature-multi-file-cache + websearch x2 |
| opencode-go/mimo-v2.5 | go | 12/19 (63%) | rerun via GO gateway (replaces the quota-invalid zen free column) |
| ~~zen/mimo-v2.5-free~~ | zen (free) | ~~2/17 (12%)~~ | **invalid: zen free-tier quota exhausted (HTTP 429); replaced by the opencode-go/mimo-v2.5 rerun** |

Suite size note: batches 1-2 ran the 17-task suite; batches 3-4 ran 19 tasks after two websearch tasks were added to `evals/tasks/` mid-run (committed later in 30cec28, 2026-08-06 12:33; batches 1-2 predate them). `websearch-summary` failed on every model; `websearch-save-report` passed on ark models only — both are new tasks (added mid-run), treated as FAIL where not covered (missing tasks are scored FAIL in the matrix).

Follow-up directions (per model):
- doubao-seed-2.1-turbo (84%): first run under the new A23 DoubaoProvider (supports_reasoning/FC declared from live probe); feature-multi-file-cache + websearch gaps; tokenizer estimation (chars:2.0) to revisit when a doubao tokenizer is available.
- mimo-v2.5 via GO (63%): valid data vs the quota-invalid zen free run; websearch tasks drag it down.
- kimi-k2.7-code (68%): readcode identifier-citation + websearch tasks underperform — prompt-variant mechanism (A9) is the vehicle once real variants exist.
- minimax-m3 (79%): readcode + extract-function flake; re-run for confirmation.
- luna (88%): cheap and competitive; readcode gaps point at the same identifier-citation issue.
- websearch tasks: investigate task quality/tool wiring before including in the canonical suite.

验收记录留在本地开发笔记中（`docs/plans/` 不入库）。

Raw evidence (per-model baselines + matrix md) is intentionally **not tracked** (gitignore policy 5c6c84a: date-stamped per-model runs are run artifacts); data lives locally under `evals/baselines/2026-08-06-agent-*.json` and `evals/baselines/models-comparison-2026-08-06.md`. Public-benchmark context (Artificial Analysis / Arena Intelligence, 2026-08): Kimi K3 is the top open-weights model (AA index 57) and GLM-5.2 second (51); qwen3.8-max leads the Arena text chart; consistent with the measured ordering where coverage overlaps.
