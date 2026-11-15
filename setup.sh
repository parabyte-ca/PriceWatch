#!/usr/bin/env bash
# PriceWatch CA first-run setup. Idempotent: safe to re-run.
#  - creates .env from .env.example (mode 600) and generates the admin password
#  - creates the data folder owned by uid/gid 568 (TrueNAS "apps")
#  - checks the host port is free
#  - pulls the signed release image, falling back to a local build
#  - builds the browser sidecar and starts the stack, then waits for the health check
set -euo pipefail
cd "$(dirname "$0")"

PROJECT=pricewatch
CONTAINER=pricewatch
IMAGE=ghcr.io/parabyte-ca/pricewatch
VERSION=$(cat VERSION 2>/dev/null || echo latest)
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "VERSION file is not X.Y.Z: $VERSION" >&2; exit 1; }

log() { echo "[setup] $*"; }
die() { echo "[setup] ERROR: $*" >&2; exit 1; }

command -v docker >/dev/null || die "docker is not installed"
docker compose version >/dev/null 2>&1 || die "docker compose plugin is not available"

# ---- .env ----
NEW_PASSWORD=""
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  log "created .env from .env.example"
fi
set_env() {  # key value: replace or append
  if grep -q "^$1=" .env; then
    sed -i "s|^$1=.*|$1=$2|" .env
  else
    echo "$1=$2" >> .env
  fi
}
get_env() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }

if [ "$(get_env PRICEWATCH_AUTH_MODE)" != "none" ] && [ -z "$(get_env PRICEWATCH_ADMIN_PASSWORD)" ]; then
  NEW_PASSWORD=$(set +o pipefail; LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 20)
  set_env PRICEWATCH_ADMIN_PASSWORD "$NEW_PASSWORD"
fi
set_env PRICEWATCH_VERSION "$VERSION"
chmod 600 .env

PORT=$(get_env PRICEWATCH_HOST_PORT); PORT=${PORT:-8086}
DATA=$(get_env PRICEWATCH_DATA_PATH); DATA=${DATA:-./data}

# ---- data folder ----
mkdir -p "$DATA/backups"
if [ "$(id -u)" = "0" ]; then
  chown -R 568:568 "$DATA"
else
  log "not running as root; make sure $DATA is writable by uid 568 (sudo chown -R 568:568 $DATA)"
fi

# ---- port check ----
running_here=$(docker ps --filter "name=^${CONTAINER}$" --format '{{.Names}}' || true)
if [ -z "$running_here" ]; then
  if command -v ss >/dev/null && ss -tlnH "( sport = :$PORT )" | grep -q .; then
    die "port $PORT is already in use. Check: sudo ss -tlnp | grep :$PORT. Pick a free port from dev-sop/ports.md and set PRICEWATCH_HOST_PORT in .env"
  fi
fi

# ---- image ----
verify_image() {
  if [ "${PRICEWATCH_SKIP_VERIFY:-false}" = "true" ]; then
    log "signature check skipped (PRICEWATCH_SKIP_VERIFY=true)"; return 0
  fi
  if ! command -v cosign >/dev/null; then
    log "cosign not installed; skipping signature check (install cosign to verify release images)"; return 0
  fi
  cosign verify "$IMAGE:$VERSION" \
    --certificate-identity-regexp "(?i)^https://github.com/parabyte-ca/pricewatch/.github/workflows/release.yml@refs/heads/main$" \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com >/dev/null
}

if docker pull -q "$IMAGE:$VERSION" >/dev/null 2>&1 && verify_image; then
  log "using signed release image $IMAGE:$VERSION"
  set_env PRICEWATCH_IMAGE "$IMAGE"
else
  log "release image unavailable; building locally"
  docker build -t "parabyte-ca/$PROJECT:$VERSION" -t "parabyte-ca/$PROJECT:latest" \
    --build-arg VERSION="$VERSION" --build-arg REVISION="$(git rev-parse HEAD 2>/dev/null || echo unknown)" .
  set_env PRICEWATCH_IMAGE "parabyte-ca/$PROJECT"
fi
docker compose build browser

# ---- start ----
docker compose up -d
log "waiting for the health check..."
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
    log "PriceWatch CA v$VERSION is running on port $PORT"
    if [ -n "$NEW_PASSWORD" ]; then
      echo
      echo "  Sign in as: admin   password (stored in .env): $NEW_PASSWORD"
      echo
    fi
    log "next: open http://<truenas-ip>:$PORT, set a notification URL in Settings and send a test alert"
    exit 0
  fi
  sleep 2
done
docker compose logs --tail 50 pricewatch >&2
die "health check failed"
