"""In-app updates (admin): ask the host upgrade agent to update or roll back, and show its progress.

The container only writes a small JSON request into the inbox; the root-owned agent on TrueNAS validates it,
runs update.sh (backup, signature check, health check, automatic rollback) and reports through a read-only folder.
"""

import json
import os
import re
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
