#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# deploy-web-vm.sh - RxyCode cloud deploy helper for the rxyprod VM.
#
# RUNS ON THE PRODUCTION VM (CentOS 7) AS ROOT. Never prints secrets: only
# image pins, tags, health, version JSON and paths.
#
#   echo <sudo-pass> | sudo -S -p '' bash /opt/rxycode/.ops/deploy-web-vm.sh status
#   ... build    cloudfix-<sha8>-01 <commit8> [--dir DIR] [--manifest FILE]
#   ... deploy   cloudfix-<sha8>-01
#   ... verify
#   ... rollback [BACKUP_DIR]
#
# deploy():
#   1. preflight: new tag images exist, build manifest exists, disk free, DB
#      head, previous pinned images exist (rollback guarantee).
#   2. backup (root:root, env 600, dir 700) compose.prod.yaml + .env + pins +
#      container/image IDs + alembic head.
#   3. rewrite the four rxycode-* image pins in compose.prod.yaml to the SAME
#      tag AND set RXYCODE_IMAGE_TAG in .env to that tag (so the one-shot
#      migrate service resolves an existing image; today .env points at the
#      stale 3a8526c tag).
#   4. render/validate the compose config, assert every rxycode-* image in the
#      render is on the new tag.
#   5. run the one-shot migrate job on the new api image (idempotent).
#   6. force-recreate api -> worker (all replicas) -> gateway with health gates;
#      postgres/redis/minio are NEVER touched.
#   7. verify /api/v1/version reports the build commit and csrf answers 200.
#   Any post-mutation failure auto-restores the .before files and recreates the
#   previous pins (AUTO_ROLLBACK=1 default; set 0 to inspect manually).
#
# rollback(): restores compose.prod.yaml + .env from the newest cloudfix-*
# backup (or a given dir), force-recreates api/worker/gateway on the old pins
# and re-runs the health gates. It never downgrades the schema automatically.
# ---------------------------------------------------------------------------
set -euo pipefail
umask 077

ROOT="${RXYCODE_ROOT:-/opt/rxycode}"
PROJECT="${RXYPROD_PROJECT:-rxyprod}"
COMPOSE_BASE="$ROOT/compose.yaml"
COMPOSE_PROD="$ROOT/compose.prod.yaml"
ENV_FILE="$ROOT/.env"
OPS_DIR="$ROOT/.ops"
BUILD_ROOT="$OPS_DIR/build"
MANIFEST_DIR="$OPS_DIR/manifests"
BACKUP_ROOT="$ROOT/backups"

PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmmirror.com}"
BUILD_PROXY="${BUILD_PROXY:-http://192.168.88.128:7890}"
WORKER_REPLICAS="${RXYCODE_WORKER_REPLICAS:-3}"
MIN_FREE_KB_BUILD="${MIN_FREE_KB_BUILD:-3000000}"
MIN_FREE_KB_DEPLOY="${MIN_FREE_KB_DEPLOY:-1500000}"
TAG_RE='^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$'

say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s ==\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

require_root() {
  [ "$(id -u)" -eq 0 ] || die "run as root: echo <sudo-pass> | sudo -S -p '' bash $0 $*"
}

require_tag() {
  local tag="$1"
  [ -n "$tag" ] || die "missing tag"
  printf '%s' "$tag" | grep -Eq "$TAG_RE" || die "invalid tag: $tag"
  case "$tag" in
    *:*) die "tag must not contain colon";;
  esac
}

require_commit() {
  printf '%s' "$1" | grep -Eq '^[0-9a-fA-F]{7,40}$' || die "invalid commit sha: $1"
}

compose() {
  docker compose -p "$PROJECT" --env-file "$ENV_FILE" \
    -f "$COMPOSE_BASE" -f "$COMPOSE_PROD" "$@"
}

compose_images() { compose config --images 2>/dev/null | sort -u; }

http_port() {
  local p
  p="$(compose port gateway 80 2>/dev/null | head -1 | awk -F: '{print $NF}')" || true
  [ -n "$p" ] || p="${RXYCODE_HTTP_PORT:-8080}"
  printf '%s' "$p"
}

