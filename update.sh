#!/usr/bin/env bash
# PriceWatch CA update. Backs up the database, deploys a release tag, waits for the health check,
# and rolls back automatically on failure.
#   ./update.sh                  latest release tag (vX.Y.Z)
#   ./update.sh --version 0.2.0  a specific release
#   ./update.sh --ref <branch>   a git ref (pre-release testing; builds locally)
#   ./update.sh --rollback       previous deployed tag + the pre-update database backup
set -euo pipefail
ROOT=${PRICEWATCH_ROOT:-$(cd "$(dirname "$0")" && pwd)}
cd "$ROOT"
# run from a copy: git checkout below may replace this file while bash is still reading it
if [ -z "${PRICEWATCH_UPDATE_COPY:-}" ]; then
  mkdir -p .state
  cp "$0" .state/update-run.sh
  PRICEWATCH_UPDATE_COPY=1 PRICEWATCH_ROOT="$ROOT" exec bash .state/update-run.sh "$@"
fi

CONTAINER=pricewatch
IMAGE=ghcr.io/parabyte-ca/pricewatch
STATE=.state
LOG=logs/update.log
mkdir -p "$STATE" logs
exec > >(tee -a "$LOG") 2>&1
# UTC timestamps: the in-app progress view reads these lines to show which step is running
log() { echo "[update $(date -u +%FT%TZ)] $*"; }
die() { log "ERROR: $*"; exit 1; }

[ -f .env ] || die ".env not found; run setup.sh first"
get_env() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }
set_env() { if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi; }
PORT=$(get_env PRICEWATCH_HOST_PORT); PORT=${PORT:-8086}
DATA=$(get_env PRICEWATCH_DATA_PATH); DATA=${DATA:-./data}

MODE=update TARGET="" REF=""
while [ $# -gt 0 ]; do
  case "$1" in
    --version) TARGET="v${2#v}"; shift 2 ;;
    --ref) REF="$2"; shift 2 ;;
    --rollback) MODE=rollback; shift ;;
    *) die "unknown option $1" ;;
  esac
done

wait_healthy() {
  log "waiting for the health check"
  for _ in $(seq 1 60); do
    curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}

deploy_current_checkout() {
  local version; version=$(cat VERSION)
  [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "VERSION is not X.Y.Z: $version"
  set_env PRICEWATCH_VERSION "$version"
  local revision; revision=$(git rev-parse HEAD)
  log "downloading v$version"
  if [ -z "$REF" ] && docker pull -q "$IMAGE:$version" >/dev/null 2>&1; then
    if [ "${PRICEWATCH_SKIP_VERIFY:-false}" != "true" ] && command -v cosign >/dev/null; then
      log "verifying the signature"
      cosign verify "$IMAGE:$version" \
        --certificate-identity-regexp "(?i)^https://github.com/parabyte-ca/pricewatch/.github/workflows/release.yml@refs/heads/main$" \
        --certificate-oidc-issuer https://token.actions.githubusercontent.com >/dev/null || die "signature check failed for $IMAGE:$version"
      local label; label=$(docker inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE:$version")
      [ "$label" = "$revision" ] || die "image revision $label does not match tag commit $revision"
    fi
    set_env PRICEWATCH_IMAGE "$IMAGE"
  else
    log "building image locally"
    docker build -t "parabyte-ca/pricewatch:$version" --build-arg VERSION="$version" --build-arg REVISION="$revision" .
    set_env PRICEWATCH_IMAGE "parabyte-ca/pricewatch"
  fi
  docker compose rm -sf browser >/dev/null 2>&1 || true  # the browser sidecar was removed in 1.0
  log "restarting containers"
  docker compose up -d
}

restore_db() {
  local backup=$1
  [ -f "$backup" ] || die "backup $backup not found"
  log "restoring database from $backup"
  docker compose stop pricewatch
  cp "$DATA/pricewatch.db" "$STATE/pre-restore-$(date +%s).db" 2>/dev/null || true
  cp "$backup" "$DATA/pricewatch.db"
  rm -f "$DATA/pricewatch.db-wal" "$DATA/pricewatch.db-shm"
  chown 568:568 "$DATA/pricewatch.db" 2>/dev/null || true
}

if [ "$MODE" = rollback ]; then
  PREV=$(cat "$STATE/previous_ref" 2>/dev/null) || die "no previous deployment recorded"
  log "rolling back to $PREV"
  git checkout -q "$PREV"
  [ -f "$STATE/pre-update.db" ] && restore_db "$STATE/pre-update.db"
  deploy_current_checkout
  if wait_healthy; then
    log "rollback complete: $(curl -fsS "http://127.0.0.1:$PORT/healthz")"
  else
    die "rollback health check failed"
  fi
  exit 0
fi

# ---- update ----
CURRENT=$(cat "$STATE/current_ref" 2>/dev/null || git describe --tags --exact-match 2>/dev/null || git rev-parse HEAD)
git fetch -q --tags origin
if [ -n "$REF" ]; then
  git fetch -q origin "$REF"
  TARGET_REF="origin/$REF"
else
  TARGET=${TARGET:-$(git tag -l 'v*' --sort=-v:refname | head -1)}
  [ -n "$TARGET" ] || die "no release tags yet; use --ref main for a pre-release build"
  TARGET_REF="$TARGET"
fi
git rev-parse -q --verify "$TARGET_REF^{commit}" >/dev/null || die "unknown ref $TARGET_REF"
log "current: $CURRENT, target: $TARGET_REF"

log "backing up the database"
if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  STAMP=$(date +%Y%m%d-%H%M%S)
  docker exec "$CONTAINER" python -m pricewatch.backup "/data/backups/pre-update-$STAMP.db"
  cp "$DATA/backups/pre-update-$STAMP.db" "$STATE/pre-update.db"
elif [ -f "$DATA/pricewatch.db" ]; then
  cp "$DATA/pricewatch.db" "$STATE/pre-update.db"
fi

echo "$CURRENT" > "$STATE/previous_ref"
git checkout -q "$TARGET_REF"
deploy_current_checkout
if wait_healthy; then
  git describe --tags --exact-match 2>/dev/null > "$STATE/current_ref" || git rev-parse HEAD > "$STATE/current_ref"
  log "update complete: $(curl -fsS "http://127.0.0.1:$PORT/healthz")"
  log "to roll back: sudo ./update.sh --rollback"
else
  log "health check failed; rolling back automatically"
  docker compose logs --tail 50 pricewatch || true
  git checkout -q "$CURRENT"
  [ -f "$STATE/pre-update.db" ] && restore_db "$STATE/pre-update.db"
  deploy_current_checkout
  if wait_healthy; then
    die "update failed; rolled back to $CURRENT"
  fi
  die "update and rollback both failed; check docker compose logs"
fi
