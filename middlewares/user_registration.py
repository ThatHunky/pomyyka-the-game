"""Middleware for auto-registering users on any interaction."""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.types import BotCommandScopeChat, CallbackQuery, Message, TelegramObject
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from database.models import User
from database.session import get_session
from logging_config import get_logger
from utils.commands import get_all_commands, is_admin

logger = get_logger(__name__)


class UserRegistrationMiddleware(BaseMiddleware):
    """Middleware to automatically register users on any interaction."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """
        Process update and auto-register user if needed.

        Args:
            handler: Next handler in the chain.
            event: Telegram event (Message or CallbackQuery).
            data: Middleware data dictionary.
        """
        # Extract user from different event types
        user = None
        if isinstance(event, Message) and event.from_user:
            user = event.from_user
        elif isinstance(event, CallbackQuery) and event.from_user:
            user = event.from_user

        # Auto-register user if found
        if user:
            async for session in get_session():
                try:
                    # Check if user exists
                    user_stmt = select(User).where(User.telegram_id == user.id)
                    result = await session.execute(user_stmt)
                    db_user = result.scalar_one_or_none()

                    # Register if not exists
                    if not db_user:
                        # Use PostgreSQL INSERT ON CONFLICT DO NOTHING for thread safety
                        stmt = insert(User).values(
                            telegram_id=user.id,
                            username=user.username,
                            balance=0,
                        )
                        stmt = stmt.on_conflict_do_nothing(index_elements=["telegram_id"])

                        await session.execute(stmt)
                        await session.commit()

                        logger.info(
                            "User auto-registered",
                            user_id=user.id,
                            username=user.username,
                        )
                except Exception as e:
                    logger.error(
                        "Error auto-registering user",
                        user_id=user.id if user else None,
                        error=str(e),
                        exc_info=True,
                    )
                finally:
                    break

            # Set admin commands if user is admin
            if is_admin(user.id):
                try:
                    bot: Bot = data.get("bot")
                    if bot:
                        await bot.set_my_commands(
                            commands=get_all_commands(),
                            scope=BotCommandScopeChat(chat_id=user.id),
                        )
                        logger.debug(
                            "Admin commands set for user",
                            user_id=user.id,
                        )
                except Exception as e:
                    logger.warning(
                        "Failed to set admin commands",
                        user_id=user.id,
                        error=str(e),
                    )

        return await handler(event, data)
