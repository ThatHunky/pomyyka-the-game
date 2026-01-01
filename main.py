"""Main entry point for the Telegram bot application."""

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from database.session import init_db
from handlers.drops import router as drops_router
from logging_config import setup_logging, get_logger
from services import DropScheduler

logger = get_logger(__name__)


async def main() -> None:
    """Initialize and start the bot application."""
    # Setup logging
    setup_logging()

    logger.info("Starting bot application")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Initialize bot and dispatcher
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher()

    # Register routers
    dp.include_router(drops_router)
    logger.info("Routers registered")

    # Initialize and start scheduler
    scheduler = DropScheduler(bot, interval_minutes=10, drop_chance=0.05)
    await scheduler.start()
    logger.info("Scheduler started")

    try:
        # Start polling
        logger.info("Starting bot polling")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.error("Error during bot polling", error=str(e), exc_info=True)
        raise
    finally:
        # Cleanup
        await scheduler.stop()
        await bot.session.close()
        logger.info("Bot shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
