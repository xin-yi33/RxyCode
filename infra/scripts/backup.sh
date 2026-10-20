#!/usr/bin/env bash
# W10-D2: daily backup for the RxyCode prod compose stack.
#
# What it captures, into a timestamped dir under $RXYCODE_BACKUP_DIR
# (default D:\rxycode-backups, env-overridable; Windows and /d/... paths both
# accepted):
#
#   <backup-dir>/<project>/<YYYYMMDD-HHMMSS>/
#     manifest.txt            project, timestamp, image tag, git sha
#     postgres.pgdump         pg_dump -Fc of the `postgres` service database
#     volumes/<name>.tar.gz   tar of every compose-managed volume EXCEPT
#                             pg-data (covered by the dump — a raw tar of a
#                             running PG is not consistent) and the dev-seed
#                             volumes repo-src / boot-state / web-dist.
#                             -> worker-data (run workspaces), minio-data
#                             (artifact store), redis-data, caddy-data,
#                             caddy-config.
#
# Keeps the newest --keep (default 7) timestamped dirs; older are pruned.
# No secrets in this file: the DB dump runs inside the postgres container
# over the local socket (trust auth, same as the runbook psql), and every
# compose credential comes from the caller's --env-file / environment.
#
# Run on the live stack (pg_dump takes a consistent snapshot online):
#   infra/scripts/backup.sh -p rxyprod --env-file 'D:\rxycode-prod\.env'
# Restore with infra/scripts/restore.sh.
set -euo pipefail

PROJECT="rxyprod"
ENV_FILE=""
KEEP=7
# Image used for the throwaway tar containers — postgres:16 is guaranteed
# present (the stack pulls it) and ships tar+gzip; override if unavailable.
TAR_IMAGE="${RXYCODE_BACKUP_TAR_IMAGE:-postgres:16}"
# Space-separated volume-name suffixes to skip (project prefix stripped).
SKIP_VOLUMES="${RXYCODE_BACKUP_SKIP_VOLUMES:-pg-data repo-src boot-state web-dist}"

usage() {
  cat <<'EOF'
usage: backup.sh [-p PROJECT] [--env-file FILE] [--keep N]

  -p, --project   compose project name (default: rxyprod)
  --env-file      env file passed to docker compose --env-file (secrets stay
                  there; required when stack env vars are not exported)
  --keep          number of timestamped backups to retain (default: 7)

env: RXYCODE_BACKUP_DIR   backup root (default: D:\rxycode-backups)
     RXYCODE_BACKUP_TAR_IMAGE   image for volume tars (default: postgres:16)
     RXYCODE_BACKUP_SKIP_VOLUMES   volume suffixes to skip
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -p|--project) PROJECT="$2"; shift 2 ;;
    --env-file)   ENV_FILE="$2"; shift 2 ;;
    --keep)       KEEP="$2"; shift 2 ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

# Convert a Windows path (D:\foo or D:/foo) to a git-bash path (/d/foo);
# passes through anything that is already a unix path.
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
# Relative -f paths: docker.exe is native; absolute /d/... args survive MSYS
# path conversion only because it rewrites them — relative paths need none.
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

BACKUP_ROOT="$(win_to_unix "${RXYCODE_BACKUP_DIR:-D:\\rxycode-backups}")"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_ROOT/$PROJECT/$STAMP"
mkdir -p "$DEST/volumes"
echo "backup destination: $DEST"

# --- manifest ---------------------------------------------------------------
GIT_SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
{
  echo "project=$PROJECT"
  echo "stamp=$STAMP"
  echo "created=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "git_sha=$GIT_SHA"
  echo "image_tag=${RXYCODE_IMAGE_TAG:-latest}"
  echo "compose_files=infra/compose/compose.yaml infra/compose/compose.prod.yaml"
} > "$DEST/manifest.txt"

# --- postgres dump (custom format -> pg_restore on the way back) -------------
echo "pg_dump -> postgres.pgdump"
"${COMPOSE[@]}" exec -T postgres \
  pg_dump -U rxycode -d rxycode -Fc --no-password > "$DEST/postgres.pgdump"
[ -s "$DEST/postgres.pgdump" ] || { echo "pg_dump produced an empty file" >&2; exit 1; }

# --- volume tars -------------------------------------------------------------
mapfile -t VOLUMES < <(docker volume ls -q \
  --filter "label=com.docker.compose.project=${PROJECT}" | sort)
for vol in "${VOLUMES[@]}"; do
  short="${vol#"${PROJECT}"_}"
  skip=0
  for s in $SKIP_VOLUMES; do
    if [ "$short" = "$s" ]; then skip=1; break; fi
  done
  if [ "$skip" -eq 1 ]; then
    echo "skip volume $vol"
    continue
  fi
  echo "tar volume $vol -> volumes/${short}.tar.gz"
  # MSYS_NO_PATHCONV: git-bash rewrites args like `-C /src` or `-C/src` into
  # Windows paths for native docker.exe; container paths must stay literal.
  MSYS_NO_PATHCONV=1 docker run --rm --entrypoint tar \
    -v "${vol}:/src:ro" "$TAR_IMAGE" \
    czf - -C /src . > "$DEST/volumes/${short}.tar.gz"
  [ -s "$DEST/volumes/${short}.tar.gz" ] \
    || { echo "volume tar is empty: $vol" >&2; exit 1; }
done

# --- prune: keep the newest $KEEP timestamped dirs ---------------------------
mapfile -t DIRS < <(
  find "$BACKUP_ROOT/$PROJECT" -mindepth 1 -maxdepth 1 -type d \
    -printf '%f\n' | grep -E '^[0-9]{8}-[0-9]{6}$' | sort
)
COUNT=${#DIRS[@]}
if [ "$COUNT" -gt "$KEEP" ]; then
  REMOVE=$((COUNT - KEEP))
  for old in "${DIRS[@]:0:$REMOVE}"; do
    echo "prune $BACKUP_ROOT/$PROJECT/$old"
    rm -rf "${BACKUP_ROOT:?}/$PROJECT/$old"
  done
fi

echo "backup complete: $DEST (kept newest $KEEP of $COUNT)"
