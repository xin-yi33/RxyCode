# RxyCode web — self-hosted compose runbook (WEB-W7-C05)

Stack file: `infra/compose/compose.yaml` + `infra/compose/Caddyfile`.
Everything below was executed against this checkout on Docker Engine 29.7.2 /
Compose v5.5.1. Commands are run from the **repo root**.

## Topology

```
browser --https(8443)--> gateway (caddy:2.11, TLS internal CA)
                          |-- /api/*  -> api:8000  (SSE + WS included)
                          '-- /*      -> /srv/www  (vite dist from `webbuild`)
api (python:3.12-slim, uvicorn on rxycode_server.main.serve(mode=cloud))
worker (python:3.12-slim, `python -m rxycode_worker.drain` — durable queue
        consumer: claim -> placement gate -> per-run userns sandbox turn ->
        terminal commit. Every executed turn runs INSIDE a bubblewrap
        user/pid/ipc/uts namespace; the worker host never runs agent code)
migrate (one-shot: rxycode_server.persistence.migrate.upgrade_head)
webbuild (one-shot: node:22-slim, npm install + npm run build -> web-dist vol)
postgres:16 | redis:7 | bitnamilegacy/minio:2025.7.23 (named volumes)
```

Honest notes:

- The durable spine is `rxycode_worker.supervisor.claim/commit_terminal`
  plus the `outbox` table, and the worker service is a real consumer:
  `rxycode_worker.drain` polls `runs` for claimable rows (`pending`, or a
  dead worker's expired lease), takes the fenced lease, reads the persisted
  message with `load_run`, and spawns the turn as a confined child process.
  Journaling, telemetry spans and the usage ledger all land on the run's own
  event log. Its healthcheck proves the drain is PID 1 *and* can reach
  Postgres.
- **Turn isolation (public rule)**: `RXYCODE_WORKER_EXECUTION=cloud-only`
  means only `cloud:{tenant}:{workspace}` targets execute — the tenant
  segment must equal the run's own `tenant_id` (a cross-tenant target is
  refused), and `full`/`full_auto` permission profiles are refused outright:
  Full authority means unsandboxed host execution, which does not exist on
  this stack. Accepted targets run inside `rxycode_runner.sandbox.userns`
  (bubblewrap): `--unshare-user --unshare-pid --unshare-ipc --unshare-uts`,
  `--clearenv` + an explicit setenv passlist, system paths and the checkout
  read-only, only the per-tenant workspace writable, `--die-with-parent`
  tree reaping on cancel/stop. The agent's tool calls happen inside that
  namespace — sibling workspaces and the worker's own data dir are simply
  not mounted. If bwrap/userns is missing the provider raises
  `IsolationUnavailable` and the run fails honestly; there is no host
  fallback. The worker's `security_opt: seccomp=unconfined` exists solely
  because Docker's default seccomp profile forbids the `unshare`/`mount`
  syscalls userns needs — it grants no capability, no privileged flag and
  no docker.sock. When a real cloud sandbox broker (VM/gVisor provider)
  lands, it replaces `userns` behind the same `SandboxProvider` contract —
  the gate, lease and commit flow do not change.
- The api/worker/migrate images are stock `python:3.12-slim`; the checkout is
  **not** bind-mounted — it is streamed as a tar into the shared `repo-src`
  volume through the `reposync` service (see Bring-up). That keeps the stack
  working on Docker Desktop hosts that cannot mount host paths. The worker
  copies `/repo-src` to a writable `/repo` because appserver state can write;
  a `/opt/pkg` shim makes `RxyCode.RxyCode1_1_0.*` importable. Rebuilding an
  image is *not* required — but the first cold `up` pays a few minutes of
  `pip install`/`npm install` inside the api/worker/webbuild containers.
