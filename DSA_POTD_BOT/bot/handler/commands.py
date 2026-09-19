# bot/handlers/commands.py

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func

from db.model import User, User_Question_Log, Log_Status
from db.session import AsyncSessionLocal

from bot.keyboards.onboarding_kb import year_kb
from bot.handler.onboarding import Onboarding

logger = logging.getLogger(__name__)
router = Router(name="commands")


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext) -> None:
    tg_user = message.from_user
    if tg_user is None:
        return

    tg_id = tg_user.id
    first_name = tg_user.first_name or "there"

    logger.info("Received /start from tg_id=%s username=%s", tg_id, tg_user.username)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.telegram_id == tg_id)
        )
        existing = result.scalar_one_or_none()

    if existing is not None:
        await state.clear()
        await message.answer(
            f"Welcome back, {first_name}! 👋\n\n"
            f"Your profile:\n"
            f"  • Year: <b>{existing.year.value if existing.year else '—'}</b>\n"
            f"  • Org type: <b>{existing.org_type.value if existing.org_type else '—'}</b>\n"
            f"  • Level: <b>{existing.level.value if existing.level else '—'}</b>\n"
            f"  • Status: <b>{existing.status.value if existing.status else '—'}</b>\n\n"
            f"Use /stats to see your progress."
        )
        logger.info("Returning user tg_id=%s", tg_id)
        return

    await state.set_state(Onboarding.year)
    await message.answer(
        f"Hi {first_name}! 👋\n\n"
        f"Welcome to <b>DSA POTD Bot</b>.\n\n"
        f"Let's set up your profile in 3 quick steps.\n\n"
        f"<b>Step 1/3 — Which year are you in?</b>",
        reply_markup=year_kb(),
    )
    logger.info("New user tg_id=%s — onboarding started (step 1)", tg_id)


@router.message(Command("stats"))
async def stats_handler(message: Message) -> None:
    tg_user = message.from_user
    if tg_user is None:
        return

    async with AsyncSessionLocal() as db:
        user = (await db.execute(
            select(User).where(User.telegram_id == tg_user.id)
        )).scalar_one_or_none()

        if user is None:
            await message.answer("Please /start first to set up your profile.")
            return

        solved = (await db.execute(
            select(func.count()).select_from(User_Question_Log).where(
                User_Question_Log.user_id == user.id,
                User_Question_Log.status == Log_Status.solved,
            )
        )).scalar() or 0

        skipped = (await db.execute(
            select(func.count()).select_from(User_Question_Log).where(
                User_Question_Log.user_id == user.id,
                User_Question_Log.status == Log_Status.skipped,
            )
        )).scalar() or 0

        pending = (await db.execute(
            select(func.count()).select_from(User_Question_Log).where(
                User_Question_Log.user_id == user.id,
                User_Question_Log.status == Log_Status.pending,
            )
        )).scalar() or 0

    total = solved + skipped
    rate = f"{(solved / total * 100):.0f}%" if total else "—"

    await message.answer(
        f"📊 <b>Your Stats</b>\n\n"
        f"  • Solved     : <b>{solved}</b>\n"
        f"  • Skipped    : <b>{skipped}</b>\n"
        f"  • Pending    : <b>{pending}</b>\n"
        f"  • Solve rate : <b>{rate}</b>"
    )
    logger.info("Stats sent to tg_id=%s (solved=%s, skipped=%s)", tg_user.id, solved, skipped)