free_kb() { df -Pk "$ROOT" | awk 'NR==2 {print $4}'; }

alembic_head() {
  local pg_id
  pg_id="$(compose ps -q postgres 2>/dev/null | head -1)" || true
  [ -n "$pg_id" ] || { printf 'unknown'; return 0; }
  docker exec "$pg_id" psql -U rxycode -d rxycode -t -A \
    -c 'select version_num from alembic_version' 2>/dev/null | tr -d '[:space:]'
}

container_ids() { compose ps -q "$@" 2>/dev/null || true; }

service_healthy() {
  local id="$1" st
  st="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id" 2>/dev/null || echo missing)"
  [ "$st" = "healthy" ]
}
wait_healthy() {
  local svc="$1" expect="$2" timeout="$3" deadline ids n i ok
  deadline=$(( $(date +%s) + timeout ))
  say "waiting for $svc healthy (expect $expect, <=$timeout s)"
  while :; do
    ids="$(container_ids "$svc")"
    n=$(printf '%s\n' "$ids" | grep -c . || true)
    ok=1
    [ "$n" -ge "$expect" ] || ok=0
    if [ "$n" -ge "$expect" ]; then
      for i in $ids; do
        if ! service_healthy "$i"; then ok=0; break; fi
      done
    fi
    if [ "$ok" -eq 1 ]; then say "  $svc healthy ($n container(s))"; return 0; fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
      say "  $svc NOT healthy after $timeout s"
      compose ps || true
      return 1
    fi
    sleep 5
  done
}

wait_api_http() {
  local port="$1" timeout="$2" deadline
  deadline=$(( $(date +%s) + timeout ))
  while :; do
    if curl -fsS -m 5 -o /dev/null "http://127.0.0.1:$port/api/v1/auth/csrf"; then
      say "  api http csrf ok"
      return 0
    fi
    [ "$(date +%s)" -ge "$deadline" ] && { say "  api http csrf FAILED"; return 1; }
    sleep 3
  done
}

version_json() {
  local port="$1"
  curl -fsS -m 10 "http://127.0.0.1:$port/api/v1/version" 2>/dev/null || printf '{}'
}

assert_version_commit() {
  local port="$1" expect="$2" body
  body="$(version_json "$port")"
  say "  version: $body"
  case "$body" in
    *"\"commit\":\"$expect\""*) return 0;;
  esac
  die "version endpoint does not report commit $expect"
}

dump_failure_logs() {
  local dir="$1" svc id
  mkdir -p "$dir"
  for svc in api worker gateway; do
    for id in $(container_ids "$svc"); do
      docker logs --tail 120 "$id" >"$dir/$svc-$id.log" 2>&1 || true
    done
  done
  compose ps >"$dir/compose-ps.txt" 2>&1 || true
  say "failure logs saved under $dir (review before sharing - may contain tokens)"
}

# --- tag rewriting ---------------------------------------------------------
rewrite_pins() {
  local tag="$1" count
  cp -p "$COMPOSE_PROD" "$COMPOSE_PROD.tmp.$"
  sed -i -E "s#^([[:space:]]+image:[[:space:]]+rxycode-(api|worker|web)):.*#\1:$tag#" "$COMPOSE_PROD.tmp.$"
  count=$(grep -cE "^[[:space:]]+image:[[:space:]]+rxycode-(api|worker|web):$tag$" "$COMPOSE_PROD.tmp.$" || true)
  if [ "$count" -ne 4 ]; then
    rm -f "$COMPOSE_PROD.tmp.$"
    die "expected 4 rxycode image pins rewritten, got $count"
  fi
  mv -f "$COMPOSE_PROD.tmp.$" "$COMPOSE_PROD"
  # .env must point at an image that EXISTS: the migrate service still uses
  # the RXYCODE_IMAGE_TAG variable in the repo copy of the overlay.
  if grep -qE '^RXYCODE_IMAGE_TAG=' "$ENV_FILE"; then
    sed -i -E "s#^RXYCODE_IMAGE_TAG=.*#RXYCODE_IMAGE_TAG=$tag#" "$ENV_FILE"
  else
    printf 'RXYCODE_IMAGE_TAG=%s\n' "$tag" >>"$ENV_FILE"
  fi
  chmod 600 "$ENV_FILE"
}

