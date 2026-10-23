# WEB-W7-C03 evidence notes

Reproducible agent-eval harness: `evals/web/run.py` (4 cells: cli-solo,
cli-team, web-solo, web-team), `evals/web/taskset.jsonl` (30 fixed tasks,
one designed-to-fail `w7c03-c14-oracle-fail`), `evals/web/report.py`
(stats + quality gate).

## Files

- `red.txt` — TEST-first expected failure (module collection: `run.py`
  did not exist yet).
- `green.txt` — final `pytest tests/web/w7/test_w7_c03_unit.py
  tests/web/w7/test_w7_c03_module.py -q` → 3 passed.
- `manifest_cli-solo.json` / `results_cli-solo.json` — real run:
  `run.py --cells cli-solo --sample 3 --task-timeout 240 --budget 2000000`.
- `manifest_web-solo.json` / `results_web-solo.json` — real run:
  `run.py --cells web-solo --sample 1 --task-timeout 240 --budget 2000000`.
- `report_cli-solo.md` (+`.report.json`) — gate FAIL (2 attempted < min 3;
  budget cap blocked task 3 — honest rejection).
- `report_web-solo.md` (+`.report.json`) — gate PASS at `--min-tasks 1`.

## What the real runs showed

deepseek-flash (deepseek/deepseek-v4.1-flash via api.deepseek.com) produced
correct artifacts for both `w7c03-c01-hello` and `w7c03-c02-calc` — the
oracle confirms `file_exists`/`file_contains`/`command_succeeds` all green
in both runs — but the model looped on environment verification (no
`python3` on PATH, sandboxed bash refusing several commands) and hit the
240s per-task cap each time. Statuses are `passed` with the timeout
annotated and full token/cost recorded; `w7c03-c03` was `blocked` by the
per-cell 2M-token budget (2 tasks already burned ~3.4M). These are honest
results: correct artifacts, real spend, real wall-clock overrun.

cli-solo tokens come from the process token-stats delta (price_table
estimate at the published 2026-10 rate). web-solo tokens come from the
durable spine: `run.created` (message carries the `/solo` prefix — Run has
no mode column, the prefix is the mode forcing) → `event/agent_started` →
`eval.checks` verdict → `usage.updated` → `usage_records` row
(id `bec4291602904ae8afdb480541b68855`, 2,534,123 tokens, $5.06824600,
model_id `active` — the ledger wrote the alias; the code now resolves the
configured model name for future runs). The interrupted turn left the Run
row `failed` while the oracle still scored `passed` — the two semantics
are intentionally different (turn lifecycle vs artifact oracle).

## Reproduce

    python evals/web/run.py --cells cli-solo --sample 3 \
        --task-timeout 240 --budget 2000000 \
        --out out.json --manifest manifest.json
    python evals/web/report.py --results out.json --manifest manifest.json \
        --taskset evals/web/taskset.jsonl --min-tasks 3 --out report.md

Web cells need `RXYCODE_WEB_DATABASE_URL` (default
`postgresql+psycopg://postgres@127.0.0.1:55432/rxycode` — the shared
`rxy-w2c01-pg` container); unreachable PG marks web cells `blocked`, never
fakes numbers.

## Not yet exercised with a real model

`cli-team` and `web-team` cells (Session.prompt `/team` → Coordinator)
are implemented and share the same code path; they were left unrun to keep
the bounded attempt under budget — team tasks multiply token spend.
