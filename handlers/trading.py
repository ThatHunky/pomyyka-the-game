"""Trading handlers for card exchange between players."""

from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.models import UserCard
from database.session import get_session
from logging_config import get_logger
from services.session_manager import SessionManager
from utils.emojis import get_biome_emoji, get_rarity_emoji
from utils.keyboards import (
    TradeCancelCallback,
    TradeConfirmCallback,
    TradeProposeCallback,
)
from utils.text import escape_markdown
from utils.telegram_utils import safe_callback_answer

logger = get_logger(__name__)

router = Router(name="trading")

# Global session manager instance (will be initialized in main)
session_manager = SessionManager()


@router.callback_query(TradeProposeCallback.filter())
async def handle_trade_propose(callback: CallbackQuery, callback_data: TradeProposeCallback) -> None:
    """
    Handle trade propose callback - when opponent clicks "Propose trade" button.

    This sends an ephemeral message to the opponent with their cards for selection.
    """
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    user = callback.from_user
    if not user:
        await safe_callback_answer(callback,"Помилка", show_alert=True)
        return

    session_data = await session_manager.get_trade_session(callback_data.session_id)
    if not session_data:
        await safe_callback_answer(callback,"❌ Сесія обміну не знайдена або застаріла", show_alert=True)
        return

    # Check if user is the opponent (not the initiator)
    if session_data["initiator_id"] == user.id:
        await safe_callback_answer(callback,"❌ Ти не можеш обмінятися з самим собою", show_alert=True)
        return

    # Update session with opponent ID
    await session_manager.update_trade_session(callback_data.session_id, opponent_id=user.id)

    # Store active trade session for this user (so we know which session to use when they select a card)
    import redis.asyncio as redis
    from config import settings
    redis_client = await redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    await redis_client.setex(f"user_active_trade:{user.id}", 600, callback_data.session_id)  # 10 min TTL
    await redis_client.aclose()

    # Get opponent's cards
    async for session in get_session():
        try:
            cards_stmt = (
                select(UserCard)
                .where(UserCard.user_id == user.id)
                .options(selectinload(UserCard.template))
                .order_by(UserCard.acquired_at.desc())
                .limit(50)
            )
            result = await session.execute(cards_stmt)
            cards = list(result.scalars().all())

            if not cards:
                await safe_callback_answer(callback,
                    "❌ У тебе немає карток для обміну",
                    show_alert=True,
                )
                break

            # Build message with card list
            message_text = (
                f"🔄 **Обмін картками**\n\n"
                f"Оберіть картку для обміну (використайте @DumpsterChroniclesBot для вибору):"
            )

            # Show first few cards as examples
            for i, card in enumerate(cards[:5], 1):
                template = card.template
                rarity_emoji = get_rarity_emoji(template.rarity)
                stats = template.stats
                message_text += (
                    f"\n{i}. {rarity_emoji} {escape_markdown(template.name)} "
                    f"(⚔️ {stats.get('atk', 0)} / 🛡️ {stats.get('def', 0)})"
                )

            if len(cards) > 5:
                message_text += f"\n\n... та ще {len(cards) - 5} карток"

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❌ Скасувати",
                            callback_data=TradeCancelCallback(session_id=callback_data.session_id).pack(),
                        ),
                    ],
                ]
            )

            await callback.message.edit_text(
                message_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            await safe_callback_answer(callback,"Оберіть картку через @DumpsterChroniclesBot")
            break

        except Exception as e:
            logger.error(
                "Error in trade propose",
                user_id=user.id,
                session_id=callback_data.session_id,
                error=str(e),
                exc_info=True,
            )
            await safe_callback_answer(callback,"❌ Помилка", show_alert=True)
            break


async def handle_trade_card_selected(
    session_id: str, opponent_id: int, card_id: str, bot, chat_id: int, message_id: int
) -> None:
    """
    Handle when opponent selects their card via inline query.

    This is called from inline.py when a card is selected for trading.
    Updates the trade message with both cards and confirmation buttons.
    """
    session_data = await session_manager.get_trade_session(session_id)
    if not session_data:
        return

    # Update session with opponent's card
    await session_manager.update_trade_session(session_id, opponent_card_id=card_id)

    # Get both cards details
    async for session in get_session():
        try:
            # Get initiator's card
            initiator_card_stmt = (
                select(UserCard)
                .where(
                    UserCard.id == UUID(session_data["card_id"]),
                    UserCard.user_id == session_data["initiator_id"],
                )
                .options(selectinload(UserCard.template))
            )
            initiator_result = await session.execute(initiator_card_stmt)
            initiator_card = initiator_result.scalar_one_or_none()

            # Get opponent's card
            opponent_card_stmt = (
                select(UserCard)
                .where(UserCard.id == UUID(card_id), UserCard.user_id == opponent_id)
                .options(selectinload(UserCard.template))
            )
            opponent_result = await session.execute(opponent_card_stmt)
            opponent_card = opponent_result.scalar_one_or_none()

            if not initiator_card or not opponent_card:
                logger.error(
                    "Card not found for trade",
                    session_id=session_id,
                    initiator_card_id=session_data["card_id"],
                    opponent_card_id=card_id,
                )
                return

            initiator_template = initiator_card.template
            opponent_template = opponent_card.template

            # Build trade message
            trade_text = "🔄 **Угода про обмін**\n\n"
            trade_text += f"👤 **Гравець 1** віддає:\n"
            trade_text += f"{get_rarity_emoji(initiator_template.rarity)} **{escape_markdown(initiator_template.name)}**\n"
            trade_text += f"⚔️ {initiator_template.stats.get('atk', 0)} / 🛡️ {initiator_template.stats.get('def', 0)}\n\n"
            trade_text += f"👤 **Гравець 2** віддає:\n"
            trade_text += f"{get_rarity_emoji(opponent_template.rarity)} **{escape_markdown(opponent_template.name)}**\n"
            trade_text += f"⚔️ {opponent_template.stats.get('atk', 0)} / 🛡️ {opponent_template.stats.get('def', 0)}\n\n"
            trade_text += "Обидва гравці мають підтвердити обмін."

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Підтвердити (Гравець 1)",
                            callback_data=TradeConfirmCallback(session_id=session_id).pack(),
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="✅ Підтвердити (Гравець 2)",
                            callback_data=TradeConfirmCallback(session_id=session_id).pack(),
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="❌ Скасувати",
                            callback_data=TradeCancelCallback(session_id=session_id).pack(),
                        ),
                    ],
                ]
            )

            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=trade_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            break

        except Exception as e:
            logger.error(
                "Error updating trade message",
                session_id=session_id,
                error=str(e),
                exc_info=True,
            )


