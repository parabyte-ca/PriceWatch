"""Web Push to the installed app (Android Chrome, desktop browsers, iOS 16.4+ home-screen apps).

VAPID keys are created once in the data folder. Pushes need HTTPS in the browser (Tailscale or the reverse proxy).
"""

import base64
import json
import logging
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Alert, PushSubscription
from ..timeutil import utcnow

log = logging.getLogger(__name__)
_vapid = None


def _key_path() -> Path:
    return get_settings().data_dir / "vapid_private.pem"


def vapid():
    """Load or create the server's VAPID key pair."""
    global _vapid
    if _vapid is not None:
        return _vapid
    from py_vapid import Vapid01

    path = _key_path()
    if path.is_file():
        _vapid = Vapid01.from_file(str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        v = Vapid01()
        v.generate_keys()
        v.save_key(str(path))
        path.chmod(0o600)
        _vapid = v
    return _vapid


def public_key() -> str:
    raw = vapid().public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _subject() -> str:
    url = get_settings().public_url
    return url if url.startswith("https://") else "mailto:pricewatch@localhost"


def payload(alert: Alert) -> dict:
    from .alerts import action_token

    base = get_settings().public_url.rstrip("/")
    data = {"title": alert.title, "body": alert.body, "url": alert.url or "/", "tag": f"pw-{alert.item_id or 'sys'}",
            "item_id": alert.item_id}
    if alert.item_id:
        data["item_url"] = f"/items/{alert.item_id}"
        data["snooze_url"] = f"{base}/api/actions/{action_token(alert.item_id, 'snooze', alert.user_id)}" \
            if base else f"/api/actions/{action_token(alert.item_id, 'snooze', alert.user_id)}"
    return data


def send(db: Session, alert: Alert, sender=None) -> int:
    """Push to every device the person subscribed. Returns how many accepted it. Gone subscriptions are removed."""
    if alert.user_id is None:
        return 0
    subs = db.scalars(select(PushSubscription).where(PushSubscription.user_id == alert.user_id)).all()
    if not subs:
        return 0
    if sender is None:
        from pywebpush import webpush as sender  # noqa: N813
    body = json.dumps(payload(alert))
    ok = 0
    for sub in subs:
        info = {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
        try:
            sender(subscription_info=info, data=body, vapid_private_key=vapid(),
                   vapid_claims={"sub": _subject()}, ttl=86400, timeout=10)
            sub.last_success_at, sub.failures = utcnow(), 0
            ok += 1
        except Exception as exc:  # noqa: BLE001
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                db.delete(sub)  # the browser dropped this subscription
            else:
                sub.failures = (sub.failures or 0) + 1
                log.warning("web push failed", extra={"status": status, "error": type(exc).__name__})
    db.commit()
    return ok
