# scheduler/scheduler.py

"""
APScheduler setup — schedules selector + sender jobs for both slots.

Used by bot/main.py:
    from scheduler.scheduler import scheduler, setup_jobs, dump_jobs, shutdown_scheduler
    setup_jobs(bot)
    scheduler.start()
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MISSED,
)

from config.settings import settings
from db.model import Slot

from scheduler.selector_job import run as selector_run
from scheduler.sender_job import run as sender_run


logger = logging.getLogger(__name__)


# ---------- Tunables ----------
SELECTOR_LEAD_MINUTES = 30      # selector runs this many min before sender
MISFIRE_GRACE_SECONDS = 300     # 5 min grace if server was briefly down


# ---------- Singleton ----------
scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)


# =========================================================
# Helpers
# =========================================================
def _parse_hhmm(value: str) -> tuple[int, int]:
    """'07:00' -> (7, 0)"""
    h, m = value.strip().split(":")
    return int(h), int(m)


def _subtract_minutes(hour: int, minute: int, delta: int) -> tuple[int, int]:
    """Subtract `delta` minutes, wrapping across midnight if needed."""
    total = (hour * 60 + minute - delta) % (24 * 60)
    return total // 60, total % 60


# =========================================================
# Job wrappers (error-isolated)
# =========================================================
async def _run_selector(slot: Slot) -> None:
    label = f"Selector[{slot.value}]"
    logger.info("%s: job started", label)
    try:
        summary = await selector_run(slot)
        logger.info(
            "%s: done — active=%d, selected=%d, writes=%d, skipped=%d, no_candidate=%d",
            label,
            summary.get("active_buckets", 0),
            summary.get("selected", 0),
            summary.get("redis_writes", 0),
            summary.get("skipped_already", 0),
            summary.get("no_candidate", 0),
        )
        errors = summary.get("errors") or []
        if errors:
            logger.error("%s: %d error(s): %s", label, len(errors), errors[:3])
    except Exception:
        logger.exception("%s: crashed unexpectedly", label)


async def _run_sender(slot: Slot, bot: Bot) -> None:
    label = f"Sender[{slot.value}]"
    logger.info("%s: job started", label)
    try:
        summary = await sender_run(slot, bot=bot)
        logger.info(
            "%s: done — users=%d, sent=%d, skipped=%d, blocked=%d, failed=%d",
            label,
            summary.get("users_fetched", 0),
            summary.get("sent", 0),
            summary.get("skipped_no_question", 0),
            summary.get("blocked", 0),
            summary.get("failed", 0),
        )
    except Exception:
        logger.exception("%s: crashed unexpectedly", label)


# =========================================================
# APScheduler event listeners
# =========================================================
def _on_job_executed(event: Any) -> None:
    logger.info("APScheduler: job '%s' executed", event.job_id)


def _on_job_error(event: Any) -> None:
    logger.error(
        "APScheduler: job '%s' raised %s: %s",
        event.job_id, type(event.exception).__name__, event.exception,
    )


def _on_job_missed(event: Any) -> None:
    logger.warning("APScheduler: job '%s' MISSED its run time", event.job_id)


# =========================================================
# Setup jobs
# =========================================================
def setup_jobs(bot: Bot) -> None:
    """Register the 4 daily jobs on the global scheduler."""

    m_h, m_m = _parse_hhmm(settings.MORNING_SEND_TIME)
    e_h, e_m = _parse_hhmm(settings.EVENING_SEND_TIME)

    ms_h, ms_m = _subtract_minutes(m_h, m_m, SELECTOR_LEAD_MINUTES)
    es_h, es_m = _subtract_minutes(e_h, e_m, SELECTOR_LEAD_MINUTES)

    # --- Morning selector ---
    scheduler.add_job(
        _run_selector,
        CronTrigger(hour=ms_h, minute=ms_m, timezone=settings.TIMEZONE),
        args=[Slot.morning],
        id="selector_morning",
        replace_existing=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
        coalesce=True,
        max_instances=1,
    )
    # --- Morning sender ---
    scheduler.add_job(
        _run_sender,
        CronTrigger(hour=m_h, minute=m_m, timezone=settings.TIMEZONE),
        args=[Slot.morning, bot],
        id="sender_morning",
        replace_existing=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
        coalesce=True,
        max_instances=1,
    )

    # --- Evening selector ---
    scheduler.add_job(
        _run_selector,
        CronTrigger(hour=es_h, minute=es_m, timezone=settings.TIMEZONE),
        args=[Slot.evening],
        id="selector_evening",
        replace_existing=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
        coalesce=True,
        max_instances=1,
    )
    # --- Evening sender ---
    scheduler.add_job(
        _run_sender,
        CronTrigger(hour=e_h, minute=e_m, timezone=settings.TIMEZONE),
        args=[Slot.evening, bot],
        id="sender_evening",
        replace_existing=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
        coalesce=True,
        max_instances=1,
    )

    # --- Event listeners ---
    scheduler.add_listener(_on_job_executed, EVENT_JOB_EXECUTED)
    scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
    scheduler.add_listener(_on_job_missed, EVENT_JOB_MISSED)

    logger.info(
        "Scheduler configured — morning: selector@%02d:%02d, sender@%02d:%02d | "
        "evening: selector@%02d:%02d, sender@%02d:%02d (%s)",
        ms_h, ms_m, m_h, m_m,
        es_h, es_m, e_h, e_m,
        settings.TIMEZONE,
    )


def dump_jobs() -> None:
    """Print all scheduled jobs — useful on startup."""
    logger.info("Registered jobs:")
    for job in scheduler.get_jobs():
        logger.info(
            "  • %-18s next_run=%s",
            job.id, getattr(job, "next_run_time", "—"),
        )


# =========================================================
# Shutdown
# =========================================================
def shutdown_scheduler(wait: bool = False) -> None:
    if scheduler.running:
        scheduler.shutdown(wait=wait)
        logger.info("Scheduler stopped.")