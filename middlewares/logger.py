"""Middleware for logging messages to the database."""

import asyncio
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from database.models import MessageLog
from database.session import get_session
from logging_config import get_logger

logger = get_logger(__name__)


async def _log_message(user_id: int, chat_id: int, content: str) -> None:
    """Fire-and-forget async task to log a message to the database."""
    try:
        async for session in get_session():
            try:
                message_log = MessageLog(
                    user_id=user_id,
                    chat_id=chat_id,
                    content=content[:500],  # Truncate to 500 chars
                )
                session.add(message_log)
                # Session will be committed automatically by get_session()
            except Exception as e:
                logger.error(
                    "Error logging message",
                    user_id=user_id,
                    chat_id=chat_id,
                    error=str(e),
                    exc_info=True,
                )
            finally:
                break
    except Exception as e:
        logger.error(
            "Error in message logging task",
            user_id=user_id,
            chat_id=chat_id,
            error=str(e),
            exc_info=True,
        )


class MessageLoggingMiddleware(BaseMiddleware):
    """Middleware to log text messages in group chats."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        """
        Process message and log text messages.

        Args:
            handler: Next handler in the chain.
            event: Telegram message event.
            data: Middleware data dictionary.
        """
        # Only process text messages in group chats
        if event.text and event.chat:
            chat = event.chat

            # Only log group/supergroup chats
            if chat.type in ("group", "supergroup") and event.from_user:
                # Skip commands (starting with /)
                if not event.text.startswith("/"):
                    # Fire-and-forget async task
                    asyncio.create_task(
                        _log_message(
                            user_id=event.from_user.id,
                            chat_id=chat.id,
                            content=event.text,
                        )
                    )

        return await handler(event, data)
