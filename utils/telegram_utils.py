"""Telegram utility functions."""

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from logging_config import get_logger

logger = get_logger(__name__)


async def safe_callback_answer(
    callback: CallbackQuery,
    text: str | None = None,
    show_alert: bool = False,
    url: str | None = None,
    cache_time: int | None = None,
) -> bool:
    """
    Safely answer a callback query, ignoring 'query is too old' errors.
    
    Args:
        callback: The callback query to answer.
        text: Text of the notification. If not specified, nothing will be shown to the user, 0-200 characters.
        show_alert: If true, an alert will be shown by the client instead of a notification at the top of the chat screen. Defaults to false.
        url: URL that will be opened by the user's client. If you have created a Game and accepted the conditions via @BotFather, specify the URL that opens your game - note that this will not work if the query was sent from a top-level message.
        cache_time: The maximum amount of time in seconds that the result of the callback query may be cached client-side. Telegram apps will support caching starting in version 3.14. Defaults to 0.
        
    Returns:
        True if successful, False if ignored (expired) or failed.
    """
    try:
        await callback.answer(
            text=text,
            show_alert=show_alert,
            url=url,
            cache_time=cache_time,
        )
        return True
    except TelegramBadRequest as e:
        error_text = str(e)
        if "query is too old" in error_text or "query ID is invalid" in error_text:
            logger.warning(f"Ignoring expired callback query: {error_text}")
            return False
        logger.error(f"TelegramBadRequest in callback answer: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error in callback answer: {e}", exc_info=True)
        return False
