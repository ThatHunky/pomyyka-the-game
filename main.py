"""Main entry point for the Telegram bot application."""

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from database.session import init_db
from handlers.admin import router as admin_router
from handlers.admin_autocard import router as admin_autocard_router
from handlers.drops import router as drops_router
from handlers.player import router as player_router
from logging_config import setup_logging, get_logger
from middlewares.group_tracker import ChatTrackingMiddleware
from middlewares.logger import MessageLoggingMiddleware
from services import DropScheduler
from services.cleanup import CleanupService

logger = get_logger(__name__)


async def main() -> None:
    """Initialize and start the bot application."""
    # Setup logging
    setup_logging()

    logger.info("Starting bot application")
    
    # Log admin configuration (without exposing IDs for security)
    admin_count = len(settings.admin_user_ids)
    logger.info(
        "Admin configuration loaded",
        admin_count=admin_count,
        admin_enabled=settings.is_admin_enabled,
    )

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Initialize bot and dispatcher
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher()

    # Register middlewares (order matters - ChatTrackingMiddleware runs first)
    dp.message.middleware(ChatTrackingMiddleware())
    dp.message.middleware(MessageLoggingMiddleware())
    logger.info("Middlewares registered")

    # Register routers
    dp.include_router(admin_router)
    dp.include_router(admin_autocard_router)
    dp.include_router(drops_router)
    dp.include_router(player_router)
    logger.info("Routers registered")

    # Initialize and start schedulers
    drop_scheduler = DropScheduler(bot, interval_minutes=10, drop_chance=0.05)
    await drop_scheduler.start()
    logger.info("Drop scheduler started")

    cleanup_service = CleanupService(retention_days=7)
    await cleanup_service.start()
    logger.info("Cleanup service started")

    # Delete webhook if bot was previously running on webhook mode
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted (if existed)")
    except Exception as e:
        logger.warning("Failed to delete webhook (may not exist)", error=str(e))

    try:
        # Start polling
        logger.info("Starting bot polling")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.error("Error during bot polling", error=str(e), exc_info=True)
        raise
    finally:
        # Cleanup
        await drop_scheduler.stop()
        await cleanup_service.stop()
        await bot.session.close()
        logger.info("Bot shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
