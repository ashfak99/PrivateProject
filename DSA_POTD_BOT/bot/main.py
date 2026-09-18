from __future__ import annotations

import asyncio
import sys
import os
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from aiogram import Dispatcher, Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config.settings import settings
from db.session import engine
from bot.handler import commands, onboarding

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_bot() ->Bot:
    token = settings.TELEGRAM_BOT_TOKEN

    if not token:
        raise RuntimeError("Telegram bot token not found. Add TELEGRAM_BOT_TOKEN to config/settings.py / .env")
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

def create_dispatcher()->Dispatcher:
    dp = Dispatcher()
    dp.include_router(commands.router)
    dp.include_router(onboarding.router)
    return dp

async def main()->None:
    bot = create_bot()
    dp=create_dispatcher()

    logger.info("Starting bot in polling mode…")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()
        logger.info("Bot Stopped")

if __name__=="__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Interrup by User.")
        sys.exit(0)