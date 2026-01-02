"""Main entry point for the Telegram bot application."""

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommandScopeChat, BotCommandScopeDefault

from config import settings
from database.session import init_db
from handlers.admin import router as admin_router
from handlers.admin_autocard import router as admin_autocard_router
from handlers.battles import router as battles_router
from handlers.drops import router as drops_router
from handlers.inline import router as inline_router
from handlers.player import router as player_router
from handlers.trading import router as trading_router
from logging_config import setup_logging, get_logger
from middlewares.group_tracker import ChatTrackingMiddleware
from middlewares.logger import MessageLoggingMiddleware
from middlewares.user_registration import UserRegistrationMiddleware
from services import DropScheduler
from services.cleanup import CleanupService
from utils.commands import get_admin_commands, get_all_commands, get_player_commands

logger = get_logger(__name__)


async def setup_bot_commands(bot: Bot) -> None:
    """
    Set up bot commands for all users and admins.

    Args:
        bot: Bot instance.
    """
    try:
        # Set default commands for all users (player commands only)
        await bot.set_my_commands(
            commands=get_player_commands(),
            scope=BotCommandScopeDefault(),
        )
        logger.info("Default bot commands set for all users")

        # Set commands for each admin user (player + admin commands)
        admin_commands = get_all_commands()
        for admin_id in settings.admin_user_ids:
            try:
                await bot.set_my_commands(
                    commands=admin_commands,
                    scope=BotCommandScopeChat(chat_id=admin_id),
                )
                logger.debug(
                    "Admin commands set",
                    admin_id=admin_id,
                )
            except Exception as e:
                logger.warning(
                    "Failed to set commands for admin",
                    admin_id=admin_id,
                    error=str(e),
                )

        logger.info(
            "Bot commands setup complete",
            admin_count=len(settings.admin_user_ids),
        )
    except Exception as e:
        logger.error(
            "Error setting up bot commands",
            error=str(e),
            exc_info=True,
        )


async def main() -> None:
    """Initialize and start the bot application."""
    # Setup logging
    setup_logging()

    logger.info("Starting bot application")
    
    # Log admin configuration
    admin_count = len(settings.admin_user_ids)
    logger.info(
        "Admin configuration loaded",
        admin_count=admin_count,
        admin_enabled=settings.is_admin_enabled,
        admin_user_ids=settings.admin_user_ids,
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

    # Register middlewares (order matters)
    # UserRegistrationMiddleware should run first to ensure users are registered
    user_registration = UserRegistrationMiddleware()
    dp.message.middleware(user_registration)
    dp.callback_query.middleware(user_registration)
    dp.message.middleware(ChatTrackingMiddleware())
    dp.message.middleware(MessageLoggingMiddleware())
    logger.info("Middlewares registered")

    # Register routers
    dp.include_router(admin_router)
    dp.include_router(admin_autocard_router)
    dp.include_router(drops_router)
    dp.include_router(inline_router)
    dp.include_router(player_router)
    dp.include_router(trading_router)
    dp.include_router(battles_router)
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

    # Setup bot commands
    await setup_bot_commands(bot)
    logger.info("Bot commands configured")

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