assert_rendered_pins() {
  local tag="$1" bad img
  compose config >/dev/null 2>&1 || die "compose config failed to render - fix the pin env before any deploy"
  bad="$(compose_images | grep -E '^rxycode-(api|worker|web):' | grep -vE ":$tag$" || true)"
  [ -z "$bad" ] || die "rendered rxycode images not on tag $tag: $bad"
  for img in "rxycode-api:$tag" "rxycode-worker:$tag" "rxycode-web:$tag"; do
    docker image inspect "$img" >/dev/null 2>&1 || die "image missing on VM: $img (run build first)"
  done
  say "rendered pins:"
  compose_images | sed 's/^/  /'
}

# --- backups / record ------------------------------------------------------
new_backup_dir() {
  local tag="$1" dir
  dir="$BACKUP_ROOT/cloudfix-$tag-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$dir"
  chmod 700 "$dir"
  printf '%s' "$dir"
}

snapshot_state() {
  local dir="$1" pair img f
  cp -p "$COMPOSE_PROD" "$dir/compose.prod.yaml.before"
  cp -p "$ENV_FILE" "$dir/.env.before"
  chmod 600 "$dir/.env.before" "$dir/compose.prod.yaml.before"
  sha256sum "$COMPOSE_PROD" "$ENV_FILE" >"$dir/sha256.before.txt" 2>/dev/null || true
  compose_images >"$dir/pins.before.txt" 2>&1 || true
  compose ps >"$dir/containers.before.txt" 2>&1 || true
  for pair in api worker web; do
    f="$dir/image-$pair.before.txt"
    img="$(compose_images | grep -E "^rxycode-$pair:" | head -1)" || true
    if [ -n "$img" ]; then
      docker image inspect -f '{{.Id}}' "$img" >"$f" 2>/dev/null || printf 'unknown' >"$f"
    else
      printf 'unknown' >"$f"
    fi
  done
  alembic_head >"$dir/alembic.before.txt" 2>&1 || printf 'unknown' >"$dir/alembic.before.txt"
  say "backup: $dir"
}
write_record() {
  local dir="$1" tag="$2" commit="$3" pair
  {
    printf 'tag=%s\n' "$tag"
    printf 'commit=%s\n' "$commit"
    printf 'deployed_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'host=%s\n' "$(hostname)"
    for pair in api worker web; do
      printf '%s_image_id=%s\n' "$pair" "$(docker image inspect -f '{{.Id}}' "rxycode-$pair:$tag" 2>/dev/null || echo unknown)"
    done
    compose ps >"$dir/containers.after.txt" 2>&1 || true
    compose_images >"$dir/pins.after.txt" 2>&1 || true
    printf 'alembic_after=%s\n' "$(alembic_head)"
    printf 'version=%s\n' "$(version_json "$(http_port)")"
  } >"$dir/deploy.txt"
  chmod 600 "$dir/deploy.txt" 2>/dev/null || true
}

restore_files() {
  local dir="$1"
  [ -f "$dir/compose.prod.yaml.before" ] || die "backup lacks compose.prod.yaml.before: $dir"
  [ -f "$dir/.env.before" ] || die "backup lacks .env.before: $dir"
  cp -p "$dir/compose.prod.yaml.before" "$COMPOSE_PROD.restore.$"
  mv -f "$COMPOSE_PROD.restore.$" "$COMPOSE_PROD"
  cp -p "$dir/.env.before" "$ENV_FILE.restore.$"
  mv -f "$ENV_FILE.restore.$" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  say "restored compose.prod.yaml + .env from $dir"
  compose config >/dev/null 2>&1 || die "restored compose config does not render"
  compose_images | sed 's/^/  /'
}

