from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

from datetime import date, timedelta
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import redis.asyncio as aioredis

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramBadRequest,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.model import User, Status, Slot
from db.session import AsyncSessionLocal, engine
from bot.keyboards.question_kb import solved_skip_kb

logger = logging.getLogger(__name__)

TRIAL_DAYS = settings.TRIAL_DAYS
SEND_RATE_SLEEP = 0.05
MESSAGE_MAX_LENGTH = 4000


def _is_eligible(user: User, today: date) -> bool:
    if user.status == Status.inactive:
        return False
    if user.status == Status.active:
        return True
    if user.status == Status.trial:
        if user.trial_start is None:
            return False
        return user.trial_start + timedelta(days=TRIAL_DAYS) >= today
    return False


async def _get_eligible_users(db: AsyncSession) -> list[User]:
    result = await db.execute(select(User))
    all_users = result.scalars().all()
    today = date.today()
    eligible = [u for u in all_users if _is_eligible(u, today)]
    logger.info("Eligible users: %d (of %d total)", len(eligible), len(all_users))
    return eligible


async def _get_question_from_redis(
    redis_client: aioredis.Redis,
    bucket_key: str,
    slot: Slot,
) -> dict[str, Any] | None:
    key = f"bucket:{bucket_key}:{slot.value}"
    raw = await redis_client.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("Bad JSON in Redis key %s: %s", key, e)
        return None


async def _get_or_create_question(
    db: AsyncSession,
    redis_client: aioredis.Redis,
    bucket_key: str,
    slot: Slot,
    user: User,
) -> dict[str, Any] | None:
    q = await _get_question_from_redis(redis_client, bucket_key, slot)
    if q is not None:
        return q

    logger.info("Redis miss %s/%s — selecting on-the-fly", bucket_key, slot.value)

    from scheduler.selector_job import (
        _level_to_difficulty,
        _get_recent_question_ids,
        _pick_question,
        _write_redis,
        _log_daily,
        SLOT_SOURCE,
    )

    source = SLOT_SOURCE[slot]
    difficulty = _level_to_difficulty(user.level)
    recent_ids = await _get_recent_question_ids(db, bucket_key, slot)
    picked = await _pick_question(db, difficulty, source, recent_ids)

    if picked is None:
        logger.warning(
            "No candidate for %s/%s (diff=%s, src=%s)",
            bucket_key, slot.value, difficulty.value, source.value,
        )
        return None

    redis_key = f"bucket:{bucket_key}:{slot.value}"
    await _write_redis(redis_client, redis_key, picked)
    await _log_daily(db, bucket_key, slot, picked.id)
    await db.commit()

    logger.info(
        "Lazy-selected for %s/%s -> q.id=%s (%s)",
        bucket_key, slot.value, picked.id, picked.title,
    )
    return await _get_question_from_redis(redis_client, bucket_key, slot)


def _format_message(question: dict[str, Any], slot: Slot) -> str:
    greeting = "Good morning" if slot == Slot.morning else "Good evening"

    title = question.get("title") or "Untitled"
    difficulty = question.get("difficulty") or "—"
    source = (question.get("source") or "").capitalize() or "—"
    url = question.get("url") or ""
    tags = question.get("tags") or []
    rating = question.get("rating")

    tags_line = ", ".join(tags) if tags else "—"

    lines = [
        f"🔔 <b>{greeting}!</b> Here's your problem of the day:",
        "",
        f"📌 <b>{title}</b>",
        f"📊 Difficulty: <b>{difficulty}</b>",
        f"🏷️ Tags: {tags_line}",
        f"🎯 Source: <b>{source}</b>",
    ]

    if rating:
        lines.append(f"⭐ Rating: <b>{rating}</b>")

    lines.append("")
    if url:
        lines.append(f"👉 {url}")

    lines.append("")
    lines.append("Solve it and let me know! 💪")

    text = "\n".join(lines)
    if len(text) > MESSAGE_MAX_LENGTH:
        text = text[: MESSAGE_MAX_LENGTH - 3] + "..."
    return text


