"""In-app updates (admin): ask the host upgrade agent to update or roll back, and show its progress.

The container only writes a small JSON request into the inbox; the root-owned agent on TrueNAS validates it,
runs update.sh (backup, signature check, health check, automatic rollback) and reports through a read-only folder.
"""

import json
import os
import re
import statistics
import tempfile
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import __version__
from ..auth import require_admin
from ..config import get_settings
from ..models import User

router = APIRouter(prefix="/api/admin/updates", tags=["updates"])
VERSION_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$")

# Steps of an update, and the update.sh log lines that show each one was reached (same idea as NetWatch).
UPDATE_STAGES = (
    ("requested", "Requested", None),
    ("started", "Agent started", None),
    ("backup", "Backup", re.compile(r"^(current: |backing up the database)")),
    ("download", "Download and verify", re.compile(r"^(downloading v|verifying the signature|building image locally)")),
    ("restart", "Restart", re.compile(r"^restarting containers")),
    ("health", "Health check", re.compile(r"^waiting for the health check")),
    ("done", "Done", None),
)
ROLLBACK_STAGES = (
    ("requested", "Requested", None),
    ("started", "Agent started", None),
    ("restore", "Restore", re.compile(r"^(rolling back to|restoring database)")),
    ("restart", "Restart", re.compile(r"^restarting containers")),
    ("health", "Health check", re.compile(r"^waiting for the health check")),
    ("done", "Done", None),
)
LOG_LINE = re.compile(r"^\[update (\S+(?: \d\d:\d\d:\d\d)?)\] (.*)$")
REQUEST_STALE_S, RUNNING_STALE_S = 3600, 1800


def _ts(value) -> float | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).timestamp()


def _history(limit: int = 20) -> list[dict]:
    path = get_settings().upgrade_status_dir / "history.jsonl"
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 262_144:
            return []
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
        if len(out) >= limit:
            break
    return out


def estimate(action: str) -> float | None:
    """Median of the last 5 successful runs of this kind, plus half a minute for the agent to pick it up."""
    took = []
    for h in _history(50):
        if h.get("state") != "succeeded" or (h.get("action") or "update") != action:
            continue
        a, b = _ts(h.get("started_at")), _ts(h.get("finished_at"))
        if a and b and b > a:
            took.append(b - a)
        if len(took) >= 5:
            break
    return round(statistics.median(took) + 30, 1) if took else None


def progress(now: float | None = None) -> dict:
    """idle | requested | running | succeeded | failed, with the steps reached, the latest log line and an estimate."""
    import time

    now = now or time.time()
    inbox = get_settings().upgrade_dir / "request.json"
    req = None
    try:
        if inbox.is_file() and not inbox.is_symlink() and inbox.stat().st_size < 65536:
            req = json.loads(inbox.read_text())
    except (OSError, ValueError):
        req = None
    st = _read_json("status.json") or {}
    if req is not None:
        if now - (_ts(req.get("requested_at")) or now) > REQUEST_STALE_S:
            out = {"state": "failed", "reason": "the upgrade agent never picked up the request", "request": req}
        else:
            out = {"state": "requested", "request": req}
    elif st.get("state") == "running":
        out = {"state": "running", "status": st}
        if now - (_ts(st.get("started_at")) or now) > RUNNING_STALE_S:
            out = {"state": "failed", "reason": "the update stalled", "status": st}
    elif st.get("state") in ("succeeded", "failed"):
        out = {"state": st["state"], "status": st}
    else:
        return {"state": "idle", "status": st or None}
    action = (req or {}).get("action") or st.get("action") or "update"
    table = ROLLBACK_STAGES if action == "rollback" else UPDATE_STAGES
    reached: dict[str, float | None] = {"requested": _ts((req or {}).get("requested_at"))}
    last_line = None
    if out["state"] != "requested" and st:
        started = _ts(st.get("started_at"))
        reached["started"] = started
        for line in _log_tail(400):
            m = LOG_LINE.match(line.strip())
            if not m:
                continue
            ts, text = _ts(m[1].replace(" ", "T")), m[2].strip()
            if started and ts and ts < started - 5:
                continue  # an earlier run's lines
            last_line = text
            for key, _label, pattern in table:
                if pattern is not None and key not in reached and pattern.match(text):
                    reached[key] = ts
        if out["state"] == "succeeded":
            reached["done"] = _ts(st.get("finished_at"))
    keys = [k for k, _, _ in table]
    furthest = max((keys.index(k) for k in reached if k in keys), default=0)
    out.update({
        "action": action,
        "stages": [{"key": k, "label": label, "at": reached.get(k), "reached": i <= furthest}
                   for i, (k, label, _) in enumerate(table)],
        "failed_at": keys[furthest] if out["state"] == "failed" else None,
        "rolled_back": st.get("rolled_back") == "yes",
        "last_line": (last_line or "")[:160] or None,
        "estimate_s": estimate(action),
    })
    return out


