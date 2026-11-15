#!/usr/bin/env bash
# End-to-end smoke test: start the stack on a clean data folder, add a fixture-served product,
# lower the target above the current price and assert the alert reaches the notification endpoint,
# then restart the app and check the data survived.
# Usage: scripts/smoke.sh [--keep] [--browser]
set -euo pipefail
cd "$(dirname "$0")/.."

KEEP=false
BROWSER=false
for arg in "$@"; do
  case "$arg" in
    --keep) KEEP=true ;;
    --browser) BROWSER=true ;;
  esac
done

PORT=${SMOKE_PORT:-18086}
DATA=$(mktemp -d)
chmod 777 "$DATA"
ENVFILE=$(mktemp)
sed -e "s|^PRICEWATCH_HOST_PORT=.*|PRICEWATCH_HOST_PORT=$PORT|" -e "s|^PRICEWATCH_DATA_PATH=.*|PRICEWATCH_DATA_PATH=$DATA|" \
    -e "s|^PRICEWATCH_VERSION=.*|PRICEWATCH_VERSION=$(cat VERSION)|" .env.example > "$ENVFILE"
echo "PRICEWATCH_ENV_FILE=$ENVFILE" >> "$ENVFILE"
# never touches a real .env: the stack reads only the temporary file
COMPOSE=(docker compose -p pricewatch-smoke --env-file "$ENVFILE" -f docker-compose.yml -f scripts/docker-compose.smoke.yml)
SERVICES=(pricewatch fixtures)
$BROWSER && SERVICES+=(browser)
BASE="http://127.0.0.1:$PORT"
JAR=$(mktemp)

cleanup() {
  if ! $KEEP; then
    "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$DATA" "$JAR" "$ENVFILE"
  fi
}
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; "${COMPOSE[@]}" logs --tail 50 pricewatch >&2 || true; exit 1; }
pass() { echo "ok   $*"; }

wait_healthy() {
  for _ in $(seq 1 60); do
    curl -fsS "$BASE/healthz" >/dev/null 2>&1 && return 0
    sleep 1
  done
  fail "app did not become healthy"
}

req() {  # method path [json]
  local m=$1 p=$2 d=${3:-}
  if [ -n "$d" ]; then
    curl -fsS -b "$JAR" -c "$JAR" -X "$m" -H 'Content-Type: application/json' -d "$d" "$BASE$p"
  else
    curl -fsS -b "$JAR" -c "$JAR" -X "$m" "$BASE$p"
  fi
}

jget() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {}, {'d': d}))" "$1"; }

echo "Starting stack (data in $DATA)..."
"${COMPOSE[@]}" up -d --no-build "${SERVICES[@]}" >/dev/null
wait_healthy
pass "healthz: $(curl -fsS "$BASE/healthz")"

[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/items")" = "401" ] || fail "API not protected"
pass "API requires login"
req POST /api/auth/login '{"password":"smoke-test-password"}' >/dev/null || fail "login"
pass "login"

req PATCH /api/settings '{"notify_urls":["json://fixtures:8000/notify"]}' >/dev/null || fail "settings"
ITEM=$(req POST /api/items/from-url '{"url":"http://fixtures:8000/jsonld_offer.html"}') || fail "add by URL"
ID=$(echo "$ITEM" | jget 'd["id"]')
PRICE=$(echo "$ITEM" | jget 'd["summary"]["best_price_cents"]')
[ "$PRICE" = "44999" ] || fail "expected price 44999, got $PRICE"
pass "added item $ID from URL, price \$449.99 parsed from JSON-LD"

req PATCH "/api/items/$ID" '{"target_price_cents":45000}' >/dev/null || fail "set target"
sleep 2
GOT=$(curl -fsS "http://127.0.0.1:18000/received")
echo "$GOT" | grep -q "BUY NOW" || fail "alert not delivered: $GOT"
pass "target alert delivered through Apprise"

SID=$(echo "$ITEM" | jget 'd["sources"][0]["id"]')
OUT=$(req POST "/api/sources/$SID/check" | jget 'd["outcome"]')
[ "$OUT" = "ok" ] || fail "manual check outcome $OUT"
pass "check now: $OUT"

if $BROWSER; then
  req PATCH "/api/sources/$SID" '{"fetch_mode":"browser"}' >/dev/null
  OUT=$(req POST "/api/sources/$SID/check" | jget 'd["outcome"]')
  [ "$OUT" = "ok" ] || fail "browser check outcome $OUT"
  pass "browser sidecar render: $OUT"
fi

"${COMPOSE[@]}" restart pricewatch >/dev/null
wait_healthy
req POST /api/auth/login '{"password":"smoke-test-password"}' >/dev/null
N=$(req GET "/api/items/$ID/history" | jget 'sum(len(s["points"]) for s in d["series"])')
[ "$N" -ge 2 ] || fail "history lost after restart ($N points)"
pass "restart: data intact ($N observations)"

echo "SMOKE TEST PASSED"
