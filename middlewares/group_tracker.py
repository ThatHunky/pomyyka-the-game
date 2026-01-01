"""Middleware for tracking group chats."""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from sqlalchemy.dialects.postgresql import insert

from database.models import GroupChat
from database.session import get_session
from logging_config import get_logger

logger = get_logger(__name__)


class ChatTrackingMiddleware(BaseMiddleware):
    """Middleware to track all group and supergroup chats."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        """
        Process message and track group chats.

        Args:
            handler: Next handler in the chain.
            event: Telegram message event.
            data: Middleware data dictionary.
        """
        # Get chat from message
        chat = event.chat

        # Track group/supergroup chats
        if chat and chat.type in ("group", "supergroup"):
            async for session in get_session():
                try:
                    # Use PostgreSQL INSERT ON CONFLICT DO NOTHING
                    stmt = insert(GroupChat).values(
                        chat_id=chat.id,
                        title=chat.title,
                        is_active=True,
                    )
                    stmt = stmt.on_conflict_do_nothing(index_elements=["chat_id"])

                    await session.execute(stmt)
                    # Session will be committed automatically by get_session()

                    logger.debug(
                        "Group chat tracked",
                        chat_id=chat.id,
                        chat_type=chat.type,
                        title=chat.title,
                    )
                except Exception as e:
                    logger.error(
                        "Error tracking group chat",
                        chat_id=chat.id,
                        error=str(e),
                        exc_info=True,
                    )
                finally:
                    break

        return await handler(event, data)
