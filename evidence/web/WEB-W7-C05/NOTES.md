# WEB-W7-C05 handoff notes

## What shipped

| File | Role |
|------|------|
| `infra/compose/compose.yaml` | 9-service stack: postgres, redis, minio, reposync, migrate, api, worker, webbuild, gateway |
| `infra/compose/Caddyfile` | HTTPS gateway (internal CA), security headers, `/api/*` reverse proxy (SSE+WS), SPA static + preview-auth seam |
| `.github/workflows/web-ci.yml` | 4 lanes: ruff, pytest web contract subset (with real docker), apps/web typecheck+build, compose config + deploy invariants |
| `docs/deploy/web-runbook.md` | bring-up/seed/migrations/certs/logs/upgrade/rollback/boundaries — commands verified on this checkout |
| `packages/rxycode-worker/src/rxycode_worker/drain.py` | the deployed queue consumer: claim -> load_run -> real `Session.prompt` turn -> usage ledger -> terminal commit |
| `packages/rxycode-worker/src/rxycode_worker/__main__.py` | `python -m rxycode_worker` entry to the drain |
| `packages/rxycode-server/src/rxycode_server/api/ratelimit.py` | per-client-IP fixed-window ASGI limiter (429 + Retry-After) |
| `packages/rxycode-server/src/rxycode_server/main.py` | `create_app(..., rate_limit_rpm=)` wires the limiter; `serve()` is the guarded boot path |
| `tests/web/w7/test_w7_c05_unit.py` | contract (real compose up + HTTPS + alembic head) + negative (validator refuses unsafe overlays incl. wildcard ports, local-mode public bind refused, limiter 429 drive) |
| `tests/web/w7/test_w7_c05_module.py` | deployed-worker drains a queued run inside the container; restart durability; deterministic stale-lease reclaim; worker-container SIGKILL + recreate recovery |

## Topology decisions worth knowing

- **The worker service is `python -m rxycode_worker.drain`** — a real durable
  consumer, not an idle stdio appserver. It polls `runs` for claimable rows
  (`pending`, or a dead worker's expired lease), takes the fenced lease via
  `supervisor.claim`, reads the persisted message with `runs.service.load_run`,
  and drives ONE real turn through `AgentRuntime -> Session.prompt` —
  journaled `event/agent_started`/`event/agent_done`, telemetry spans and the
  `usage.updated` ledger row all land on the run's own event log. A lease
  watchdog renews the fence and cancels the turn on `cancel_requested`
  (`confirm_cancel`) or a lost epoch (honest abort — the new owner finishes).
  Persisted `steer.accepted` commands reach the turn through a bound
  `_DrainWorkerShim` + `consume_persisted_commands`; `child.cancel` gets an
  honest "no manager" (the drain is single-agent).
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
- **Upgrade/rollback reseeds, not just recreates**: `up -d` alone leaves
  `repo-src` stale. The runbook sequence clears `.rxy-sync-done` +
  `.migrate-done`, re-streams the tar, writes the marker with the new commit
  hash, re-runs migrate + webbuild, then force-recreates api/worker/gateway
  so consumers never boot a half-swapped tree.
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
  `8000:8000` (that means 0.0.0.0). Secrets use `${VAR:?msg}` required
  interpolation — zero literals. Tests use per-test project names + free
  ports so the rxy-w2c* dev containers are never touched.

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
  Approval-gated tools then emit requests nobody can answer in a deployed
  drain (no stdin client) — the turn fails at `RXYCODE_WORKER_RUN_TIMEOUT`
  instead of hanging forever. The in-process approval-answer channel
  (`interrupt_resume`/`pause_for_approval`) is invoked by the caller that
  owns the lease; a resume service is not part of this stack.
- E2E-DEPLOY-01 run leg: the deployed drain worker really claims and
  executes queued runs — the module test asserts `worker.lease` +
  `event/agent_started` + `usage.updated` inside the container, where the
  configured model points at a loopback dead port so the provider call fails
  honestly at the network boundary (verified live: `run.error` carries
  "run timed out after 60s"). A run that *succeeds* needs a real
  `RXYCODE_LLM_BASE_URL`+key; on the host dev DB the same drain drove a real
  turn to `succeeded` (real model, `agent_done`+usage recorded).

## Quick verify

```bash
python -m pytest tests/web/w7/test_w7_c05_unit.py tests/web/w7/test_w7_c05_module.py -q
# 3 passed — ~10-15 min; each docker test self-cleans its project.
```
