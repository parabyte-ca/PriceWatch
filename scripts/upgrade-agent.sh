#!/usr/bin/env bash
# PriceWatch CA host upgrade agent. Runs as root from a TrueNAS cron job (every minute).
#
# Trust model (dev-sop "Host Upgrade Agent Pattern"):
#   upgrade/         request inbox; the container can write here, so everything in it is untrusted
#   upgrade-status/  written only by this agent; mounted read-only in the container
#   .state/          root-only; never mounted
# The request is validated strictly (regular file, size, strict JSON, allowed action, X.Y.Z that is a real tag).
# Nothing from the inbox is ever sourced, eval'd or used as a path.
#
#   sudo scripts/upgrade-agent.sh --install    create or update the TrueNAS cron job (midclt)
#   sudo scripts/upgrade-agent.sh --uninstall  remove the cron job
#   sudo scripts/upgrade-agent.sh --status     show the agent's view
#   sudo scripts/upgrade-agent.sh              one run (what cron calls)
set -euo pipefail
umask 022

ROOT=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
INBOX="$ROOT/upgrade"
STATUS="$ROOT/upgrade-status"
STATE="$ROOT/.state"
AGENT_VERSION=1
CRON_DESC="PriceWatch upgrade agent"
MAX_REQUEST_BYTES=2048

[ "$(id -u)" = "0" ] || { echo "run as root" >&2; exit 1; }
cd "$ROOT"

write_json() {  # write_json <file> <python-dict-literal-args...>: atomic, world-readable
  local target=$1; shift
  local tmp
  tmp=$(mktemp "$STATUS/.tmp.XXXXXX")
  python3 -I -c 'import json,sys; print(json.dumps(dict(a.split("=",1) for a in sys.argv[1:])))' "$@" > "$tmp"
  chmod 644 "$tmp"
  mv -f "$tmp" "$STATUS/$target"
}

prepare_dirs() {
  mkdir -p "$INBOX" "$STATUS" "$STATE"
  # inbox: only the container user (568) may write; never follow a symlinked inbox
  if [ -L "$INBOX" ] || [ -L "$STATUS" ] || [ -L "$STATE" ]; then
    echo "refusing: a control folder is a symlink" >&2; exit 1
  fi
  chown 568:568 "$INBOX"; chmod 750 "$INBOX"
  chown root:root "$STATUS"; chmod 755 "$STATUS"
  chown root:root "$STATE"; chmod 700 "$STATE"
}

install_cron() {
  command -v midclt >/dev/null || { echo "midclt not found: add a root cron job that runs $ROOT/scripts/upgrade-agent.sh every minute" >&2; exit 1; }
  local cmd="$ROOT/scripts/upgrade-agent.sh >/dev/null 2>&1"
  local id
  id=$(midclt call cronjob.query "[[\"description\",\"=\",\"$CRON_DESC\"]]" | python3 -I -c 'import json,sys; r=json.load(sys.stdin); print(r[0]["id"] if r else "")')
  local body
  body=$(python3 -I -c 'import json,sys; print(json.dumps({"user":"root","command":sys.argv[1],"description":sys.argv[2],"enabled":True,"stdout":False,"stderr":False,"schedule":{"minute":"*","hour":"*","dom":"*","month":"*","dow":"*"}}))' "$cmd" "$CRON_DESC")
  if [ -n "$id" ]; then
    midclt call cronjob.update "$id" "$body" >/dev/null && echo "cron job $id updated"
  else
    midclt call cronjob.create "$body" >/dev/null && echo "cron job created"
  fi
}

uninstall_cron() {
  local id
  id=$(midclt call cronjob.query "[[\"description\",\"=\",\"$CRON_DESC\"]]" | python3 -I -c 'import json,sys; r=json.load(sys.stdin); print(r[0]["id"] if r else "")')
  [ -n "$id" ] && midclt call cronjob.delete "$id" >/dev/null && echo "cron job $id removed" || echo "no cron job"
}

current_version() { tr -d '[:space:]' < VERSION 2>/dev/null || echo unknown; }

