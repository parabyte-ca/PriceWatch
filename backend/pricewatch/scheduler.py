"""APScheduler jobs: a 60-second tick dispatches due source checks with concurrency limits."""

import asyncio
import logging
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import or_, select

from .db import session_scope
from .models import Item, Purchase, SourceLink
from .services import alerts, events, protection, runtime, settings_store
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
                or_(Item.active.is_(True), Item.id.in_(
                    select(Purchase.item_id).where(Purchase.status.in_(["watching", "claimable"])))),
                SourceLink.status == "confirmed",
                ~SourceLink.url.startswith("manual://"),
                or_(SourceLink.fetch_mode.is_(None), SourceLink.fetch_mode.notin_(["manual", "search"])),
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
        alerts.maybe_send_digest(db)
        from .services import weekly

        weekly.maybe_send(db)
        protection.expire(db)
    except Exception:  # noqa: BLE001
        log.exception("housekeeping failed")
    finally:
        db.close()


_last_backup_day = None


async def nightly_backup() -> None:
    """VACUUM INTO a dated copy at 03:30 local, before the TrueNAS daily snapshot."""
    global _last_backup_day
    from .backup import vacuum_into
    from .config import get_settings

    local = events.local_now()
    if local.hour != 3 or local.minute < 30 or _last_backup_day == local.date():
        return
    if not get_settings().db_url.startswith("sqlite"):
        return
    try:
        path = await asyncio.to_thread(vacuum_into)
        _last_backup_day = local.date()
        log.info("nightly backup", extra={"path": str(path)})
    except Exception:  # noqa: BLE001
        log.exception("nightly backup failed")


async def pre_event_backup() -> None:
    """One extra database copy in the 6 hours before each sale mode starts (kept apart from the nightly rotation)."""
    from .backup import vacuum_into
    from .config import get_settings

    s = get_settings()
    if not s.db_url.startswith("sqlite"):
        return
    db = session_scope()
    try:
        cfg = settings_store.get_all(db)
    finally:
        db.close()
    now = events.local_now()
    for name, start, _end in events.sale_windows(cfg):
        if timedelta(0) <= start - now <= timedelta(hours=6):
            dest = s.data_dir / "backups" / f"pre-{name.lower().replace(' ', '')}-{start:%Y}.sqlite"
            if dest.exists():
                continue
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(vacuum_into, dest, 10_000)
                log.info("pre-event backup", extra={"event": name, "path": str(dest)})
            except Exception:  # noqa: BLE001
                log.exception("pre-event backup failed")


async def order_emails() -> None:
    from .services import emailimport

    if not emailimport.configured():
        return
    db = session_scope()
    try:
        await asyncio.to_thread(emailimport.poll, db)
    except Exception:  # noqa: BLE001
        log.exception("order email import failed")
    finally:
        db.close()


async def rediscover() -> None:
    """Daily search per active item for prices across stores (a few items per run, paced to the monthly limit)."""
    from .services import discovery

    db = session_scope()
    try:
        await discovery.refresh_stale(db, per_run=3)
    except Exception:  # noqa: BLE001
        log.exception("weekly discovery failed")
    finally:
        db.close()


async def deal_feed() -> None:
    from .services import dealfeed

    db = session_scope()
    try:
        await dealfeed.poll(db)
        from .services import rfdthread

        await rfdthread.refresh(db)
    except Exception:  # noqa: BLE001
        log.exception("deal feed failed")
    finally:
        db.close()


async def flyers() -> None:
    from .services import flyers as flyer_service

    db = session_scope()
    try:
        await flyer_service.poll(db)
    except Exception:  # noqa: BLE001
        log.exception("flyer poll failed")
    finally:
        db.close()


def start() -> AsyncIOScheduler:
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(tick, "interval", seconds=60, id="tick", max_instances=1, coalesce=True,
                       next_run_time=utcnow_aware())
    _scheduler.add_job(housekeeping, "interval", minutes=5, id="housekeeping", max_instances=1, coalesce=True)
    _scheduler.add_job(nightly_backup, "interval", minutes=10, id="backup", max_instances=1, coalesce=True)
    _scheduler.add_job(deal_feed, "interval", minutes=15, id="deal_feed", max_instances=1, coalesce=True)
    _scheduler.add_job(flyers, "interval", hours=1, id="flyers", max_instances=1, coalesce=True)
    _scheduler.add_job(rediscover, "interval", hours=2, id="rediscover", max_instances=1, coalesce=True)
    _scheduler.add_job(order_emails, "interval", minutes=10, id="order_emails", max_instances=1, coalesce=True)
    _scheduler.add_job(pre_event_backup, "interval", minutes=15, id="pre_event_backup", max_instances=1, coalesce=True)
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
