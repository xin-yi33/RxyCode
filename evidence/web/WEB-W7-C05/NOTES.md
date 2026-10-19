# WEB-W7-C05 handoff notes

## What shipped

| File | Role |
|------|------|
| `infra/compose/compose.yaml` | 9-service stack: postgres, redis, minio, reposync, migrate, api, worker, webbuild, gateway |
| `infra/compose/Caddyfile` | HTTPS gateway (internal CA), security headers, `/api/*` reverse proxy (SSE+WS), SPA static + preview-auth seam |
| `.github/workflows/web-ci.yml` | 4 lanes: ruff, pytest web contract subset (with real docker), apps/web typecheck+build, compose config + deploy invariants |
| `docs/deploy/web-runbook.md` | bring-up/seed/migrations/certs/logs/upgrade/rollback/boundaries — commands verified on this checkout |
| `packages/rxycode-worker/src/rxycode_worker/drain.py` | the deployed queue consumer: claim -> placement gate -> confined turn (spawned via the userns provider) -> usage ledger -> terminal commit; the same file re-enters in turn mode (`RXYCODE_TURN_RUN_ID`) inside the sandbox |
| `packages/rxycode-runner/src/rxycode_runner/sandbox/userns.py` | the per-run kernel boundary: bwrap userns/pidns/ipc/uts + minimal ro root + rw workspace + env passlist; `UsernsSandboxProvider` implements the `SandboxProvider` contract; `userns_available()` is a real probe and fails closed |
| `packages/rxycode-worker/src/rxycode_worker/__main__.py` | `python -m rxycode_worker` entry to the drain |
| `packages/rxycode-server/src/rxycode_server/api/ratelimit.py` | per-client-IP fixed-window ASGI limiter (429 + Retry-After) |
| `packages/rxycode-server/src/rxycode_server/main.py` | `create_app(..., rate_limit_rpm=)` wires the limiter; `serve()` is the guarded boot path |
| `tests/web/w7/test_w7_c05_unit.py` | contract (real compose up + HTTPS + alembic head) + negative (validator refuses unsafe overlays incl. wildcard ports, literal `RXYCODE_API_KEY`, local-mode public bind, limiter 429 drive) + drain internals (lease-watchdog outage semantics, reducer projection vocabulary) |
| `tests/web/w7/test_w7_c05_module.py` | deployed-worker drains a queued run inside the container; restart durability; deterministic stale-lease reclaim; worker-container SIGKILL + recreate recovery; `sandbox:` target fails closed without spawning |

## Topology decisions worth knowing

