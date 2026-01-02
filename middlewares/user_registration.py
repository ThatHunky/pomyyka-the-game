"""Middleware for auto-registering users on any interaction."""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.types import BotCommandScopeChat, CallbackQuery, Message, TelegramObject
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database.models import User
from database.session import first_session, get_session
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
        # Extract user (prefer duck-typing to support test doubles)
        user = getattr(event, "from_user", None)

        # Auto-register user if found
        if user:
            async with first_session(get_session()) as session:
                try:
                    # Check if user exists
                    user_stmt = select(User).where(User.telegram_id == user.id)
                    result = await session.execute(user_stmt)
                    db_user = result.scalar_one_or_none()

                    # Register if not exists (cross-dialect; safe for tests on SQLite).
                    if not db_user:
                        session.add(
                            User(
                                telegram_id=user.id,
                                username=user.username,
                                balance=0,
                            )
                        )
                        try:
                            await session.commit()
                        except IntegrityError:
                            # Another concurrent insert won; that's fine.
                            await session.rollback()

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
