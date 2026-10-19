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
  real queue consumer the audit found missing, now two-process: the drain
  polls `runs`, fences the `claim`, enforces the placement gate, then spawns
  the turn as a CONFINED child (`python -m rxycode_worker.drain` re-entered
  with `RXYCODE_TURN_RUN_ID`). Inside the boundary the child binds
  `remember_web_run`, a real `ProtocolTui` + `bind_prompt_context` with the
  persisted `RunContext` (the audit-r3-required production producer for
  tool/stream events), `bind_worker_todo_sink`, the steer shim, and drives
  ONE real turn through `AgentRuntime -> Session.prompt`. The parent renews
  the lease with deadline-bounded probes, honors `cancel_requested` (SIGKILL
  to the bwrap supervisor reaps the whole tree), reads back
  `.turn-result.json`, then writes `record_terminal_usage` and
  `commit_terminal` (or `confirm_cancel`). Failed/provider-less runs end
  `failed` — never fabricated.
  - Public placement rule (`_execution_gate`, `RXYCODE_WORKER_EXECUTION`):
    shipped `cloud-only` accepts ONLY `cloud:{tenant}:{workspace}` targets
    whose tenant segment equals the run's own tenant, and refuses
    `full`/`full_auto` profiles, `local:*`, `sandbox:*` and empty targets —
    `run.error` → `failed`, no `agent_started`, nothing on the host.
  - The boundary is real: `rxycode_runner.sandbox.userns` (bwrap userns +
    pidns/ipc/uts + minimal ro root + rw per-tenant workspace + `--clearenv`
    passlist + `--die-with-parent`); `userns_available()` is a live probe —
    unavailable means `IsolationUnavailable` → `failed`, never a host
    fallback. Worker's `seccomp=unconfined` is scoped to that one service
    (validator enforces), no capabilities, no privileged, no docker.sock.
  - Lease watchdog: every store call is `wait_for`-bounded; a monotonic
    deadline extends only on a proven renewal — renewals unproven past the
    TTL cancel the turn and raise `_LeaseRenewalLost` (no terminal write on
    a lease it cannot prove).
  - `event/*` notifications land as `notify.*` audit rows AND structured
    reducer projections (`assistant.final`/`assistant.delta`/`tool.*`/
    `plan.updated`/`todo.updated`/`question.requested`/`approval.requested`);
    `assistant.final` is exempt from the intermediate-event cap so the
    answer is never dropped.
  - Real token delta is metered in the confined turn's `finally` and
    reported via `.turn-result.json` — failed and cancelled turns write the
    ledger too; a ledger write failure forces the commit to `failed` (a
    `succeeded` can never stand on a missing usage row), and on the cancel
    path it is journaled as `run.error` first.
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
  negative (incl. a literal `RXYCODE_API_KEY` refusal, `cap_add`/
  non-worker `security_opt` refusals) + drain-internal unit legs (watchdog
  outage semantics, reducer projection vocabulary, execution-gate matrix,
  sandbox argv shape, terminal-projection cap bypass) + restart-durability;
  the module test asserts the DEPLOYED worker container drains a queued
  tenant-bound `cloud:*` run INSIDE the per-run sandbox (`worker.lease` +
  `event/agent_started` + `usage.updated` events), a planted stale lease is
  reclaimed at epoch+1, a SIGKILLed+recreated worker claims a new run again,
  and `local:*` + `sandbox:` targets both fail closed without spawning.

## Evidence

`red.txt` (pre-implementation failures), `green.txt` (post-fix full suite +
docker legs), `NOTES.md` (topology, deviations, honest labels).

## Status

- Focused tests green on Docker Engine 29.7.2 (contract + negative +
  watchdog/projection unit legs + the real docker module leg).
- ruff clean on all touched files; `docker compose config --quiet` OK;
  `git diff --check` clean on the card scope.
- Browser E2E: BLOCKED (no Playwright dep in apps/web) — labeled, not claimed.
- Provider-backed run-success leg: the pre-sandbox in-process drain reached
  `succeeded` on host with a real provider; under the current sandboxed
  drain this Windows host refuses (no userns) and the compose test project
  ends `failed` honestly at the network boundary (no provider creds). A
  real `RXYCODE_LLM_BASE_URL`+key on the shipped stack runs the same
  confined path to completion — needs credentials, labeled not claimed.
- Live-debug boundary fixes: probe loader binds (`/lib*`), `/usr/local`
  interpreter mount, `ro_binds` union semantics — all found by running the
  shipped container, all fixed in `userns.py`.
- **Audit r4 remediation** (this commit): claim-anchored lease deadline that
  cancels the turn at expiry even with a stalling store probe; child config
  moved to a parent-owned dir outside the writable workspace (symlink-safe);
  `.turn-result.json` bound to run_id + requires `rc==0` for success;
  cumulative `usage.delta` heartbeats recover spend for SIGKILLed turns;
  bwrap mounts private `/tmp` before the workspace bind (default workspace
  root unbroken). Unit file now 11 legs incl. the audit's probe shape.

## What the next auditor should probe

- Lease expiry while a status/renewal call stalls past the deadline.
- A prior success report left in a reused workspace + a child exiting 37.
- Cancel/timeout mid-provider-call: usage must still land (usage.delta).
- Default workspace root `/tmp/rxycode-runs` under bwrap (no compose
  override) — the /tmp shadowing regression is unit-covered.
