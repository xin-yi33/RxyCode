#!/usr/bin/env bash
# W10-D2: restore a backup produced by backup.sh into a STOPPED stack.
#
#   1. Refuses to run while any container of the compose project is up —
#      take the stack down first (`docker compose -p rxyprod ... down`,
#      WITHOUT -v, or the volumes you are about to overwrite are deleted).
#   2. Restores every volumes/<name>.tar.gz into the project's named volumes
#      (wiping current contents).
#   3. Starts ONLY postgres, waits for it to accept connections, then feeds
#      postgres.pgdump to pg_restore --clean --if-exists.
#   4. Stops postgres again — bring the stack up yourself and verify:
#      `docker compose -p rxyprod ... up -d`, then run migrations if the
#      backup predates the deployed image (`run --rm migrate`).
#
# No secrets in this file: credentials come from --env-file / environment.
#
#   infra/scripts/restore.sh -p rxyprod --env-file 'D:\rxycode-prod\.env' \
#     'D:\rxycode-backups\rxyprod\20261028-020000'
set -euo pipefail

PROJECT="rxyprod"
ENV_FILE=""
BACKUP_DIR_ARG=""
TAR_IMAGE="${RXYCODE_BACKUP_TAR_IMAGE:-postgres:16}"

usage() {
  cat <<'EOF'
usage: restore.sh [-p PROJECT] [--env-file FILE] <backup-dir>

  <backup-dir>    timestamped dir created by backup.sh (Windows or unix path)
  -p, --project   compose project name (default: rxyprod) — must match the
                  project that produced the backup (volumes are named
                  <project>_<name>)
  --env-file      env file passed to docker compose --env-file

The stack must be STOPPED (`compose ... down`, keep volumes). The script
starts postgres alone to run pg_restore and stops it afterwards.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project) PROJECT="$2"; shift 2 ;;
    --env-file)   ENV_FILE="$2"; shift 2 ;;
    -h|--help)    usage; exit 0 ;;
    -*) echo "unknown flag: $1" >&2; usage; exit 2 ;;
    *)
      if [ -z "$BACKUP_DIR_ARG" ]; then BACKUP_DIR_ARG="$1"; shift
      else echo "unexpected argument: $1" >&2; usage; exit 2; fi ;;
  esac
done

win_to_unix() {
  local p="$1"
  p="${p//\\//}"
  if [[ "$p" =~ ^([A-Za-z]):/ ]]; then
    local drive
    drive="$(printf '%s' "${BASH_REMATCH[1]}" | tr 'A-Z' 'a-z')"
    p="/${drive}/${p#?:/}"
  fi
  printf '%s' "$p"
}

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

[ -n "$BACKUP_DIR_ARG" ] || { usage; exit 2; }
SRC="$(win_to_unix "$BACKUP_DIR_ARG")"
[ -d "$SRC" ] || { echo "backup dir not found: $SRC" >&2; exit 1; }
[ -s "$SRC/postgres.pgdump" ] \
  || { echo "missing postgres.pgdump in $SRC" >&2; exit 1; }

# --- refuse while the stack is up ---------------------------------------------
# Query the daemon by project label, not `compose ps`: the latter renders the
# compose model first and silently returns nothing when required env vars are
# missing — which must never read as "stack is down" here.
RUNNING="$(docker ps -q \
  --filter "label=com.docker.compose.project=${PROJECT}")"
if [ -n "$RUNNING" ]; then
  echo "project '$PROJECT' has running containers — stop the stack first" >&2
  echo "(from the repo root; NO -v or the volumes are deleted):" >&2
  echo "  ${COMPOSE[*]} down" >&2
  exit 1
fi

if [ -f "$SRC/manifest.txt" ]; then
  echo "--- backup manifest ---"; cat "$SRC/manifest.txt"; echo "-----------------------"
fi

# --- restore volume tars ------------------------------------------------------
if [ -d "$SRC/volumes" ]; then
  for archive in "$SRC/volumes"/*.tar.gz; do
    [ -e "$archive" ] || continue
    short="$(basename "$archive" .tar.gz)"
    vol="${PROJECT}_${short}"
    echo "restore volume $vol <- $(basename "$archive")"
    docker volume create \
      --label "com.docker.compose.project=${PROJECT}" \
      --label "com.docker.compose.volume=${short}" \
      "$vol" >/dev/null
    # Wipe current contents, then untar the backup over stdin.
    # MSYS_NO_PATHCONV keeps container paths (/dst) literal for docker.exe.
    MSYS_NO_PATHCONV=1 docker run --rm -i --entrypoint sh \
      -v "${vol}:/dst" "$TAR_IMAGE" \
      -c 'find /dst -mindepth 1 -delete; tar xzf - -C /dst' < "$archive"
  done
else
  echo "no volumes/ dir in $SRC — skipping volume restore"
fi

# --- postgres dump ------------------------------------------------------------
echo "starting postgres alone for pg_restore"
"${COMPOSE[@]}" up -d postgres

ready=0
for _ in $(seq 1 60); do
  if "${COMPOSE[@]}" exec -T postgres pg_isready -U rxycode -d rxycode \
      >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 2
done
if [ "$ready" -ne 1 ]; then
  echo "postgres never became ready" >&2
  exit 1
fi

echo "pg_restore <- postgres.pgdump"
"${COMPOSE[@]}" exec -T postgres \
  sh -c 'pg_restore -U rxycode -d rxycode --clean --if-exists' \
  < "$SRC/postgres.pgdump"

"${COMPOSE[@]}" stop postgres >/dev/null

echo "restore complete. Next (from the repo root):"
echo "  1. ${COMPOSE[*]} up -d"
echo "  2. if the backup predates the deployed images:"
echo "     ${COMPOSE[*]} run --rm migrate"
