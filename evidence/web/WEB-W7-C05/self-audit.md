# WEB-W7-C05 self-audit / manual review

Audited commit: `<filled after the audited fix commit>`
Final verdict: `<filled by the Codex audit>` (session
`01a140a7-2cc1-7f61-bdab-2af627f08e80`, `gpt-6.1-sol` `high`).

## Audit history

| round | verdict | findings fixed |
|---|---|---|
| r1 | PROBLEMS | 8: no deployed queue consumer (idle stdio worker); api bypassed `serve()` mode guard; upgrade/rollback ran stale `repo-src`; CI lint failed on 3 committed files; rate limiting was text-only; validator accepted wildcard port publication; `compose up` outside try/finally skipped cleanup; NOTES/.gitignore scope disagreement |
| r2 | `<pending>` | — |

## Scope rulings committed to the nested plan

1. r1 remediation (nested `c7621e7`): `rxycode_worker/drain.py`+`__main__.py`
   (real queue consumer), `rxycode_server/main.py` `rate_limit_rpm` +
   `serve()` boot path, `api/ratelimit.py` middleware, `.gitignore`
   `!docs/deploy/` negation, three lint fixes, port validator + CI port
   invariant, runbook versioned reseed sequence.

## What the remediation actually does (verified by hand)

- Drain end-to-end on host against dev PG (55432): create_run -> claim ->
  `worker.lease` event -> `event/agent_started` journaled -> real
  `Session.prompt` turn -> `notify.event/*` -> `event/agent_done` ->
  `usage.updated` -> `commit_terminal` (`succeeded` with the configured
  model; `failed` honestly without provider creds). Observed live.
- Same drain inside a real compose worker container (debug stack w7c05dbg):
  claim -> `worker.lease` -> `event/agent_started` -> provider call fails at
  the real network boundary -> `run.error` -> `failed`. Three real bugs were
  caught and fixed during this verification: (a) `AgentV2()` needs a
  configured model — worker now accepts `RXYCODE_LLM_BASE_URL`/`_MODEL`/
  `RXYCODE_API_KEY` and writes a real model entry when set; (b) the LLM
  client enforces https-with-credential except loopback — test uses
  `http://127.0.0.1:9/v1` (dead port => honest connection failure, no stub
  LLM); (c) a shell `${VAR}` inside the worker's `sh -c` script is
  interpolated by COMPOSE from the host env at `up` time (the test's
  RXYCODE_DATA_DIR temp path was baked into the container script) — the
  model-config write moved inside a python heredoc that reads the real
  container env.
- `serve(mode="local", host="0.0.0.0")` raises RuntimeError — the deployed
  api can never weaken mode; verified by the negative test against the real
  module, not a copy.
- Rate limiter driven at ASGI level: 2 allowed, 3rd -> 429 + Retry-After.
- Port validator: `8000:8000` (no host_ip) refused; `127.0.0.1:...` accepted;
  same check duplicated in the CI invariants lane.
- Module test: the run is claimed and terminated by the worker INSIDE the
  container (`lease_owner = drain-<container>-<pid>`), not the test process;
  stale-lease reclaim uses a planted expired-lease row while the worker is
  SIGKILLed (deterministic, no race); worker recreation + third run prove
  restart recovery.

## Known limitations (accepted, documented)

- Rate-limit window is per-process memory — single-replica demo only.
- Approval-gated runs (profiles outside the mode map -> `confirm_all`
  default) emit approval requests nobody can answer in the drain — they fail
  at `RXYCODE_WORKER_RUN_TIMEOUT` rather than hang. The approval-resume
  service is not part of this stack.
- `child.cancel` persisted commands get "no manager" — the drain is
  single-agent; undeliverable commands are logged, not dropped silently.
- Workspaces live under the `worker-data` volume (`/work/runs`) — survive
  container restart, die with `down -v` (documented).
- Browser E2E BLOCKED: no Playwright dep in apps/web; never claimed.
