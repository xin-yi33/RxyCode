# WEB-W7-C03 handoff — 可复现 Agent Eval 和基线对照

## Scope delivered

| File | Role |
|---|---|
| `evals/web/taskset.jsonl` | 30 fixed tasks (14 coding incl. designed-fail `w7c03-c14-oracle-fail`, 6 browser, 6 recovery, 4 remote); oracle checks reuse `evals` CHECK_TYPES; each task pins `source_commit`; sha256 of the normalized file pins the set |
| `evals/web/run.py` | standalone runner, 4 cells (cli-solo/cli-team via real AgentBackend+AgentV2; web-solo/web-team via durable spine: create_run→claim→Session.prompt in journaled AgentRuntime→eval.checks→record_terminal_usage→commit_terminal→replay); enforced per-cell token budget (`_await_budgeted` cancels in-flight on crossing; `budget_tokens` derived from remaining); fresh workdir per (cell,task); manifest pins taskset hash, model, provider, price_version, code_commit, `executed_sources` sha256 + bounded `evals_web_diff` when dirty |
| `evals/web/report.py` | per-cell+overall n/success(failures in denominator, blocked excluded AND reported)/p50/p95/tokens/Decimal cost, abnormal-cost surfacing, `gate_report()` strict gate |
| tests | `test_w7_c03_contract` (manifest reproducibility), `test_w7_c03_negative` (gate rejects demo-only/unknown-id/empty-reason/empty-records/duplicates/undeclared cells), `test_w7_c03_integration` + 5 more (real PG: failure in denominator, abnormal cost surfaced, budget mid-run cancel, ledger-read fault, usage-write failure, oracle-crash finalization) |

## Audit findings fixed (4 rounds)

- R1 P1: gate accepted demo-only/empty reports → strict taskset provenance (distinct-task coverage, unknown ids, non-empty blocked reasons, empty results).
- R1 P1: token budget unenforced (CLI burned 3.38M vs declared 2M) → `_await_budgeted` mid-flight cancel + derived `budget_tokens`; overrun bound documented in manifest.
- R1 P2: workdir reuse let stale artifacts pass oracles → rmtree before setup.
- R1 P2: provider failures discarded consumed spend → blocked records persist usage; report counts blocked spend in totals.
- R1 P2: spine write failures left passing results → spine_errors flip status to error, oracle_status preserved.
- R1 P2: manifest pinned only HEAD+dirty → `executed_sources` sha256 + bounded diff.
- R2 P1: manifest-declared cells could silently drop → bidirectional reconciliation.
- R2 P1: duplicate (cell,task_id) rows inflated success → gate rejects; stats de-dupe, spend still sums.
- R2 P2: ledger-read exception aborted the matrix → contained into spine_errors; per-task catch-all keeps the matrix alive.
- R2 P2: usage-write failure lost cost → `estimate/ledger_failed` fallback on all web cost paths.
- R3 P1: per-record cell not validated (phantom web-team rows) → per-record provenance check; undeclared cells flagged in report.
- R3 P2: catch-all erased crash spend → spend_sink + token_stats delta recover tokens; charged to cell budget.
- R3 P2: `_setup_workdir` outside containment → moved inside; prep failure = task error record, matrix continues.
- R4 P2: oracle crash orphaned the leased web run → `_finalize_orphaned_web_run` keeps run identity, attempts usage write + fenced terminal commit, errors → spine_errors.

## Results

- red.txt: TEST-first collection failure recorded. green.txt: full command log — unit+module 16 passed; chaos suite regression 1 passed; ruff clean.
- Real evidence (`evidence/web/WEB-W7-C03/`): `results_cli-solo.json` (sample-3 real deepseek run: 2 passed-with-timeout + 1 budget-blocked) and `results_web-solo.json` (sample-1 real durable-spine run: oracle passed, usage_records row 2,534,123 tokens / $5.06824600, run_id `6c5cde6f`). `report_cli-solo` gate FAIL on sample size (honest), `report_web-solo` gate PASS at min-tasks 1. NOTES.md documents reproduce commands and the `model_id=active` ledger wart.

## Risk acceptance / open items

- E2E-EVAL-01 full 5-task × all-cells trace matrix: partially exercised — real model+tools ran on 2 cells (cli-solo sample 3, web-solo sample 1); `cli-team`/`web-team` implemented but deliberately not real-run to bound token spend (they share the same code path). Labeled honestly in NOTES.md, not claimed complete.
- Historical sample manifests legitimately FAIL the strict gate now (missing coverage) — they were samples, not full-suite evidence; documented.
- `Run` rows carry no mode column; solo/team forcing via `/solo`/`/team` prefixes, recorded in manifest `mode_map`.

## Audit verdict

- gpt-6.1-sol high, Codex session 01a140a7-2cc1-7f61-bdab-2af627f08e80, audited parent commit 1944203497016e010b8a8ab8d2bd63887b628f1d → VERDICT: NO_REMAINING_PROBLEMS (w7c03-audit-5.json).
- Rounds 1-4 returned PROBLEMS; fixes are commits 795ad2d9, 439946ab, 64dd4a9b, 19442034.
- PG-backed tests ran implementer-side; auditor reviewed code/assertions (read-only env).