# RxyCode web — self-hosted compose runbook (WEB-W7-C05)

Stack file: `infra/compose/compose.yaml` + `infra/compose/Caddyfile`.
Everything below was executed against this checkout on Docker Engine 29.7.2 /
Compose v5.5.1. Commands are run from the **repo root**.

## Topology

```
browser --https(8443)--> gateway (caddy:2.11, TLS internal CA)
                          |-- /api/*  -> api:8000  (SSE + WS included)
                          '-- /*      -> /srv/www  (vite dist from `webbuild`)
api (python:3.12-slim, uvicorn rxycode_server.main:create_app, mode=cloud)
worker (python:3.12-slim, `python -m appserver` over stdio)
migrate (one-shot: rxycode_server.persistence.migrate.upgrade_head)
webbuild (one-shot: node:22-slim, npm install + npm run build -> web-dist vol)
postgres:16 | redis:7 | bitnamilegacy/minio:2025.7.23 (named volumes)
```

Honest notes:

- There is **no standalone run-drain daemon** in this repo. The durable spine
  is `rxycode_worker.supervisor.claim/commit_terminal` plus the `outbox`
  table; the *worker service* is the real `python -m appserver` process —
  the same entry the desktop/TUI transports spawn — running headless with
  `RXYCODE_WEB_DATABASE_URL` set, so a web-bound session attaches via
  `agent_worker.bind_web_session`/`lookup_web_run` when one is driven over
  its stdio JSON-RPC. `tty: true` holds stdin open; the healthcheck proves
  the process lives *and* reaches Postgres.
- The api/worker/migrate images are stock `python:3.12-slim`; the checkout is
  **not** bind-mounted — it is streamed as a tar into the shared `repo-src`
  volume through the `reposync` service (see Bring-up). That keeps the stack
  working on Docker Desktop hosts that cannot mount host paths. The worker
  copies `/repo-src` to a writable `/repo` because appserver state can write;
  a `/opt/pkg` shim makes `RxyCode.RxyCode1_1_0.*` importable. Rebuilding an
  image is *not* required — but the first cold `up` pays a few minutes of
  `pip install`/`npm install` inside the api/worker/webbuild containers.
- `mode=cloud` is used because `rxycode_server.main.serve(mode="local")`
  refuses non-loopback binds by design (`reject_as_public_web_gateway`).

## Environment

No `.env` file is shipped. Export (or pass inline) per deploy:

| Var | Required | Default | Purpose |
|-----|----------|---------|---------|
| `RXYCODE_POSTGRES_PASSWORD` | yes | — | `POSTGRES_PASSWORD`; also embedded in `RXYCODE_WEB_DATABASE_URL` |
| `RXYCODE_MINIO_ROOT_USER` / `_PASSWORD` | yes | — | artifact store root creds |
| `RXYCODE_WEB_SECRET` | yes | — | session/CSRF secret; ≥32 chars, ≥10 distinct |
| `RXYCODE_WEB_MODE` | no | `cloud` | gateway mode (`local` must not be exposed) |
| `RXYCODE_WEB_ORIGINS` | no | `https://localhost:8443` | CSRF Origin allowlist (comma-separated) |
| `RXYCODE_GITHUB_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` | no | empty | real GitHub OAuth app for cloud login |
| `RXYCODE_S3_ENDPOINT` / `_BUCKET` | no | `http://minio:9000` / `rxycode-artifacts` | artifact store |
| `RXYCODE_PREVIEW_TOKEN` | no | empty | optional extra preview-token check at the gateway |
| `RXYCODE_PG_PORT` / `RXYCODE_HTTP_PORT` / `RXYCODE_HTTPS_PORT` | no | `54433` / `8080` / `8443` | loopback-published ports |

Example:

```bash
export RXYCODE_POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export RXYCODE_MINIO_ROOT_USER=rxy-minio
export RXYCODE_MINIO_ROOT_PASSWORD="$(openssl rand -hex 24)"
export RXYCODE_WEB_SECRET="$(openssl rand -hex 32)"
export COMPOSE_PROJECT_NAME=rxyweb
```

## Bring-up

```bash
# from repo root; pick a project name that is NOT a rxy-* dev container
docker compose -f infra/compose/compose.yaml -p rxyweb up -d

# Seed the checkout into the repo-src volume (the .rxy-sync-done marker is the
# gate every service waits on). Without this step the stack idles by design.
tar --exclude=.git --exclude=node_modules --exclude=__pycache__ \
    --exclude=dist --exclude=build -cf - . | \
  docker compose -f infra/compose/compose.yaml -p rxyweb exec -T reposync \
    sh -c 'tar -xf - -C /repo && touch /repo/.rxy-sync-done'

docker compose -f infra/compose/compose.yaml -p rxyweb ps -a
```

Ordering is by marker files on shared volumes, not blocking `depends_on`
conditions, so `up -d` returns immediately and seeding happens after:

- `reposync` exits once `.rxy-sync-done` appears in `repo-src`.
- `migrate` waits for the marker, runs `upgrade_head` against the project
  Postgres, then drops `.migrate-done` into the `boot-state` volume.
- `api` and `worker` wait on `.migrate-done` before starting their real
  processes; `gateway` waits for `index.html` in `web-dist` (dropped by
  `webbuild`). Once everything is green the gateway serves:

- `https://localhost:8443/` — built SPA (vite `dist`, not the dev server)
- `https://localhost:8443/api/v1/*` — proxied to `api:8000`
- `http://localhost:8080/` — plain HTTP, redirects to HTTPS

Healthcheck detail:

- `postgres`: `pg_isready -U rxycode -d rxycode` inside the container
- `api`: `GET /api/v1/auth/csrf` == 200 (app layer) **and** `SELECT 1`
  against `RXYCODE_WEB_DATABASE_URL` (durable layer)
- `worker`: `/proc/1/cmdline` is `appserver` **and** `SELECT 1` on the same DSN
- `gateway`: Caddy admin API on loopback `:2019` answers

## Migrations

`migrate` is a one-shot job (restart policy `no`) — it runs automatically on
`up` and is **idempotent** (`alembic upgrade head`). To re-run by hand after
pulling new revisions:

```bash
docker compose -f infra/compose/compose.yaml -p rxyweb run --rm migrate
docker compose -f infra/compose/compose.yaml -p rxyweb exec postgres \
  psql -U rxycode -d rxycode -c 'select version_num from alembic_version'
```

Head for this card: revision `004` (`004_waiting_approval`).

## Certificates

`tls internal` signs `localhost` with Caddy's internal CA, persisted in the
`caddy-data` volume. The API itself is HTTP behind the gateway; TLS ends at
Caddy, which is also where `proxy_headers` re-asserts `https` to FastAPI.

Trust the demo cert in a browser:

```bash
docker compose -f infra/compose/compose.yaml -p rxyweb \
  cp gateway:/data/caddy/pki/authorities/local/root.crt ./rxycode-local-root.crt
# then import rxycode-local-root.crt into the OS/browser trust store
```

`curl`/`httpx` verification without trusting that CA fails — expected: the
test suite asserts both directions (verify=False succeeds, verify=True
refuses). For a public deploy, replace `tls internal` with a real domain +
ACME or mounted cert files; the runbook steps otherwise stand.

## Preview-auth seam

`/api/v1/previews/{sandbox}/{port}/…` is owner-authenticated by the app
(`previews.proxy` + `current_record`). Setting `RXYCODE_PREVIEW_TOKEN` adds a
second gate at Caddy: preview requests must carry `X-Preview-Token: <token>`
or get `403` before reaching the API. Empty env ⇒ the gateway defers to app
auth. Rotate by changing the env and `up -d` (Caddy reloads the Caddyfile on
recreate only — force it with `docker compose ... up -d --force-recreate gateway`).

## Logs

```bash
docker compose -f infra/compose/compose.yaml -p rxyweb logs -f api
docker compose -f infra/compose/compose.yaml -p rxyweb logs --tail=200 worker
docker compose -f infra/compose/compose.yaml -p rxyweb logs migrate webbuild
docker compose -f infra/compose/compose.yaml -p rxyweb logs gateway --since 10m
```

api/worker pip output is the bring-up story; a worker that keeps restarting
usually means a missing pip dep — read its `logs` before anything else.

## Restart / recovery (断电)

- `docker compose -p rxyweb restart postgres api` — exercised by
  `tests/web/w7/test_w7_c05_module.py`: run rows + events survive on the
  `pg-data` volume; a stale lease (`lease_until` in the past) is re-claimed
  by a fresh `worker_id`, which bumps `lease_epoch` and commits terminal.
- `docker compose -p rxyweb down` (no `-v`) keeps `pg-data`; `up -d` resumes.
- `docker compose -p rxyweb down -v` drops the volumes — the full wipe path.
- The api's bootstrap is idempotent (pip "already satisfied" → uvicorn), so a
  restarted api re-passes health without operator input.

## Rollback

```bash
# pin to the previous checkout state, then recreate
git checkout <prev-ref> -- infra/compose apps/web packages
docker compose -f infra/compose/compose.yaml -p rxyweb up -d --force-recreate
# schema rollback if a bad revision shipped. `run` overrides the service
# command, so redo the tiny pip bootstrap first (stock python:3.12-slim):
docker compose -f infra/compose/compose.yaml -p rxyweb run --rm --no-deps \
  --entrypoint sh migrate -c "
    pip install --quiet --no-input 'sqlalchemy>=2,<2.1' 'alembic>=1.17,<2' 'psycopg[binary]>=3.2,<4' &&
    python -c \"import os; from rxycode_server.persistence.migrate import downgrade_base; downgrade_base(os.environ['RXYCODE_WEB_DATABASE_URL'])\""
```

(`downgrade_base` drops to base — destructive; prefer `command.downgrade` to a
named revision via the same module when you only need one step back.)

## Boundaries this stack does NOT cross

- **Cloud login** needs a real GitHub OAuth app (`RXYCODE_GITHUB_*`). Without
  it the UI reaches the login page and stops — everything else still serves.
- **A cloud run that really executes** needs a provider key the agent can use
  inside the worker *and* a session attached over the worker's stdio
  JSON-RPC. Neither is fabricated here; E2E-DEPLOY-01's "run completes" leg
  is covered to the durable-spine level by `test_w7_c05_integration` +
  W7-C01..C04, and the remaining gap is marked BLOCKED in evidence.
- The compose Postgres is for the web stack — the dev containers
  (`rxy-w2c01-pg` etc.) are untouched; use a distinct `-p` project name and
  the shipped loopback ports so nothing collides.