- The deployed api boots through `rxycode_server.main.serve()`, not bare
  `create_app`: `mode=local` on a non-loopback bind is refused by
  `reject_as_public_web_gateway`, so `RXYCODE_WEB_MODE=local` cannot weaken
  the deployed stack — the same guard the negative test exercises.

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
| `RXYCODE_WEB_RATE_LIMIT_RPM` | no | `240` | public-demo throttle: requests/min per client IP at the app layer; `0` disables |
| `RXYCODE_WORKER_ID` / `_POLL_SECONDS` / `_LEASE_TTL` / `_RUN_TIMEOUT` / `_MODEL` | no | hostname / `2` / `120` / `900` / active | drain worker tuning |
| `RXYCODE_WORKER_EXECUTION` | no | `cloud-only` | placement gate: `cloud-only` accepts only tenant-bound `cloud:*` targets (the shipped public mode); `sandboxed-local` is the dev opt-in that also accepts `local:*` — still confined |
| `RXYCODE_LLM_BASE_URL` / `RXYCODE_LLM_MODEL` | no | empty | when set, worker writes a real model entry (openai-compatible) into its config and executes turns against this endpoint |
| `RXYCODE_API_KEY` | no | empty | credential for the deployed endpoint; referenced via `api_key_env`, never written into config.yaml |
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
- `worker`: `/proc/1/cmdline` is `rxycode_worker` **and** `SELECT 1` on the same DSN
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

## Upgrade (new source on a running stack)

App services execute the checkout seeded into `repo-src` — `up -d` alone does
**not** refresh it, and leftover markers would release the old waits
instantly. The upgrade sequence therefore clears both markers, reseeds,
re-migrates and rebuilds before recreating consumers:

```bash
COMPOSE="docker compose -f infra/compose/compose.yaml -p rxyweb"

# 1. Stop consumers so nothing boots against a half-swapped tree
$COMPOSE stop api worker gateway

# 2. Clear the ordering markers — a stale marker would release api/worker on
#    old code. `run --no-deps` mounts the same volumes in a throwaway
#    container (reposync/migrate are one-shot; `exec` needs a running one).
$COMPOSE run --rm --no-deps -T migrate sh -c 'rm -f /boot/.migrate-done'

# 3. Reseed repo-src as an EXACT copy of the new checkout: a plain
#    `tar -xf -` overlay would keep files the new revision deleted (stale
#    modules, stale migration revisions). Empty the volume first, then
#    stream the tar — its final entry is the `.rxy-sync-done` marker.
$COMPOSE run --rm --no-deps -T reposync sh -c 'find /repo -mindepth 1 -delete'
tar --exclude=.git --exclude=node_modules --exclude=__pycache__ \
    --exclude=dist --exclude=build -cf - . | \
  $COMPOSE run --rm --no-deps -T reposync sh -c 'tar -xf - -C /repo'
git rev-parse HEAD | $COMPOSE run --rm --no-deps -T reposync \
  sh -c 'cat > /repo/.rxy-sync-done'

# 4. Re-run migrations and rebuild the SPA against the new source (drop the
#    stale index.html first so a restarting gateway can never serve it)
$COMPOSE run --rm --no-deps -T webbuild sh -c 'rm -f /dist/index.html'
$COMPOSE run --rm --no-deps migrate
$COMPOSE run --rm --no-deps webbuild

# 5. Recreate the long-running services — api/worker wait on the fresh
#    .migrate-done, gateway on the fresh index.html
$COMPOSE up -d --force-recreate api worker gateway
```

## Rollback

Same sequence pinned to the previous checkout (`git checkout <prev-ref>` first,
then steps 1–5). If a bad schema revision shipped, downgrade after the reseed
(`run` overrides the service command, so redo the tiny pip bootstrap first):

```bash
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
- **A cloud run that really executes** needs a real endpoint: set
  `RXYCODE_LLM_BASE_URL`/`RXYCODE_LLM_MODEL`/`RXYCODE_API_KEY` so the worker
  writes a real model entry and `Session.prompt` reaches your provider. The
  drain worker claims the durable run and drives the turn inside the per-run
  userns sandbox — no stdio client needed. Without a reachable endpoint the
  run still reaches a real terminal state (`failed`, not a fabricated
  `succeeded`), recorded by `test_w7_c05_module`. `local:*` targets and
  `full`/`full_auto` profiles are refused on this stack by design; on a
  development host set `RXYCODE_WORKER_EXECUTION=sandboxed-local` to let
  `local:*` drain (still confined — the drain never executes unconfined).
- The compose Postgres is for the web stack — the dev containers
  (`rxy-w2c01-pg` etc.) are untouched; use a distinct `-p` project name and
  the shipped loopback ports so nothing collides.