@router.callback_query(TradeConfirmCallback.filter())
async def handle_trade_confirm(callback: CallbackQuery, callback_data: TradeConfirmCallback) -> None:
    """
    Handle trade confirmation callback.

    When both users confirm, execute atomic card swap.
    """
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    user = callback.from_user
    if not user:
        await safe_callback_answer(callback,"Помилка", show_alert=True)
        return

    session_data = await session_manager.get_trade_session(callback_data.session_id)
    if not session_data:
        await safe_callback_answer(callback,"❌ Сесія обміну не знайдена або застаріла", show_alert=True)
        return

    # Check if user is part of this trade
    if user.id not in [session_data["initiator_id"], session_data.get("opponent_id")]:
        await safe_callback_answer(callback,"❌ Ти не є учасником цього обміну", show_alert=True)
        return

    # Check if opponent card is selected
    if not session_data.get("opponent_card_id"):
        await safe_callback_answer(callback,"❌ Суперник ще не обрав картку", show_alert=True)
        return

    # Confirm trade
    both_confirmed = await session_manager.confirm_trade(callback_data.session_id, user.id)

    if not both_confirmed:
        await safe_callback_answer(callback,"✅ Підтверджено! Очікуємо підтвердження суперника...")
        return

    # Both confirmed - execute trade
    try:
        initiator_card_id = UUID(session_data["card_id"])
        opponent_card_id = UUID(session_data["opponent_card_id"])
        initiator_id = session_data["initiator_id"]
        opponent_id = session_data["opponent_id"]

        async for session in get_session():
            try:
                # Get both cards to verify ownership
                initiator_card_stmt = select(UserCard).where(
                    UserCard.id == initiator_card_id, UserCard.user_id == initiator_id
                )
                opponent_card_stmt = select(UserCard).where(
                    UserCard.id == opponent_card_id, UserCard.user_id == opponent_id
                )

                initiator_result = await session.execute(initiator_card_stmt)
                opponent_result = await session.execute(opponent_card_stmt)

                initiator_card = initiator_result.scalar_one_or_none()
                opponent_card = opponent_result.scalar_one_or_none()

                if not initiator_card or not opponent_card:
                    logger.error(
                        "Card not found during trade execution",
                        initiator_card_id=str(initiator_card_id),
                        opponent_card_id=str(opponent_card_id),
                    )
                    await safe_callback_answer(callback,"❌ Помилка: картка не знайдена", show_alert=True)
                    await session_manager.delete_trade_session(callback_data.session_id)
                    break

                # Atomic swap: update user_id for both cards
                async with session.begin():
                    initiator_card.user_id = opponent_id
                    opponent_card.user_id = initiator_id
                    session.add(initiator_card)
                    session.add(opponent_card)

                logger.info(
                    "Trade completed",
                    session_id=callback_data.session_id,
                    initiator_id=initiator_id,
                    opponent_id=opponent_id,
                    initiator_card_id=str(initiator_card_id),
                    opponent_card_id=str(opponent_card_id),
                )

                # Update message with success
                success_text = "✅ **Обмін успішно завершено!**\n\n"
                success_text += "Картки обміняно між гравцями."

                await callback.message.edit_text(
                    success_text,
                    parse_mode="Markdown",
                )
                await safe_callback_answer(callback,"✅ Обмін завершено!")

                # Clean up session
                await session_manager.delete_trade_session(callback_data.session_id)
                break

            except Exception as e:
                logger.error(
                    "Error executing trade",
                    session_id=callback_data.session_id,
                    error=str(e),
                    exc_info=True,
                )
                await session.rollback()
                await safe_callback_answer(callback,"❌ Помилка при виконанні обміну", show_alert=True)
                await session_manager.delete_trade_session(callback_data.session_id)
                break

    except ValueError as e:
        logger.error(
            "Invalid card ID in trade session",
            session_id=callback_data.session_id,
            error=str(e),
        )
        await safe_callback_answer(callback,"❌ Помилка: невалідний ID картки", show_alert=True)
        await session_manager.delete_trade_session(callback_data.session_id)


@router.callback_query(TradeCancelCallback.filter())
async def handle_trade_cancel(callback: CallbackQuery, callback_data: TradeCancelCallback) -> None:
    """Handle trade cancellation."""
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    user = callback.from_user
    if not user:
        await safe_callback_answer(callback,"Помилка", show_alert=True)
        return

    session_data = await session_manager.get_trade_session(callback_data.session_id)
    if not session_data:
        await safe_callback_answer(callback,"❌ Сесія обміну не знайдена", show_alert=True)
        return

    # Check if user is part of this trade
    if user.id not in [session_data["initiator_id"], session_data.get("opponent_id")]:
        await safe_callback_answer(callback,"❌ Ти не є учасником цього обміну", show_alert=True)
        return

    # Delete session and update message
    await session_manager.delete_trade_session(callback_data.session_id)

    await callback.message.edit_text(
        "❌ **Обмін скасовано**",
        parse_mode="Markdown",
    )
    await safe_callback_answer(callback,"Обмін скасовано")
