from __future__ import annotations

import logging
from datetime import date

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery

from sqlalchemy import select

from db.model import User, Year, Org_type, Level, Status
from db.session import AsyncSessionLocal
from bot.keyboards.onboarding_kb import year_kb, org_type_kb, level_kb

logger = logging.getLogger(__name__)

router = Router(name="onboarding")


class Onboarding(StatesGroup):
    year = State()
    org_type = State()
    level = State()


# =========================================================
# STEP 1: YEAR
# =========================================================
@router.callback_query(F.data.startswith("onboard:year:"))
async def cb_year(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.data is None or cb.from_user is None:
        await cb.answer()
        return

    if cb.message is None:
        await cb.answer("Something went wrong. Try /start")
        return

    year_name = cb.data.split(":", 2)[2]
    try:
        year_enum = Year[year_name]
    except KeyError:
        await cb.answer("Invalid year")
        return

    await state.update_data(year=year_enum.name)
    await state.set_state(Onboarding.org_type)

    logger.info("cb_year: tg_id=%s year=%s", cb.from_user.id, year_enum.name)

    try:
        await cb.message.edit_text(
            "Got it! 👌\n\n<b>Which type of organisation are you in?</b>",
            reply_markup=org_type_kb(),
        )
    except Exception as e:
        logger.warning("cb_year edit_text failed: %s", e)

    await cb.answer()


# =========================================================
# STEP 2: ORG TYPE
# =========================================================
@router.callback_query(F.data.startswith("onboard:org:"))
async def cb_org(cb: CallbackQuery, state: FSMContext) -> None:
    if cb.data is None or cb.from_user is None:
        await cb.answer()
        return

    if cb.message is None:
        await cb.answer("Something went wrong. Try /start")
        return

    data = await state.get_data()
    if "year" not in data:
        await cb.answer("Please start over with /start")
        return

    org_name = cb.data.split(":", 2)[2]
    try:
        org_enum = Org_type[org_name]
    except KeyError:
        await cb.answer("Invalid option")
        return

    # ✅ FIX: key lowercase 'org_type' (pehle 'Org_type' tha — yahi asli bug tha)
    await state.update_data(org_type=org_enum.name)
    await state.set_state(Onboarding.level)

    logger.info("cb_org: tg_id=%s org_type=%s", cb.from_user.id, org_enum.name)

    try:
        await cb.message.edit_text(
            "<b>How would you rate your current DSA level?</b>",
            reply_markup=level_kb(),
        )
    except Exception as e:
        logger.warning("cb_org edit_text failed: %s", e)

    await cb.answer()


# =========================================================
# STEP 3: LEVEL -> DB INSERT
# =========================================================
@router.callback_query(F.data.startswith("onboard:level:"))
async def cb_level(cb: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if cb.data is None or cb.from_user is None:
        await cb.answer()
        return

    if cb.message is None:
        await cb.answer("Something went wrong. Try /start")
        return

    data = await state.get_data()
    logger.info("cb_level state data=%r", data)

    if "year" not in data or "org_type" not in data:
        await cb.answer("Please start over with /start")
        return

    level_name = cb.data.split(":", 2)[2]
    try:
        level_enum = Level[level_name]
    except KeyError:
        await cb.answer("Invalid option")
        return

    tg_id = cb.from_user.id
    year_enum = Year[data["year"]]
    org_enum = Org_type[data["org_type"]]

    new_user = False
    db_error: str | None = None

    try:
        async with AsyncSessionLocal() as db:
            existing = (await db.execute(
                select(User).where(User.telegram_id == tg_id)
            )).scalar_one_or_none()

            if existing is None:
                user = User(
                    telegram_id=tg_id,
                    year=year_enum,
                    org_type=org_enum,
                    level=level_enum,
                    status=Status.trial,
                    trial_start=date.today(),
                    created_at=date.today(),
                )
                db.add(user)
                await db.commit()
                new_user = True
                logger.info(
                    "Onboarded new user tg_id=%s (%s/%s/%s)",
                    tg_id, year_enum.value, org_enum.value, level_enum.value,
                )
            else:
                logger.info("User tg_id=%s already existed — skipped insert", tg_id)
    except Exception as e:
        db_error = f"{type(e).__name__}: {e}"
        logger.exception("DB insert failed for tg_id=%s", tg_id)

    await state.clear()

    if db_error:
        text = (
            "⚠️ Couldn't save your profile.\n\n"
            f"<code>{db_error}</code>\n\n"
            "Please try /start again."
        )
    elif new_user:
        text = (
            "✅ <b>Profile created!</b>\n\n"
            f"  • Year: <b>{year_enum.value}</b>\n"
            f"  • Org type: <b>{org_enum.value}</b>\n"
            f"  • Level: <b>{level_enum.value}</b>\n\n"
            "Your free trial has started. Daily question flow coming soon!"
        )
    else:
        text = "You're already onboarded. Use /start to view your profile."

    try:
        await cb.message.edit_text(text)
    except Exception as e:
        logger.warning("cb_level edit_text failed: %s — sending new message", e)
        await bot.send_message(cb.message.chat.id, text)

    await cb.answer("Saved!" if not db_error else "Error")