- **The worker service is `python -m rxycode_worker.drain`** — a real durable
  consumer, not an idle stdio appserver. It polls `runs` for claimable rows
  (`pending`, or a dead worker's expired lease), takes the fenced lease via
  `supervisor.claim`, and spawns the turn INSIDE a per-run kernel sandbox —
  journaled `event/agent_started`/`event/agent_done`, telemetry spans and the
  `usage.updated` ledger row all land on the run's own event log from inside
  the boundary.
  - **Public rule in code (`_execution_gate` + `RXYCODE_WORKER_EXECUTION`)**:
    the shipped `cloud-only` mode executes ONLY `cloud:{tenant}:{workspace}`
    targets — the tenant segment must equal the run's `tenant_id`
    (cross-tenant refused) — and refuses `local:*`/`sandbox:*`/empty
    placements AND `full`/`full_auto` profiles (Full means unsandboxed host
    authority, which does not exist on the public worker). `sandboxed-local`
    is the dev-host opt-in: `local:*` runs are accepted but STILL confined.
    Refusals commit `failed` with an honest `run.error` and never spawn —
    no `event/agent_started` (module test asserts both legs).
  - **The boundary is real**: `rxycode_runner.sandbox.userns` wraps the whole
    turn process in bubblewrap — `--unshare-user --uid 0 --gid 0
    --unshare-pid --unshare-ipc --unshare-uts`, `--clearenv` + explicit
    setenv passlist, system paths + checkout read-only, only
    `workspaces/<tenant>/<session>` writable, `--die-with-parent` tree reaping
    on kill. `userns_available()` does a live probe; unavailable means the
    run fails closed (`IsolationUnavailable`), never a host-subprocess
    fallback. `security_opt: seccomp=unconfined` is scoped to the worker
    only — Docker's default profile forbids `unshare`/`mount`; the validator
    refuses it on every other service and refuses `cap_add` everywhere.
  - **Boundary construction bugs found by live debugging** (all fixed):
    the probe originally bound only `/usr` — a dynamically linked `true`
    also needs `/lib*` (the ELF loader) so the probe failed closed while
    the real boundary would have worked; the probe now uses the same
    `_DEFAULT_RO_BINDS` the turn gets. `_DEFAULT_RO_BINDS` was missing
    `/usr/local` — the Debian-slim interpreter lives there, so the first
    confined spawn hit `execvp python: ENOENT`. And the drain's `ro_binds`
    argument originally *replaced* the system mounts instead of adding to
    them — `build_sandbox_argv` now unions defaults+caller binds so a
    caller can never drop the interpreter's own mount. Verified in the
    real stack: `worker.lease -> event/agent_started -> six real provider
    retries -> run.timeout -> failed`, and `/proc` shows zero leftover
    turn processes after the kill.
  - **The production producer is wired (audit r3-F3)**: the turn child calls
    `install_tui_context_hook()`, builds a real `ProtocolTui` +
    `RunContext` from the persisted identity (tenant/project/actor/trace)
    and binds them via `bind_prompt_context`, plus `bind_worker_todo_sink` —
    the same calls an appserver session worker makes.
  - **Terminal answer survives floods (audit r3-F4)**: `_RunEmit` caps
    intermediate projections at `_JOURNAL_CAP` but `assistant.final` is
    exempt and always persisted.
  - **Lease watchdog is deadline-bounded (audit r3-F2)**: every renewal and
    status probe runs under `asyncio.wait_for(_LEASE_IO_BUDGET)`; a
    monotonic deadline extends only on a *proven* renewal. Renewals unproven
    past the TTL cancel the turn and raise `_LeaseRenewalLost` — the worker
    never executes past a lease it cannot prove.
  - **Structured UI projections**: every `event/*` notification still lands
    as a `notify.*` audit row, and `_projection_rows` additionally writes
    reducer-vocabulary events — `assistant.final` (text + token fields),
    `assistant.delta`, `tool.completed`/`tool.failed` (call_id + tool),
    `plan.updated`/`todo.updated` (incl. the V17 snapshot envelope), and
    `question.requested` + `approval.requested` for `event/agent_needs_input`.
  - **Metering survives failure and is terminal-checked**: the real token
    delta is captured inside the confined turn's `finally` and reported via
    `.turn-result.json` so failed AND cancelled turns still write the
    ledger — a cancel never returns before `record_terminal_usage`. A ledger
    write failure is itself a durable-write failure: it appends to
    `run.error` and forces the commit to `failed`.
  - Persisted `steer.accepted` commands reach the turn through a bound
    `_DrainWorkerShim` + `consume_persisted_commands` inside the sandbox;
    `child.cancel` gets an honest "no manager" (the drain is single-agent).
    The DB URL reaching the turn is scoped inside the boundary — the
    residual is documented in the runbook.
- **The worker's model comes from `RXYCODE_LLM_BASE_URL`/`_MODEL`/`RXYCODE_API_KEY`**
  — when the base URL is set, worker startup writes a real openai-compatible
  model entry into `RXYCODE_DATA_DIR/config.yaml` (the key stays an
  `api_key_env` reference, never on disk). With a configured model the turn
  genuinely starts — `event/agent_started` was observed inside the container
  — and the provider call then succeeds or fails honestly at the network
  boundary. With NO endpoint configured `AgentV2()` raises the real
  "No model configured" ValueError and the run commits `failed` — never
  fabricated `succeeded`.
- **Docker Desktop can't mount Windows host paths here** (verified: any
  host-path bind hangs container start). Instead of bind-mounting the
  checkout, `reposync` + a tar stream seed the `repo-src` volume; a
  `.rxy-sync-done` marker gates everyone. `migrate` then drops
  `.migrate-done` into `boot-state`; `gateway` waits for `index.html` in
  `web-dist`. This replaced an earlier `service_completed_successfully`
  design that deadlocked `up -d` (seed happens after up returns).
