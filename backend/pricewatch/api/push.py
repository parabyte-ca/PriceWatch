"""Web Push subscriptions for the installed app."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import Alert, PushSubscription, User
from ..services import webpush

router = APIRouter(prefix="/api/push", tags=["push"])


class Keys(BaseModel):
    p256dh: str = Field(min_length=10, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class SubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000, pattern=r"^https://")
    keys: Keys
    user_agent: str | None = Field(default=None, max_length=300)


class EndpointIn(BaseModel):
    endpoint: str


@router.get("/key")
def key(_: User = Depends(current_user)):
    return {"public_key": webpush.public_key()}


@router.get("/devices")
def devices(db: Session = Depends(get_db), me: User = Depends(current_user)):
    subs = db.scalars(select(PushSubscription).where(PushSubscription.user_id == me.id)).all()
    return [{"id": s.id, "endpoint": s.endpoint, "user_agent": s.user_agent, "created_at": s.created_at,
             "last_success_at": s.last_success_at, "failures": s.failures} for s in subs]


@router.post("/subscribe", status_code=201)
def subscribe(body: SubscriptionIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if sub is None:
        sub = PushSubscription(endpoint=body.endpoint)
        db.add(sub)
    sub.user_id, sub.p256dh, sub.auth = me.id, body.keys.p256dh, body.keys.auth
    sub.user_agent, sub.failures = body.user_agent, 0
    db.commit()
    return {"ok": True, "id": sub.id}


@router.post("/unsubscribe")
def unsubscribe(body: EndpointIn, db: Session = Depends(get_db), me: User = Depends(current_user)):
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint,
                                                   PushSubscription.user_id == me.id))
    if sub:
        db.delete(sub)
        db.commit()
    return {"ok": True}


@router.post("/test")
def test(db: Session = Depends(get_db), me: User = Depends(current_user)):
    alert = Alert(user_id=me.id, rule_type="test", dedup_key="push-test", title="PriceWatch test",
                  body="Notifications on this device are working.", url="/", status="pending")
    sent = webpush.send(db, alert)
    if not sent:
        raise HTTPException(400, "No device accepted the test. Turn notifications on for this device first.")
    return {"sent": sent}
