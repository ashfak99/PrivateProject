# bot/main.py

from __future__ import annotations

import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config.settings import settings
from db.session import engine

from bot.handler import commands, onboarding, callback
from scheduler.scheduler import (
    scheduler, setup_jobs, dump_jobs, shutdown_scheduler,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_bot() -> Bot:
    token = (
        getattr(settings, "TELEGRAM_BOT_TOKEN", None)
        or getattr(settings, "BOT_TOKEN", None)
        or getattr(settings, "TG_BOT_TOKEN", None)
    )
    if not token:
        raise RuntimeError("Telegram bot token not found in settings.")
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(commands.router)
    dp.include_router(onboarding.router)
    dp.include_router(callback.router)
    return dp


async def main() -> None:
    bot = create_bot()
    dp = create_dispatcher()

    # ---- Scheduler ----
    setup_jobs(bot)
    scheduler.start()
    dump_jobs()
    logger.info("Scheduler started.")

    logger.info("Starting bot in polling mode…")
    try:
        await dp.start_polling(bot)
    finally:
        shutdown_scheduler(wait=False)
        await bot.session.close()
        await engine.dispose()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Interrupted by user.")
        sys.exit(0)