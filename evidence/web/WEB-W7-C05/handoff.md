# WEB-W7-C05 handoff — Compose/CI/CD、迁移、发行与 HTTPS Demo

Audited commit: `<filled after the audited fix commit>`
Audit: Codex session `01a140a7-2cc1-7f61-bdab-2af627f08e80`, model `gpt-6.1-sol`,
reasoning `high`.

## What shipped

- `infra/compose/compose.yaml` — 9-service stack (postgres, redis, minio,
  reposync, migrate, api, worker, webbuild, gateway); tar-seeded `repo-src`
  volume + marker ordering because this Docker Desktop cannot mount Windows
  bind paths; every published port binds loopback explicitly.
- `infra/compose/Caddyfile` — HTTPS gateway (internal CA), security headers,
  `/api/*` proxy incl. SSE+WS, SPA static, preview-auth seam.
- `packages/rxycode-worker/src/rxycode_worker/drain.py` + `__main__.py` — the
  real queue consumer the audit found missing: polls `runs`, fenced `claim`,
  `load_run` reads back the persisted message, drives ONE real turn through
  `AgentRuntime -> Session.prompt` with `remember_web_run` bound (journaled
  agent_started/agent_done + telemetry spans land on the run's event log),
  renews the lease and honors `cancel_requested` mid-turn, delivers persisted
  `steer.accepted` commands into the turn, writes `record_terminal_usage` and
  `commit_terminal` (or `confirm_cancel`). Failed/provider-less runs end
  `failed` — never fabricated.
  - Enforces the persisted `target_id`: only `local:*` runs execute inside
    the shared container; `sandbox:`/cloud/empty targets fail closed
    (`_UnsupportedTarget` → `run.error` → `failed`, no `agent_started`).
  - Lease watchdog: transient renewal errors retry; renewals broken past the
    TTL cancel the turn and raise `_LeaseRenewalLost` (the row is left for a
    healthy claimant — no terminal write on a lease it cannot prove).
  - `event/*` notifications land as `notify.*` audit rows AND structured
    reducer projections (`assistant.final`/`assistant.delta`/`tool.*`/
    `plan.updated`/`todo.updated`/`question.requested`/`approval.requested`).
  - Real token delta is metered in `_target`'s `finally` — failed and
    cancelled turns write the ledger too; a ledger write failure forces the
    commit to `failed` (a `succeeded` can never stand on a missing usage
    row), and on the cancel path it is journaled as `run.error` first.
- `packages/rxycode-server/src/rxycode_server/api/ratelimit.py` +
  `main.py` — per-client-IP fixed-window ASGI limiter (429+Retry-After),
  installed when `RXYCODE_WEB_RATE_LIMIT_RPM>0` (compose default 240).
- api boots through `rxycode_server.main.serve()` — `mode=local` on a
  non-loopback bind is refused in the deployed container too.
- `.github/workflows/web-ci.yml` — ruff / web contract pytest / apps-web
  typecheck+build / compose render + deploy invariants (incl. loopback port
  publication).
- `docs/deploy/web-runbook.md` — bring-up, seed, migrations, certs, logs,
  EXACT-reseed upgrade/rollback sequence (the `repo-src` volume is emptied
  before the tar stream — deleted files and stale alembic revisions cannot
  survive; `.rxy-sync-done` stamps the new commit hash), boundaries.
- `tests/web/w7/test_w7_c05_unit.py` / `test_w7_c05_module.py` — contract +
  negative (incl. a literal `RXYCODE_API_KEY` refusal) + drain-internal unit
  legs (watchdog outage semantics, reducer projection vocabulary) +
  restart-durability; the module test asserts the DEPLOYED worker container
  drains a queued run (`worker.lease` + `event/agent_started` +
  `usage.updated` events), a planted stale lease is reclaimed at epoch+1,
  a SIGKILLed+recreated worker claims a new run again, and a `sandbox:`
  target fails closed without ever spawning the local agent.

## Evidence

`red.txt` (pre-implementation failures), `green.txt` (post-fix full suite +
docker legs), `NOTES.md` (topology, deviations, honest labels).

## Status

- Focused tests green on Docker Engine 29.7.2 (contract + negative +
  watchdog/projection unit legs + the real docker module leg).
- ruff clean on all touched files; `docker compose config --quiet` OK;
  `git diff --check` clean on the card scope.
- Browser E2E: BLOCKED (no Playwright dep in apps/web) — labeled, not claimed.
- Provider-backed run success leg: exercised on host (real Session.prompt
  turn → `succeeded`, usage.updated); in the compose test project runs end
  `failed` honestly (no provider creds).