def _create_bot() -> Bot:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise RuntimeError("Telegram bot token not found in settings")
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def _send_to_user(bot: Bot, tg_id: int, text: str, reply_markup=None) -> str:
    try:
        await bot.send_message(chat_id=tg_id, text=text, reply_markup=reply_markup)
        return "sent"
    except TelegramForbiddenError:
        logger.info("User %s blocked the bot — skipping", tg_id)
        return "blocked"
    except TelegramRetryAfter as e:
        logger.warning("Rate limited, retry after %ss", e.retry_after)
        await asyncio.sleep(e.retry_after)
        try:
            await bot.send_message(chat_id=tg_id, text=text, reply_markup=reply_markup)
            return "sent"
        except Exception as e2:
            logger.error("Retry failed for %s: %s", tg_id, e2)
            return "failed"
    except TelegramBadRequest as e:
        logger.warning("Bad request for %s: %s", tg_id, e)
        return "bad_request"
    except Exception as e:
        logger.exception("Send failed for %s: %s", tg_id, e)
        return "failed"


async def run(slot: Slot, bot: Bot | None = None) -> dict[str, Any]:
    summary = {
        "slot": slot.value,
        "users_fetched": 0,
        "sent": 0,
        "skipped_no_question": 0,
        "blocked": 0,
        "bad_request": 0,
        "failed": 0,
    }

    owns_bot = bot is None
    if owns_bot:
        bot = _create_bot()

    redis_client: aioredis.Redis | None = None

    try:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )

        async with AsyncSessionLocal() as db:
            users = await _get_eligible_users(db)
            summary["users_fetched"] = len(users)

            if not users:
                logger.info("No eligible users for %s slot", slot.value)
                return summary

            bucket_to_text: dict[str, str | None] = {}
            bucket_to_q: dict[str, dict[str, Any] | None] = {}

            for user in users:
                try:
                    bucket_key = (
                        f"{user.year.name}_{user.org_type.name}_{user.level.name}"
                    )

                    if bucket_key not in bucket_to_text:
                        q = await _get_or_create_question(
                            db, redis_client, bucket_key, slot, user,
                        )
                        bucket_to_q[bucket_key] = q
                        bucket_to_text[bucket_key] = (
                            _format_message(q, slot) if q else None
                        )

                    text = bucket_to_text[bucket_key]
                    if text is None:
                        summary["skipped_no_question"] += 1
                        logger.warning(
                            "No question for bucket=%s slot=%s",
                            bucket_key, slot.value,
                        )
                        continue

                    q = bucket_to_q.get(bucket_key)
                    markup = solved_skip_kb(q["id"]) if q and q.get("id") else None

                    result = await _send_to_user(
                        bot, user.telegram_id, text, reply_markup=markup,
                    )

                    if result == "sent":
                        summary["sent"] += 1
                    elif result == "blocked":
                        summary["blocked"] += 1
                    elif result == "bad_request":
                        summary["bad_request"] += 1
                    else:
                        summary["failed"] += 1

                    await asyncio.sleep(SEND_RATE_SLEEP)

                except Exception as e:
                    summary["failed"] += 1
                    logger.exception(
                        "Sender error for tg_id=%s: %s", user.telegram_id, e,
                    )

        logger.info(
            "Sender done (%s): sent=%d, skipped=%d, blocked=%d, failed=%d",
            slot.value, summary["sent"], summary["skipped_no_question"],
            summary["blocked"], summary["failed"],
        )

    finally:
        if redis_client is not None:
            await redis_client.aclose()
        if owns_bot and bot is not None:
            await bot.session.close()

    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send today's POTD message.")
    parser.add_argument(
        "--slot",
        choices=["morning", "evening"],
        required=True,
        help="Which slot to send.",
    )
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()

    try:
        slot = Slot(args.slot)
    except ValueError:
        print(f"Invalid Slot : {args.slot}")
        return -1

    try:
        summary = await run(slot)

        print(f"\n=== Sender Summary ({summary['slot']}) ===")
        print(f"  Users fetched       : {summary['users_fetched']}")
        print(f"  Sent                : {summary['sent']}")
        print(f"  Skipped (no question): {summary['skipped_no_question']}")
        print(f"  Blocked by user     : {summary['blocked']}")
        print(f"  Bad request         : {summary['bad_request']}")
        print(f"  Failed              : {summary['failed']}")

        return 0 if summary["failed"] == 0 else 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sys.exit(asyncio.run(_main()))