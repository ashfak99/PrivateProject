# scheduler/selector_job.py

from __future__ import annotations

import argparse
import logging
import json
import asyncio
import random
import sys
import os

from datetime import date, timedelta
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.model import (
    User, Questions, Daily_Question_Log,
    Year, Org_type, Level, Source, Difficulty, Slot,
)
from db.session import AsyncSessionLocal, engine


logger = logging.getLogger(__name__)


DEDUP_DAYS = 14
REDIS_TTL_SECONDS = 24 * 60 * 60
CANDIDATE_LIMIT = 200

SLOT_SOURCE: dict[Slot, Source] = {
    Slot.morning: Source.leetcode,
    Slot.evening: Source.codeforces,
}


# =========================================================
# 1. Active buckets
# =========================================================
async def _get_active_buckets(db: AsyncSession) -> set[tuple[Year, Org_type, Level]]:
    result = await db.execute(
        select(User.year, User.org_type, User.level).distinct()
    )
    bucket = {(row[0], row[1], row[2]) for row in result.all()}
    logger.info("Found %d active bucket(s) with users", len(bucket))
    return bucket


# =========================================================
# 2. Level -> Difficulty
# =========================================================
def _level_to_difficulty(level: Level) -> Difficulty:
    if level == Level.beginner:
        return Difficulty.easy
    if level == Level.pro:
        return Difficulty.hard
    return Difficulty.medium


# =========================================================
# 3. Bucket key
# =========================================================
def _bucket_key(year: Year, org: Org_type, level: Level) -> str:
    return f"{year.name}_{org.name}_{level.name}"


# =========================================================
# 4. Recent question ids (dedup)
# =========================================================
async def _get_recent_question_ids(
    db: AsyncSession, bucket_key: str, slot: Slot,
) -> list[int]:
    cutoff = date.today() - timedelta(days=DEDUP_DAYS)
    stmt = select(Daily_Question_Log.question_id).where(
        Daily_Question_Log.bucket_key == bucket_key,
        Daily_Question_Log.slot == slot,
        Daily_Question_Log.date >= cutoff,
    )
    rows = (await db.execute(stmt)).all()
    return [r[0] for r in rows]


# =========================================================
# 5. Pick a question
# =========================================================
async def _pick_question(
    db: AsyncSession,
    difficulty: Difficulty,
    source: Source,
    recent_ids: list[int],
) -> Questions | None:
    stmt = select(Questions).where(
        Questions.difficulty == difficulty,
        Questions.source == source,
    )
    if recent_ids:
        stmt = stmt.where(Questions.id.notin_(recent_ids))
    stmt = stmt.limit(CANDIDATE_LIMIT)

    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return None
    return random.choice(rows)


# =========================================================
# 6. Redis write
# =========================================================
async def _write_redis(
    redis_client: aioredis.Redis,
    key: str,
    question: Questions,
) -> None:
    payload = {
        "id": question.id,
        "title": question.title,
        "url": question.url,
        "difficulty": question.difficulty.value if question.difficulty else None,
        "tags": question.tags,
        "source": question.source.value if question.source else None,
        "rating": question.rating,
    }
    await redis_client.set(key, json.dumps(payload), ex=REDIS_TTL_SECONDS)


# =========================================================
# 7. Log to daily_question_log
# =========================================================
async def _log_daily(
    db: AsyncSession, bucket_key: str, slot: Slot, question_id: int,
) -> None:
    entry = Daily_Question_Log(
        bucket_key=bucket_key,
        question_id=question_id,
        slot=slot,
        date=date.today(),
    )
    db.add(entry)