recreate_service() {
  local svc="$1" replicas="$2" timeout="$3"
  step "recreate $svc"
  if [ -n "$replicas" ]; then
    compose up -d --force-recreate --no-deps --scale "$svc=$replicas" "$svc"
    wait_healthy "$svc" "$replicas" "$timeout" || return 1
  else
    compose up -d --force-recreate --no-deps "$svc"
    wait_healthy "$svc" 1 "$timeout" || return 1
  fi
}

migrate_head_gate() {
  local before="$1" after
  after="$(alembic_head)"
  say "alembic head: $after (before: $before)"
  [ -n "$after" ] || die "cannot read alembic_version after migrate"
}

manifest_value() {
  local file="$1" key="$2"
  grep -E "^$key=" "$file" 2>/dev/null | head -1 | cut -d= -f2- || true
}

do_build() {
  local tag="$1" commit="$2" dir="" manifest="" f free build_time proxy_args mf stamp pair
  shift 2 || true
  while [ $# -gt 0 ]; do
    case "$1" in
      --dir) dir="$2"; shift 2;;
      --manifest) manifest="$2"; shift 2;;
      *) die "unknown build argument: $1";;
    esac
  done
  require_tag "$tag"; require_commit "$commit"
  [ -n "$dir" ] || dir="$BUILD_ROOT/$tag"
  [ -d "$dir" ] || die "build dir missing: $dir"
  for f in .dockerignore infra/docker/api.Dockerfile infra/docker/worker.Dockerfile \
           infra/docker/web.Dockerfile apps/web/package-lock.json; do
    [ -f "$dir/$f" ] || die "build dir lacks $f: $dir"
  done
  free=$(free_kb)
  [ "$free" -ge "$MIN_FREE_KB_BUILD" ] || die "only $free KB free, need >= $MIN_FREE_KB_BUILD KB (prune first)"
  build_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  step "build images tag=$tag commit=$commit built_at=$build_time"
  say "context: $dir"
  say "pip index: $PIP_INDEX_URL"
  say "npm registry: $NPM_REGISTRY"
  say "build proxy: $BUILD_PROXY"

  proxy_args=(
    --build-arg "http_proxy=$BUILD_PROXY"
    --build-arg "https_proxy=$BUILD_PROXY"
    --build-arg "HTTP_PROXY=$BUILD_PROXY"
    --build-arg "HTTPS_PROXY=$BUILD_PROXY"
    --build-arg "NO_PROXY=localhost,127.0.0.1,192.168.88.0/24,172.16.0.0/12"
  )

  step "docker build rxycode-api:$tag"
  docker build -f "$dir/infra/docker/api.Dockerfile" \
    --build-arg "RXYCODE_BUILD_COMMIT=$commit" \
    --build-arg "RXYCODE_BUILD_TIME=$build_time" \
    --build-arg "PIP_INDEX_URL=$PIP_INDEX_URL" \
    "${proxy_args[@]}" \
    -t "rxycode-api:$tag" "$dir"

  step "docker build rxycode-worker:$tag"
  docker build -f "$dir/infra/docker/worker.Dockerfile" \
    --build-arg "RXYCODE_BUILD_COMMIT=$commit" \
    --build-arg "RXYCODE_BUILD_TIME=$build_time" \
    --build-arg "PIP_INDEX_URL=$PIP_INDEX_URL" \
    "${proxy_args[@]}" \
    -t "rxycode-worker:$tag" "$dir"

  step "docker build rxycode-web:$tag"
  docker build -f "$dir/infra/docker/web.Dockerfile" \
    --build-arg "NPM_REGISTRY=$NPM_REGISTRY" \
    "${proxy_args[@]}" \
    -t "rxycode-web:$tag" "$dir"

  step "verify build stamps"
  for pair in api worker; do
    stamp="$(docker image inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "rxycode-$pair:$tag" | grep -E '^RXYCODE_BUILD_COMMIT=' | head -1 || true)"
    [ "$stamp" = "RXYCODE_BUILD_COMMIT=$commit" ] || die "rxycode-$pair:$tag build stamp wrong: '$stamp'"
    say "  rxycode-$pair:$tag $stamp"
  done

  mkdir -p "$MANIFEST_DIR"
  mf="$MANIFEST_DIR/$tag.env"
  {
    printf 'tag=%s\n' "$tag"
    printf 'commit=%s\n' "$commit"
    printf 'build_time=%s\n' "$build_time"
    printf 'built_on=%s\n' "$(hostname)"
    for pair in api worker web; do
      printf '%s_image_id=%s\n' "$pair" "$(docker image inspect -f '{{.Id}}' "rxycode-$pair:$tag")"
    done
  } >"$mf"
  chmod 600 "$mf"
  if [ -n "$manifest" ]; then
    [ -f "$manifest" ] || die "manifest file not found: $manifest"
    cp -p "$manifest" "$MANIFEST_DIR/$tag-DEPLOY-MANIFEST.txt"
    sha256sum "$manifest" >"$MANIFEST_DIR/$tag-DEPLOY-MANIFEST.sha256"
    chmod 600 "$MANIFEST_DIR/$tag-DEPLOY-MANIFEST.txt" 2>/dev/null || true
    say "stored deploy manifest: $MANIFEST_DIR/$tag-DEPLOY-MANIFEST.txt"
  else
    warn "no --manifest file passed; deploy provenance will lack the WIP overlay list"
  fi
  say ""
  say "built:"
  docker images --format '{{.Repository}}:{{.Tag}}  {{.ID}}  {{.Size}}' | grep -E "^rxycode-(api|worker|web):$tag" || true
  say "manifest: $mf"
}
# --- status / deploy / verify / rollback ------------------------------------