- **api boots through `rxycode_server.main.serve()`** — `mode="local"` on a
  non-loopback bind is refused by `reject_as_public_web_gateway`, so a stray
  `RXYCODE_WEB_MODE=local` cannot weaken the deployed stack. The app builds
  via `create_app`, which also installs `RateLimitMiddleware` when
  `RXYCODE_WEB_RATE_LIMIT_RPM > 0` (default 240 in compose): the public-demo
  throttle lives at the app layer because stock `caddy:2` ships no limiter
  plugin. `uvicorn proxy_headers=True` maps the gateway's X-Forwarded-For
  into the client key.
- **Upgrade/rollback reseeds EXACTLY, not just overlays**: `up -d` alone
  leaves `repo-src` stale, and a plain `tar -xf -` overlay keeps files the
  new revision deleted (stale modules, stale alembic revisions). The
  runbook sequence clears `.migrate-done`, **empties the `repo-src` volume**
  (`find /repo -mindepth 1 -delete`), re-streams the tar, stamps
  `.rxy-sync-done` with the new commit hash, drops the stale `index.html`,
  re-runs migrate + webbuild, then force-recreates api/worker/gateway — the
  seeded tree is an exact copy of the selected checkout.
- **MinIO is `bitnamilegacy/minio:2025.7.23`** — minio/minio release tags
  were pulled from Docker Hub in 2025; the bitnamilegacy tag keeps the
  `MINIO_ROOT_*` env contract. The image runs as uid 1001; the volume MUST
  mount at `/bitnami/minio/data` (mounting `/data` fails with permission
  errors — that was the first bug hit).
- **Caddy `tls internal`** issues a `localhost` leaf from its internal CA
  (persisted in `caddy-data` vol). The contract test proves both directions:
  default trust store refuses, relaxed verification serves. The
  preview-auth seam is an env-templated CEL expression
  (`@preview_denied`) — when `RXYCODE_PREVIEW_TOKEN` is empty it collapses
  to pass-through; non-empty requires `X-Preview-Token` header match.
- **Ports/secrets**: every published port names a loopback `host_ip`
  explicitly — the validator and the CI invariant both refuse a bare
  `8000:8000` (that means 0.0.0.0). Secrets use `${VAR}` interpolation —
  zero literals, and the validator/CI pattern now also covers
  `api_key`/`credential` names so a literal `RXYCODE_API_KEY: sk-...` is
  refused (negative test proves it). Tests use per-test project names +
  free ports so the rxy-w2c* dev containers are never touched.

## Deviations / honest labels

- `docs/deploy/web-runbook.md` IS tracked: `.gitignore` keeps a broad
  `docs/*` ignore with an explicit `!docs/deploy/`/`!docs/deploy/**`
  negation (same pattern `docs/product/` used in W6-C06). Verified with
  `git check-ignore` — the file appears in `git status` as modified.
- Frontend install inside `webbuild` uses `npm install` (repo has
  `bun.lock`, no `package-lock.json`, so `npm ci` cannot run). Documented
  in both the workflow comment and runbook.
- The rate-limit window is per-process memory — honest for the
  single-replica demo; a multi-replica deployment would need the limiter
  moved to the gateway or a shared store.