refresh_available() {
  # at most every 30 minutes, or when asked
  local stamp="$STATE/last_fetch"
  if [ "${1:-}" != "force" ] && [ -f "$stamp" ] && [ $(( $(date +%s) - $(stat -c %Y "$stamp") )) -lt 1800 ]; then
    return 0
  fi
  if git fetch -q --tags origin 2>/dev/null; then
    touch "$stamp"
  fi
  local tags
  tags=$(git tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -20 | tr '\n' ',' | sed 's/,$//')
  write_json available.json "current=$(current_version)" "tags=$tags" "checked_at=$(date -u +%FT%TZ)"
}

validate_request() {  # prints "action version requested_by" or fails
  local f="$INBOX/request.json"
  [ -e "$f" ] || return 1
  if [ -L "$f" ] || [ ! -f "$f" ]; then rm -f "$f"; echo "rejected: not a regular file" >&2; return 2; fi
  local size; size=$(stat -c %s "$f")
  if [ "$size" -gt "$MAX_REQUEST_BYTES" ]; then rm -f "$f"; echo "rejected: too large" >&2; return 2; fi
  python3 -I - "$f" <<'PY'
import json, re, sys
try:
    with open(sys.argv[1], "rb") as fh:
        data = json.loads(fh.read().decode("utf-8"))
except Exception:
    sys.exit(2)
if not isinstance(data, dict) or set(data) - {"action", "version", "requested_by", "requested_at"}:
    sys.exit(2)
action = data.get("action")
version = str(data.get("version") or "")
who = str(data.get("requested_by") or "unknown")
if action not in ("update", "rollback", "check"):
    sys.exit(2)
if action == "update" and not re.fullmatch(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", version):
    sys.exit(2)
if not re.fullmatch(r"[a-z0-9._-]{1,40}", who):
    who = "unknown"
print(action, version or "-", who)
PY
}

run_once() {
  prepare_dirs
  exec 9>"$STATE/agent.lock"
  flock -n 9 || exit 0
  write_json agent.json "agent_version=$AGENT_VERSION" "last_run=$(date -u +%FT%TZ)" "current=$(current_version)"
  local parsed rc=0
  parsed=$(validate_request) || rc=$?
  if [ "$rc" = 1 ]; then refresh_available; exit 0; fi
  rm -f "$INBOX/request.json"   # consume before acting, so a failure never loops
  if [ "$rc" != 0 ] || [ -z "$parsed" ]; then
    write_json status.json "state=rejected" "message=Request was not valid" "finished_at=$(date -u +%FT%TZ)"
    exit 0
  fi
  local action version who
  read -r action version who <<<"$parsed"
  if [ "$action" = "check" ]; then
    refresh_available force
    write_json status.json "state=idle" "message=Checked for updates" "finished_at=$(date -u +%FT%TZ)"
    exit 0
  fi
  if [ "$action" = "update" ]; then
    refresh_available force
    git rev-parse -q --verify "refs/tags/v$version" >/dev/null || {
      write_json status.json "state=rejected" "message=No release v$version" "finished_at=$(date -u +%FT%TZ)"; exit 0; }
  fi
  local started; started=$(date -u +%FT%TZ)
  write_json status.json "state=running" "action=$action" "version=$version" "requested_by=$who" "started_at=$started"
  : > "$STATUS/upgrade.log"; chmod 644 "$STATUS/upgrade.log"
  local args=(--version "$version")
  [ "$action" = "rollback" ] && args=(--rollback)
  local code=0
  ./update.sh "${args[@]}" >> "$STATUS/upgrade.log" 2>&1 || code=$?
  local state=succeeded; [ "$code" = 0 ] || state=failed
  write_json status.json "state=$state" "action=$action" "version=$version" "requested_by=$who" \
    "started_at=$started" "finished_at=$(date -u +%FT%TZ)" "exit_code=$code" "current=$(current_version)"
  refresh_available force
}

case "${1:-}" in
  --install) prepare_dirs; install_cron; run_once ;;
  --uninstall) uninstall_cron ;;
  --status) cat "$STATUS"/agent.json "$STATUS"/status.json "$STATUS"/available.json 2>/dev/null; echo ;;
  "") run_once ;;
  *) echo "unknown option $1" >&2; exit 1 ;;
esac
