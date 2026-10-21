#!/usr/bin/env bash
# W11: single-copy daily Postgres backup for the prod compose stack.
#
# Runs `pg_dump -Fc` inside the `postgres` service of project `rxyprod`
# (db/user rxycode, local-socket auth — no secrets in this file) and writes
#
#   /opt/rxycode/backups/rxycode-<YYYY-MM-DD>.dump
#
# then deletes every OTHER rxycode-*.dump in the directory — the newest
# file is the only copy kept (daily run = single-replica rotation). For
# multi-day history plus volume-level snapshots use infra/scripts/backup.sh
# instead; this script is the cheap always-on DB safety net.
#
# Schedule it once on the VM crontab (see docs/deploy/web-runbook.md):
#   10 3 * * * /opt/rxycode/src/infra/scripts/backup_pg.sh \
#     --env-file /opt/rxycode/.env >>/opt/rxycode/backups/backup_pg.log 2>&1
set -euo pipefail

PROJECT="rxyprod"
ENV_FILE=""
BACKUP_DIR="${RXYCODE_PG_BACKUP_DIR:-/opt/rxycode/backups}"

usage() {
  cat <<'EOF'
usage: backup_pg.sh [-p PROJECT] [--env-file FILE]

  -p, --project   compose project name (default: rxyprod)
  --env-file      env file passed to docker compose --env-file — required
                  when the stack's env vars are not exported (the compose
                  file interpolates ${RXYCODE_*} on every command, exec
                  included)

env: RXYCODE_PG_BACKUP_DIR   dump directory (default: /opt/rxycode/backups)
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project) PROJECT="$2"; shift 2 ;;
    --env-file)   ENV_FILE="$2"; shift 2 ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
COMPOSE=(docker compose
  -f infra/compose/compose.yaml
  -f infra/compose/compose.prod.yaml
  -p "$PROJECT")
if [ -n "$ENV_FILE" ]; then
  [ -f "$ENV_FILE" ] || { echo "env file not found: $ENV_FILE" >&2; exit 1; }
  COMPOSE+=(--env-file "$ENV_FILE")
fi

# --- sanity: stack must be up and postgres reachable (before we mkdir) -------
if ! "${COMPOSE[@]}" exec -T postgres true 2>/dev/null; then
  echo "cannot exec into postgres in project '$PROJECT' — is the stack up," >&2
  echo "and did you pass --env-file with all required vars?" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
DEST="$BACKUP_DIR/rxycode-$(date +%F).dump"

# --- dump (custom format -> pg_restore on the way back) ----------------------
echo "pg_dump -> $DEST"
"${COMPOSE[@]}" exec -T postgres \
  pg_dump -U rxycode -d rxycode -Fc --no-password > "$DEST"
[ -s "$DEST" ] || { echo "pg_dump produced an empty file" >&2; rm -f "$DEST"; exit 1; }

# --- rotation: keep ONLY the newest rxycode-*.dump ----------------------------
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'rxycode-*.dump' \
  ! -samefile "$DEST" -print -delete 2>/dev/null \
  || find "$BACKUP_DIR" -maxdepth 1 -type f -name 'rxycode-*.dump' \
       ! -name "$(basename "$DEST")" -print -delete

echo "backup complete: $DEST"