- `run.permission_profile` maps to `Session.prompt(permission_mode=)` only
  for real vocabulary (`full_auto`/`full`/`auto_edit`/`confirm_all`);
  anything else falls back to the configured default (`confirm_all`).
  Approval-gated tools then hit "no approval broker" inside the confined
  turn (no stdin client, no durable approval service on this stack) — the
  tool call is refused honestly rather than blocking forever. The
  in-process approval-answer channel (`interrupt_resume`/`pause_for_approval`)
  is invoked by the caller that owns the lease; a resume service is not part
  of this stack.
- **Network inside the sandbox is inherited** (the turn must reach Postgres
  for journaling/steer delivery and the configured LLM endpoint). The
  boundary confines filesystem/process/credentials surface, not egress —
  per-run egress policy is the `rxycode_runner.sandbox.egress` seam, not yet
  wired here; documented in the runbook.
- The turn child receives `RXYCODE_WEB_DATABASE_URL` inside the sandbox —
  run code with the DSN could write run-events directly. That residual is
  accepted for this stack (journal delivery needs it; an out-of-process
  journal broker is future work) and recorded in the runbook.
- E2E-DEPLOY-01 run leg: the deployed drain worker really claims and
  executes queued runs inside the userns sandbox — the module test asserts
  `worker.lease` + `event/agent_started` + `usage.updated` inside the
  container, where the configured model points at a loopback dead port so
  the provider call fails honestly at the network boundary. A run that
  *succeeds* needs a real `RXYCODE_LLM_BASE_URL`+key; the same drain drove a
  real turn to `succeeded` (real model, `agent_done`+usage recorded).

## Quick verify

```bash
python -m pytest tests/web/w7/test_w7_c05_unit.py tests/web/w7/test_w7_c05_module.py -q
# 11 unit + 1 module passed — ~10-15 min; each docker test self-cleans its project.
```

## Audit r4 remediation (commit pending)

The same-session audit round 4 probed the sandboxed path with fault
injection and found five real defects; all are fixed in-tree:

- **Lease expiry now stops the turn on its own** (`drain.py:_lease_watchdog`).
  The deadline is anchored at the CLAIM instant, every store call is bounded
  by `wait_for` inside the remaining TTL, sleeps wake `0.25s` before expiry,
  and expiry cancels the turn + raises `_LeaseRenewalLost` (no terminal
  write). The audit probe shape (failed renewal + a status read stalling
  past the TTL) cancels at expiry — covered by unit leg (e).
- **Child config moved out of the writable workspace** (`_prepare_child_data_dir`
  → `provider.state_root/<sandbox>-conf`). The parent writes it; the sandbox
  sees it only via `--ro-bind` as `RXYCODE_DATA_DIR`. A confined turn can no
  longer plant a `.data/config.yaml` symlink for the parent to follow.
- **Stale `.turn-result.json` cannot fake success.** The file is unlinked
  before spawn, carries `run_id`, and a `succeeded` report additionally
  requires `rc == 0`. A leftover file or a crashed-after-report child
  resolves to failure.
- **Killed turns no longer lose their spend.** The confined child
  heartbeats cumulative `usage.delta` rows onto the run's own event log
  every 3 s; the parent takes `max(result, last delta, agent_done)` — a
  SIGKILLed paid turn still writes its measured usage before `cancelled`/
  `failed`.
- **`/tmp` mount order fixed.** `build_sandbox_argv` now mounts the private
  tmpfs BEFORE the workspace bind, so the default
  `RXYCODE_WORKER_WORKSPACES=/tmp/rxycode-runs` root works outside compose's
  `/work/runs` override instead of being shadowed.

Unit coverage: 11/11 `test_w7_c05_unit.py` (placement matrix, argv shape +
mount order, watchdog legs a–e incl. the audit probe, projection
vocabulary, stale-result rejection, config placement, usage-delta
recovery, compose validators).

### Live-debug additions during r4 remediation

- **Worker healthcheck false-positive fixed**: `probe_worker.py` checked
  `rxycode_worker` in `/proc/1/cmdline`, but PID 1 during the install phase
  is the startup `sh -c` whose script TEXT already contains that string —
  the probe passed once pip finished while drain had not yet `exec`'d.
  The module test's 90 s claim window then raced real startup. The probe
  now also requires `/proc/1/comm == python`, so `healthy` means the drain
  process itself owns PID 1.
