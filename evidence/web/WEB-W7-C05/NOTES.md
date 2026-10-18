# WEB-W7-C05 handoff notes

## What shipped

| File | Role |
|------|------|
| `infra/compose/compose.yaml` | 9-service stack: postgres, redis, minio, reposync, migrate, api, worker, webbuild, gateway |
| `infra/compose/Caddyfile` | HTTPS gateway (internal CA), security headers, `/api/*` reverse proxy (SSE+WS), SPA static + preview-auth seam |
| `.github/workflows/web-ci.yml` | 4 lanes: ruff, pytest web contract subset (with real docker), apps/web typecheck+build, compose config + deploy invariants |
| `docs/deploy/web-runbook.md` | bring-up/seed/migrations/certs/logs/recovery/rollback/boundaries — commands verified on this checkout |
| `tests/web/w7/test_w7_c05_unit.py` | contract (real compose up + HTTPS + alembic head) + negative (validator refuses unsafe overlays, local-mode public bind refused) |
| `tests/web/w7/test_w7_c05_module.py` | restart durability + stale-lease re-claim + commit_terminal on the compose Postgres |

## Topology decisions worth knowing

- **No standalone worker daemon exists in this repo.** The worker service is
  `python -m appserver` (the same stdio JSON-RPC process the desktop/TUI
  transports spawn), held open with `tty: true`. `RXYCODE_WEB_DATABASE_URL`
  is what `appserver/agent_worker.bind_web_session`/`activate_web_database`
  use to bind web runs. Its healthcheck proves the process is alive AND can
  reach Postgres — it does not pretend to be a queue daemon.
- **Docker Desktop can't mount Windows host paths here** (verified: any
  host-path bind hangs container start). Instead of bind-mounting the
  checkout, `reposync` + a tar stream seed the `repo-src` volume; a
  `.rxy-sync-done` marker gates everyone. `migrate` then drops
  `.migrate-done` into `boot-state`; `gateway` waits for `index.html` in
  `web-dist`. This replaced an earlier `service_completed_successfully`
  design that deadlocked `up -d` (seed happens after up returns).
- **api is `uvicorn rxycode_server.main:create_app` in `mode=cloud`** —
  `serve(mode="local")` refuses non-loopback binds by design
  (`reject_as_public_web_gateway`), which the negative test asserts.
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
- **Ports/secrets**: all published ports bind `127.0.0.1` and are
  env-overridable (`RXYCODE_PG_PORT`/`RXYCODE_HTTP_PORT`/`RXYCODE_HTTPS_PORT`);
  secrets use `${VAR:?msg}` required interpolation — zero literals. Tests
  use per-test project names + free ports so the rxy-w2c* dev containers
  are never touched.

## Deviations / honest labels

- `docs/deploy/web-runbook.md` is covered by `.gitignore` (`docs/*` except
  a few dirs) — the file exists on disk as required but won't be tracked
  unless the ignore list gains `!docs/deploy/`. Left as-is (gitignore is
  not in this card's whitelist).
- Frontend install inside `webbuild` uses `npm install` (repo has
  `bun.lock`, no `package-lock.json`, so `npm ci` cannot run). Documented
  in both the workflow comment and runbook.
- E2E-DEPLOY-01 run-completes leg: **BLOCKED** — needs provider credentials
  + an agent session driving the worker's stdio JSON-RPC. Not faked;
  labeled blocked in green.txt and the runbook.

## Quick verify

```bash
python -m pytest tests/web/w7/test_w7_c05_unit.py tests/web/w7/test_w7_c05_module.py -q
# 3 passed — ~7-8 min; each docker test self-cleans its project.
```
