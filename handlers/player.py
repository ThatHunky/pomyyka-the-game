"""Player handlers for user commands."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from database.models import User
from database.session import get_session
from logging_config import get_logger

logger = get_logger(__name__)

router = Router(name="player")


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Handle /start command - register user in the game."""
    user = message.from_user
    if not user:
        return

    async for session in get_session():
        try:
            # Get or create user
            user_stmt = select(User).where(User.telegram_id == user.id)
            result = await session.execute(user_stmt)
            db_user = result.scalar_one_or_none()

            if not db_user:
                db_user = User(
                    telegram_id=user.id,
                    username=user.username,
                    balance=0,
                )
                session.add(db_user)
                await session.commit()

                await message.answer(
                    "🎮 **Ласкаво просимо до Хронік Помийки!**\n\n"
                    "Тепер ти зареєстрований як Сміттяр. Тримайся на зв'язку в чаті, "
                    "бо з часом з'являються аномалії з картками!\n\n"
                    "Тисни кнопку **✋ Хапнути** швидше за інших, щоб отримати картку.",
                    parse_mode="Markdown",
                )

                logger.info(
                    "User registered",
                    user_id=user.id,
                    username=user.username,
                )
            else:
                await message.answer(
                    "👋 **З поверненням!**\n\n"
                    "Ти вже зареєстрований як Сміттяр. Продовжуй збирати картки!",
                    parse_mode="Markdown",
                )

            break

        except Exception as e:
            logger.error(
                "Error in /start command",
                user_id=user.id,
                error=str(e),
                exc_info=True,
            )
            await message.answer("❌ Помилка при реєстрації. Спробуй ще раз.")
            break