- **Config vs data dir split**: the child reads config.yaml from a
  parent-owned ro-bound dir (`RXYCODE_TURN_CONFIG_SRC`) and copies it into
  `RXYCODE_DATA_DIR=<workspace>/.data` itself — discovered when the ro-bound
  data dir made `cache/precise_cache`'s mkdir fail with EROFS. The parent's
  only workspace interaction is `mkdir` + `.turn-result.json` cleanup.

## Audit r5 remediation (commit pending)

Round 5 probed harder and found five refinements; all fixed:

- **Lease deadline now anchored at renewal REQUEST-START** — the store
  computes `lease_until` from its own clock inside the transaction, so
  extending from completion let the turn outlive the real expiry by the
  response latency (probe: 15.2s alive on a 15.004s-expired lease). The
  wait_for floor also dropped to 0.05s so a probe cannot overrun the
  remaining TTL.
- **Zero-window usage metering**: `token_stats.add_real_usage` is wrapped
  in the child so every recorded provider response emits a cumulative
  `__RXY_USAGE__` line on stderr; the parent's pipe reader keeps the total
  in `streamed` — a SIGKILL cannot erase spend already delivered. The 3s
  `usage.delta` heartbeat remains as the durable record (survives even a
  parent crash).
- **Aggregation fixed**: `agent_done` tokens now `max()`-merge instead of
  replacing a larger result count.
- **Cross-attempt usage**: `usage.delta` payloads carry the lease `epoch`;
  `_usage_deltas_total` sums each attempt's last heartbeat, so a retried
  run keeps the earlier attempt's spend (attempt A=100 + retry B=5 → 105).
- **Mount order completed**: `--dev /dev` + `--tmpfs /tmp` now precede ALL
  binds — the `.sandboxes/<id>-conf` ro-bind lives under the workspaces
  root and was shadowed when that root sits under /tmp (default).

## Audit r6 remediation

Round 6 (same session) refined three more edges; all fixed:

- **Claim anchor moved before the `claim()` call** — post-commit work inside
  claim could otherwise let the watchdog deadline trail the real DB expiry.
- **Per-attempt metering aggregation**: sources merge by max WITHIN the
  attempt (result/streamed/heartbeat/agent_done are cumulative snapshots of
  the same spend) then SUM across lease epochs — attempt A's durable 100 +
  retry B's 5 commits 105, never 100 or 5.
- **stderr collector drains to EOF before being cancelled** — a fast-exiting
  child's final `__RXY_USAGE__` write is no longer dropped; CancelledError
  is caught explicitly (it's BaseException-derived, not Exception).
- Verified: contract leg retry passed in 230s on the same stack definition.

## Audit r7 remediation (commit pending)

Round 7 (same audit session) found the last two metering edges; fixed:

- **agent_done is now attempt-attributed**: `RunJournal.record` stamps every
  journaled payload with `attempt` from `RXYCODE_TURN_EPOCH` (the child env
  carries the lease epoch). `_agent_done_by_attempt` buckets
  `event/agent_done` snapshots by epoch and the ledger merges
  `max(deltas, dones)` per attempt then sums — attempt A's 100 + retry B's
  5 records 105, never A's snapshot re-charged inside B's bucket (200).
- **Lost-lease flush**: stderr-delivered spend that never made a heartbeat
  is flushed as a final `usage.delta` row (`final: true`, attempt-tagged)
  on EVERY exit path — including the lost-lease return that must not write
  terminal state. The flush is journaling, not ownership, so a retry's
  ledger recovers the spend (probe: 73 tokens after last heartbeat +
  lease lost → now durable instead of discarded).
- Regression coverage: `agent_done` epoch grouping, flush-once semantics
  (no duplicate row when cumulative already covers the pipe value), plus
  the existing watchdog/sandbox/projection suite — 13/13 unit legs green.
