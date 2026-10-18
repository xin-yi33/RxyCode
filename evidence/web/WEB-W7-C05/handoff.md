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
- `packages/rxycode-server/src/rxycode_server/api/ratelimit.py` +
  `main.py` — per-client-IP fixed-window ASGI limiter (429+Retry-After),
  installed when `RXYCODE_WEB_RATE_LIMIT_RPM>0` (compose default 240).
- api boots through `rxycode_server.main.serve()` — `mode=local` on a
  non-loopback bind is refused in the deployed container too.
- `.github/workflows/web-ci.yml` — ruff / web contract pytest / apps-web
  typecheck+build / compose render + deploy invariants (incl. loopback port
  publication).
- `docs/deploy/web-runbook.md` — bring-up, seed, migrations, certs, logs,
  VERSIONED upgrade/reseed sequence, rollback, boundaries.
- `tests/web/w7/test_w7_c05_unit.py` / `test_w7_c05_module.py` — contract +
  negative + restart-durability; the module test asserts the DEPLOYED worker
  container drains a queued run (`worker.lease` + `event/agent_started` +
  `usage.updated` events), a planted stale lease is reclaimed at epoch+1, and
  a SIGKILLed+recreated worker claims a new run again.

## Evidence

`red.txt` (pre-implementation failures), `green.txt` (post-fix full suite +
docker legs), `NOTES.md` (topology, deviations, honest labels).

## Status

- 3/3 focused tests green on Docker Engine 29.7.2.
- ruff clean on all touched files; `docker compose config --quiet` OK;
  `git diff --check` clean on the card scope.
- Browser E2E: BLOCKED (no Playwright dep in apps/web) — labeled, not claimed.
- Provider-backed run success leg: exercised on host (real Session.prompt
  turn → `succeeded`, usage.updated); in the compose test project runs end
  `failed` honestly (no provider creds).