async def _already_selected(
    db: AsyncSession, bucket_key: str, slot: Slot,
) -> bool:
    stmt = select(Daily_Question_Log.id).where(
        Daily_Question_Log.bucket_key == bucket_key,
        Daily_Question_Log.slot == slot,
        Daily_Question_Log.date == date.today(),
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


# =========================================================
# 8. NEW: Slot-specific runner (scheduler uses this)
# =========================================================
async def run(
    slot: Slot,
    redis_client: aioredis.Redis | None = None,
) -> dict[str, Any]:
    """
    Select one question per active bucket for the given slot only.
    Used by scheduler/scheduler.py.
    If redis_client is None, creates its own (and closes it after).
    """
    summary = {
        "slot": slot.value,
        "active_buckets": 0,
        "selected": 0,
        "redis_writes": 0,
        "skipped_already": 0,
        "no_candidate": 0,
        "errors": [],
    }

    owns_redis = redis_client is None
    if owns_redis:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )

    try:
        async with AsyncSessionLocal() as db:
            active = await _get_active_buckets(db)
            summary["active_buckets"] = len(active)

            if not active:
                logger.info("[%s] No active buckets — nothing to select", slot.value)
                return summary

            for (year, org, level) in active:
                bucket_key = _bucket_key(year, org, level)

                try:
                    if await _already_selected(db, bucket_key, slot):
                        summary["skipped_already"] += 1
                        logger.info(
                            "[%s] %s already selected — skip",
                            slot.value, bucket_key,
                        )
                        continue

                    source = SLOT_SOURCE[slot]
                    difficulty = _level_to_difficulty(level)
                    recent_ids = await _get_recent_question_ids(db, bucket_key, slot)
                    q = await _pick_question(db, difficulty, source, recent_ids)

                    if q is None:
                        summary["no_candidate"] += 1
                        logger.warning(
                            "[%s] No candidate for %s (diff=%s, src=%s)",
                            slot.value, bucket_key,
                            difficulty.value, source.value,
                        )
                        continue

                    redis_key = f"bucket:{bucket_key}:{slot.value}"
                    await _write_redis(redis_client, redis_key, q)
                    summary["redis_writes"] += 1

                    await _log_daily(db, bucket_key, slot, q.id)
                    summary["selected"] += 1

                    logger.info(
                        "[%s] %s -> q.id=%s (%s)",
                        slot.value, bucket_key, q.id, q.title,
                    )

                except Exception as e:
                    msg = f"{bucket_key}: {type(e).__name__}: {e}"
                    logger.exception("[%s] Selector error: %s", slot.value, msg)
                    summary["errors"].append(msg)

            await db.commit()

    finally:
        if owns_redis and redis_client is not None:
            await redis_client.aclose()

    return summary


# =========================================================
# 9. Legacy: run both slots (kept for backward compatibility)
# =========================================================
async def run_selector_job() -> dict[str, Any]:
    """Legacy: runs BOTH slots sequentially. Prefer run(slot)."""
    results: dict[str, Any] = {}
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    try:
        for slot in Slot:
            results[slot.value] = await run(slot, redis_client=redis_client)
    finally:
        await redis_client.aclose()

    # Flatten summary so existing CLI still shows totals
    return {
        "active_buckets": results.get("morning", {}).get("active_buckets", 0),
        "selected": sum(r.get("selected", 0) for r in results.values()),
        "redis_writes": sum(r.get("redis_writes", 0) for r in results.values()),
        "skipped_already": sum(r.get("skipped_already", 0) for r in results.values()),
        "no_candidate": sum(r.get("no_candidate", 0) for r in results.values()),
        "errors": [e for r in results.values() for e in r.get("errors", [])],
    }


# =========================================================
# Entrypoint — CLI
# =========================================================
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run selector for a slot.")
    parser.add_argument(
        "--slot",
        choices=["morning", "evening", "both"],
        default="both",
        help="Which slot to select for (default: both).",
    )
    return parser.parse_args()


async def _main() -> int:
    try:
        args = _parse_args()

        if args.slot == "both":
            summary = await run_selector_job()
            print("\n=== Selector Summary (both slots) ===")
            print(f"  Active buckets   : {summary['active_buckets']}")
            print(f"  Selected         : {summary['selected']}")
            print(f"  Redis writes     : {summary['redis_writes']}")
            print(f"  Skipped (already): {summary['skipped_already']}")
            print(f"  No candidate     : {summary['no_candidate']}")
            if summary["errors"]:
                print(f"\n  Errors: {len(summary['errors'])}")
                for err in summary["errors"][:10]:
                    print(f"    - {err}")
            return 0 if not summary["errors"] else 1

        slot = Slot(args.slot)
        summary = await run(slot)

        print(f"\n=== Selector Summary ({summary['slot']}) ===")
        print(f"  Active buckets   : {summary['active_buckets']}")
        print(f"  Selected         : {summary['selected']}")
        print(f"  Redis writes     : {summary['redis_writes']}")
        print(f"  Skipped (already): {summary['skipped_already']}")
        print(f"  No candidate     : {summary['no_candidate']}")
        if summary["errors"]:
            print(f"\n  Errors: {len(summary['errors'])}")
            for err in summary["errors"][:10]:
                print(f"    - {err}")
        return 0 if not summary["errors"] else 1

    finally:
        await engine.dispose()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sys.exit(asyncio.run(_main()))