MUTATED=0
BACKUP_DIR=""

deploy_guard() {
  local rc=$?
  trap - EXIT
  if [ "$rc" -ne 0 ] && [ "$MUTATED" -eq 1 ] && [ "${AUTO_ROLLBACK:-1}" = "1" ]; then
    warn "deploy failed (rc=$rc); AUTO-ROLLBACK from $BACKUP_DIR"
    restore_files "$BACKUP_DIR" || warn "restore_files failed"
    recreate_service api "" 300 || warn "api rollback recreate failed"
    recreate_service worker "$WORKER_REPLICAS" 420 || warn "worker rollback recreate failed"
    recreate_service gateway "" 180 || warn "gateway rollback recreate failed"
    dump_failure_logs "$BACKUP_DIR/failure-logs" || true
    warn "auto-rollback finished — verify manually before any retry"
  fi
  exit "$rc"
}

do_status() {
  local port
  step "status"
  compose ps || true
  say ""
  say "image pins (rendered):"
  compose_images | sed 's/^/  /' || true
  say ""
  say "alembic head: $(alembic_head)"
  port="$(http_port)"
  say "gateway host port: $port"
  say "version: $(version_json "$port")"
  say ""
  say "local rxycode images:"
  docker images --format '{{.Repository}}:{{.Tag}}  {{.ID}}  {{.Size}}' \
    | grep -E '^rxycode-(api|worker|web):' | head -20 || true
}

