
from __future__ import annotations

import logging
from datetime import date

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select

from db.model import User, User_Question_Log, Log_Status
from db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

router = Router(name="callbacks")



async def _handle_action(cb: CallbackQuery, status: Log_Status) -> None:
    if cb.data is None or cb.from_user is None or cb.message is None:
        await cb.answer()
        return

    parts = cb.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        await cb.answer("Invalid action")
        return

    question_id = int(parts[2])
    tg_id = cb.from_user.id

    
    async with AsyncSessionLocal() as db:
        user = (await db.execute(
            select(User).where(User.telegram_id == tg_id)
        )).scalar_one_or_none()

        if user is None:
            await cb.answer("Please /start first")
            return

        existing = (await db.execute(
            select(User_Question_Log).where(
                User_Question_Log.user_id == user.id,
                User_Question_Log.question_id == question_id,
                User_Question_Log.send_at == date.today(),
            )
        )).scalar_one_or_none()

        if existing is not None:
            if existing.status == status:
                await cb.answer(f"Already marked as {status.value}")
                return
            existing.status = status
            await db.commit()
            logger.info("Updated log id=%s -> %s", existing.id, status.value)
        else:
            db.add(User_Question_Log(
                user_id=user.id,
                question_id=question_id,
                send_at=date.today(),
                status=status,
            ))
            await db.commit()
            logger.info(
                "Logged user_id=%s question_id=%s status=%s",
                user.id, question_id, status.value,
            )

    
    try:
        original = cb.message.html_text or cb.message.text or ""
    except Exception:
        original = cb.message.text or ""

    today = date.today().isoformat()

    if status == Log_Status.solved:
        suffix = f"\n\n✅ <b>Marked as solved</b> on {today}. Great job! 🎉"
    else:
        suffix = f"\n\n⏭️ <b>Skipped</b> for today. No worries — try tomorrow! 💪"

    new_text = original + suffix
    if len(new_text) > 4000:
        new_text = new_text[:3997] + "..."

    try:
        await cb.message.edit_text(new_text, reply_markup=None)
    except Exception as e:
        logger.warning("edit_text failed: %s", e)

    await cb.answer("Saved!")



@router.callback_query(F.data.startswith("q:done:"))
async def cb_solved(cb: CallbackQuery) -> None:
    await _handle_action(cb, Log_Status.solved)


@router.callback_query(F.data.startswith("q:skip:"))
async def cb_skipped(cb: CallbackQuery) -> None:
    await _handle_action(cb, Log_Status.skipped)