"""APScheduler jobs: a 60-second tick dispatches due source checks with concurrency limits."""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import or_, select

from .db import session_scope
from .models import Item, SourceLink
from .services import alerts, runtime
from .services.checker import check_source
from .timeutil import utcnow

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_tasks: set[asyncio.Task] = set()


def due_source_ids(limit: int = 100) -> list[int]:
    db = session_scope()
    try:
        now = utcnow()
        rows = db.scalars(
            select(SourceLink.id)
            .join(Item, Item.id == SourceLink.item_id)
            .where(
                Item.active.is_(True),
                SourceLink.status == "confirmed",
                ~SourceLink.url.startswith("manual://"),
                or_(SourceLink.next_check_at.is_(None), SourceLink.next_check_at <= now),
            )
            .order_by(SourceLink.next_check_at.is_(None).desc(), SourceLink.next_check_at)
            .limit(limit)
        ).all()
        return list(rows)
    finally:
        db.close()


async def _run_one(source_id: int) -> None:
    try:
        async with runtime.semaphore():
            await check_source(source_id)
    finally:
        runtime.in_flight.discard(source_id)


def dispatch(source_id: int) -> bool:
    if source_id in runtime.in_flight:
        return False
    runtime.in_flight.add(source_id)
    task = asyncio.get_running_loop().create_task(_run_one(source_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True


async def tick() -> int:
    started = 0
    for sid in due_source_ids():
        if dispatch(sid):
            started += 1
    if started:
        log.info("tick dispatched", extra={"count": started})
    return started


async def housekeeping() -> None:
    db = session_scope()
    try:
        alerts.flush_deferred(db)
        alerts.check_failing_sources(db)
    finally:
        db.close()


def start() -> AsyncIOScheduler:
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(tick, "interval", seconds=60, id="tick", max_instances=1, coalesce=True,
                       next_run_time=utcnow_aware())
    _scheduler.add_job(housekeeping, "interval", minutes=5, id="housekeeping", max_instances=1, coalesce=True)
    _scheduler.start()
    return _scheduler


def utcnow_aware():
    from datetime import UTC, datetime, timedelta

    return datetime.now(UTC) + timedelta(seconds=5)


async def shutdown() -> None:
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
    for task in list(_tasks):
        task.cancel()