def _read_json(name: str) -> dict | None:
    path = get_settings().upgrade_status_dir / name
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            return None
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _log_tail(lines: int = 200) -> list[str]:
    path = get_settings().upgrade_status_dir / "upgrade.log"
    try:
        if path.is_symlink() or not path.is_file():
            return []
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 64_000))
            return fh.read().decode("utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        return []


def _vkey(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def _versions(available: dict | None) -> list[str]:
    tags = (available or {}).get("tags") or ""
    out = [t.lstrip("v") for t in tags.split(",") if t]
    return [v for v in out if VERSION_RE.match(v)]


@router.get("")
def update_status(_: User = Depends(require_admin)):
    s = get_settings()
    agent = _read_json("agent.json")
    available = _read_json("available.json")
    versions = _versions(available)
    latest = max(versions, key=_vkey) if versions else None
    last_run = None
    if agent and agent.get("last_run"):
        try:
            last_run = datetime.fromisoformat(agent["last_run"].replace("Z", "+00:00"))
        except ValueError:
            last_run = None
    age = (datetime.now(UTC) - last_run).total_seconds() if last_run else None
    return {
        "current": __version__,
        "latest": latest,
        "update_available": bool(latest and _vkey(latest) > _vkey(__version__)),
        "versions": versions,
        "checked_at": (available or {}).get("checked_at"),
        "agent_installed": agent is not None,
        "agent_online": age is not None and age < 180,
        "agent_last_run": agent.get("last_run") if agent else None,
        "status": _read_json("status.json"),
        "pending": (s.upgrade_dir / "request.json").exists(),
        "log": _log_tail(),
        "progress": progress(),
        "history": _history(10),
        "inbox_writable": os.access(s.upgrade_dir, os.W_OK) if s.upgrade_dir.is_dir() else False,
    }


class UpdateRequest(BaseModel):
    action: str = Field(pattern=r"^(update|rollback|check)$")
    version: str | None = Field(default=None, pattern=r"^\d{1,3}\.\d{1,3}\.\d{1,3}$")


@router.post("", status_code=202)
def request_update(body: UpdateRequest, me: User = Depends(require_admin)):
    s = get_settings()
    inbox = s.upgrade_dir
    if not inbox.is_dir() or inbox.is_symlink():
        raise HTTPException(409, "The upgrade folder is not mounted; run setup.sh on the host to enable in-app updates")
    if (inbox / "request.json").exists():
        raise HTTPException(409, "An update request is already waiting for the agent")
    status = _read_json("status.json") or {}
    if status.get("state") == "running":
        raise HTTPException(409, "An update is already running")
    if body.action == "update":
        if not body.version:
            raise HTTPException(422, "Choose a version")
        if body.version not in _versions(_read_json("available.json")):
            raise HTTPException(422, "That version is not a published release")
    payload = {"action": body.action, "version": body.version or "", "requested_by": me.username,
               "requested_at": datetime.now(UTC).isoformat()}
    fd, tmp = tempfile.mkstemp(dir=inbox, prefix=".req.")
    with os.fdopen(fd, "w") as fh:
        json.dump(payload, fh)
    os.replace(tmp, inbox / "request.json")
    return {"queued": True, "message": "The host agent picks this up within a minute"}