do_deploy() {
  local tag="${1:-}" dir="" mf commit commit8 before_head port free cur img pair
  shift || true
  while [ $# -gt 0 ]; do
    case "$1" in
      --dir) dir="$2"; shift 2;;
      *) die "unknown deploy argument: $1";;
    esac
  done
  [ -n "$tag" ] || die "usage: deploy <tag>"
  require_root
  require_tag "$tag"
  mf="$MANIFEST_DIR/$tag-DEPLOY-MANIFEST.txt"
  [ -f "$mf" ] || die "missing build manifest $mf (build with --manifest first)"
  commit="$(manifest_value "$mf" head)"
  [ -n "$commit" ] || die "manifest $mf lacks head="
  commit8="$(manifest_value "$mf" head_short)"
  [ -n "$commit8" ] || commit8="$(printf '%s' "$commit" | cut -c1-8)"
  for pair in api worker web; do
    docker image inspect "rxycode-$pair:$tag" >/dev/null 2>&1 \
      || die "image missing on VM: rxycode-$pair:$tag (run build first)"
  done
  free="$(free_kb)"
  [ "$free" -ge "$MIN_FREE_KB_DEPLOY" ] \
    || die "only $free KB free, need >= $MIN_FREE_KB_DEPLOY KB"
  # Rollback target = the images the CURRENT api/worker/gateway containers run.
  # The compose render also includes the one-shot migrate pin, which .env may
  # leave stale; that pin is not a rollback target and must not block a deploy.
  cur="$(for svc in api worker gateway; do
           for id in $(container_ids "$svc"); do
             docker inspect -f '{{.Config.Image}}' "$id" 2>/dev/null || true
           done
         done | sort -u)"
  [ -n "$cur" ] || die "cannot resolve the running api/worker/gateway images — refusing to deploy without a rollback target"
  for img in $cur; do
    docker image inspect "$img" >/dev/null 2>&1 \
      || die "running container image missing (rollback would be impossible): $img"
  done

  BACKUP_DIR="$(new_backup_dir "$tag")"
  snapshot_state "$BACKUP_DIR"
  before_head="$(alembic_head)"
  MUTATED=1
  trap deploy_guard EXIT

  step "rewrite compose image pins -> $tag"
  rewrite_pins "$tag"
  assert_rendered_pins "$tag"

  step "run one-shot migrations on rxycode-api:$tag"
  compose run --rm --no-deps -T migrate
  migrate_head_gate "$before_head"

  recreate_service api "" 300 || die "api did not become healthy"
  recreate_service worker "$WORKER_REPLICAS" 420 || die "workers did not become healthy"
  recreate_service gateway "" 180 || die "gateway did not become healthy"

  port="$(http_port)"
  say "gateway host port: $port"
  wait_api_http "$port" 180 || die "api http is not reachable through the gateway"
  assert_version_commit "$port" "$commit"

  write_record "$BACKUP_DIR" "$tag" "$commit"
  MUTATED=0
  trap - EXIT
  say ""
  say "DEPLOY OK tag=$tag commit=$commit8 record=$BACKUP_DIR/deploy.txt"
  do_verify || true
}

do_verify() {
  local port ids n i ok=1
  step "verify"
  compose ps || true
  for svc in api worker gateway; do
    ids="$(container_ids "$svc")"
    n=$(printf '%s\n' "$ids" | grep -c . || true)
    [ "$n" -ge 1 ] || { warn "$svc has no container"; ok=0; continue; }
    for i in $ids; do
      if ! service_healthy "$i"; then warn "$svc container $i is not healthy"; ok=0; fi
    done
  done
  port="$(http_port)"
  wait_api_http "$port" 60 || ok=0
  say "version: $(version_json "$port")"
  [ "$ok" -eq 1 ] || die "verify failed"
  say "VERIFY OK"
}

do_rollback() {
  local dir="${1:-}" port
  require_root
  if [ -z "$dir" ]; then
    dir="$(ls -1dt "$BACKUP_ROOT"/cloudfix-* 2>/dev/null | head -1 || true)"
  fi
  [ -n "$dir" ] && [ -d "$dir" ] || die "no cloudfix backup directory found under $BACKUP_ROOT"
  step "rollback from $dir"
  restore_files "$dir"
  recreate_service api "" 300 || die "api did not become healthy after rollback"
  recreate_service worker "$WORKER_REPLICAS" 420 || die "workers did not become healthy after rollback"
  recreate_service gateway "" 180 || die "gateway did not become healthy after rollback"
  port="$(http_port)"
  wait_api_http "$port" 180 || die "api http not reachable after rollback"
  say "ROLLBACK OK from $dir"
  do_verify || true
}

main() {
  local action="${1:-status}"
  shift || true
  case "$action" in
    status) do_status ;;
    build) do_build "$@" ;;
    deploy) do_deploy "$@" ;;
    verify) do_verify ;;
    rollback) do_rollback "$@" ;;
    *) die "usage: $0 {status|build <tag> <commit> [--dir DIR] [--manifest FILE]|deploy <tag>|verify|rollback [BACKUP_DIR]}" ;;
  esac
}

main "$@"



