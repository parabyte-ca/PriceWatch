"""Ask PriceWatch (questions answered by Claude) and the household's Claude set-up (admin)."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..auth import current_user, require_admin
from ..db import get_db
from ..models import User
from ..services import claude
from ..services.assistant import AskError, Assistant

router = APIRouter(prefix="/api", tags=["ask"])


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[Turn] = Field(min_length=1, max_length=40)


def _assistant(request: Request) -> Assistant:
    a = getattr(request.app.state, "assistant", None)
    if a is None:
        a = request.app.state.assistant = Assistant(request.app)
    return a


@router.get("/ask")
async def ask_status(request: Request, _: User = Depends(current_user)):
    return {"available": await asyncio.to_thread(_assistant(request).available)}


@router.post("/ask")
async def ask(body: Question, request: Request, _: User = Depends(current_user)):
    if body.messages[-1].role != "user":
        raise HTTPException(422, "the last message must be a question")
    # the tools call PriceWatch's API as this person: pass their sign-in along, nothing else
    auth = {k: v for k, v in (("cookie", request.headers.get("cookie")),
                              ("authorization", request.headers.get("authorization"))) if v}
    try:
        a = await _assistant(request).ask([m.model_dump() for m in body.messages], auth)
    except AskError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"answer": a.text, "tools": a.tools, "model": a.model, "usage": a.usage, "stop_reason": a.stop_reason}


class ClaudeIn(BaseModel):
    enabled: bool = True
    model: str
    effort: str = "medium"
    api_key: str | None = Field(default=None, max_length=300)
    price_fallback: bool = True
    monthly_cap_usd: float = Field(default=claude.DEFAULT_CAP_USD, ge=0, le=1000)


@router.get("/admin/claude")
def claude_status(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return claude.status(db)


@router.put("/admin/claude")
def claude_save(body: ClaudeIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if body.model not in claude.MODELS or body.effort not in claude.EFFORTS:
        raise HTTPException(422, "unknown model or effort")
    key = (body.api_key or "").strip() or None
    if key and not key.startswith("sk-ant-"):
        raise HTTPException(422, "That does not look like an Anthropic API key (sk-ant-...)")
    claude.save(db, body.enabled, body.model, body.effort, key, price_fallback=body.price_fallback,
                monthly_cap_usd=body.monthly_cap_usd)
    return claude.status(db)


@router.delete("/admin/claude/key")
def claude_forget(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    claude.forget_key(db)
    return claude.status(db)


class TestIn(BaseModel):
    api_key: str | None = Field(default=None, max_length=300)


@router.post("/admin/claude/test")
async def claude_test(body: TestIn | None = None, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return await claude.test(claude.config(db)["model"], (body.api_key if body else None) or None)
