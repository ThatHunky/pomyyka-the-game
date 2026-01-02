"""Battle handlers for PvP duels between players."""

from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.models import User, UserCard
from database.session import get_session
from logging_config import get_logger
from services.session_manager import SessionManager
from services.battle_engine import execute_battle, generate_battle_summary
from utils.biomes import get_chat_biome
from utils.keyboards import (
    DuelAcceptCallback,
    DuelConfirmStakeCallback,
    DuelStakeCallback,
)
from utils.text import escape_markdown

logger = get_logger(__name__)

router = Router(name="battles")

# Global session manager instance
session_manager = SessionManager()


@router.callback_query(DuelAcceptCallback.filter())
async def handle_duel_accept(callback: CallbackQuery, callback_data: DuelAcceptCallback) -> None:
    """
    Handle duel accept/reject callback.

    If accepted, proceed to stake selection.
    If rejected, cancel the challenge.
    """
    if not callback.message:
        await callback.answer("Помилка: повідомлення не знайдено", show_alert=True)
        return

    user = callback.from_user
    if not user:
        await callback.answer("Помилка", show_alert=True)
        return

    session_data = await session_manager.get_battle_session(callback_data.session_id)
    if not session_data:
        await callback.answer("❌ Сесія бою не знайдена або застаріла", show_alert=True)
        return

    # Check if user is the opponent
    if session_data["opponent_id"] != user.id:
        await callback.answer("❌ Ти не є суперником у цьому бою", show_alert=True)
        return

    if not callback_data.accept:
        # Rejected
        await session_manager.delete_battle_session(callback_data.session_id)
        await callback.message.edit_text(
            "❌ **Виклик відхилено**",
            parse_mode="Markdown",
        )
        await callback.answer("Виклик відхилено")
        return

    # Accepted - show stake selection
    stake_text = (
        "⚔️ **Виклик прийнято!**\n\n"
        "Оберіть ставку для бою:\n\n"
        "Обидва гравці мають підтвердити однакову ставку."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="10 Решток",
                    callback_data=DuelStakeCallback(session_id=callback_data.session_id, stake=10).pack(),
                ),
                InlineKeyboardButton(
                    text="50 Решток",
                    callback_data=DuelStakeCallback(session_id=callback_data.session_id, stake=50).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="100 Решток",
                    callback_data=DuelStakeCallback(session_id=callback_data.session_id, stake=100).pack(),
                ),
                InlineKeyboardButton(
                    text="200 Решток",
                    callback_data=DuelStakeCallback(session_id=callback_data.session_id, stake=200).pack(),
                ),
            ],
        ]
    )

    await callback.message.edit_text(
        stake_text,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    await callback.answer("Оберіть ставку")


@router.callback_query(DuelStakeCallback.filter())
async def handle_duel_stake(callback: CallbackQuery, callback_data: DuelStakeCallback) -> None:
    """
    Handle stake selection.

    Store stake in session and request confirmation from both players.
    """
    if not callback.message:
        await callback.answer("Помилка: повідомлення не знайдено", show_alert=True)
        return

    user = callback.from_user
    if not user:
        await callback.answer("Помилка", show_alert=True)
        return

    session_data = await session_manager.get_battle_session(callback_data.session_id)
    if not session_data:
        await callback.answer("❌ Сесія бою не знайдена", show_alert=True)
        return

    # Check if user is part of this battle
    if user.id not in [session_data["challenger_id"], session_data["opponent_id"]]:
        await callback.answer("❌ Ти не є учасником цього бою", show_alert=True)
        return

    # Set stake
    await session_manager.set_battle_stake(callback_data.session_id, callback_data.stake)

    # Update message with stake confirmation
    stake_text = (
        f"⚔️ **Ставка встановлена**\n\n"
        f"💰 Ставка: **{callback_data.stake} Решток**\n\n"
        f"Обидва гравці мають підтвердити ставку."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Підтвердити ставку (Гравець 1)",
                    callback_data=DuelConfirmStakeCallback(session_id=callback_data.session_id).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✅ Підтвердити ставку (Гравець 2)",
                    callback_data=DuelConfirmStakeCallback(session_id=callback_data.session_id).pack(),
                ),
            ],
        ]
    )

    await callback.message.edit_text(
        stake_text,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    await callback.answer(f"Ставка встановлена: {callback_data.stake} Решток")


@router.callback_query(DuelConfirmStakeCallback.filter())
async def handle_duel_confirm_stake(
    callback: CallbackQuery, callback_data: DuelConfirmStakeCallback
) -> None:
    """
    Handle stake confirmation.

    When both confirm, proceed to deck selection.
    """
    if not callback.message:
        await callback.answer("Помилка: повідомлення не знайдено", show_alert=True)
        return

    user = callback.from_user
    if not user:
        await callback.answer("Помилка", show_alert=True)
        return

    session_data = await session_manager.get_battle_session(callback_data.session_id)
    if not session_data:
        await callback.answer("❌ Сесія бою не знайдена", show_alert=True)
        return

    # Check if user is part of this battle
    if user.id not in [session_data["challenger_id"], session_data["opponent_id"]]:
        await callback.answer("❌ Ти не є учасником цього бою", show_alert=True)
        return

    # Check balance
    async for session in get_session():
        try:
            user_stmt = select(User).where(User.telegram_id == user.id)
            result = await session.execute(user_stmt)
            db_user = result.scalar_one_or_none()

            if not db_user:
                await callback.answer("❌ Користувача не знайдено", show_alert=True)
                break

            stake = session_data.get("stake", 0)
            if db_user.balance < stake:
                await callback.answer(
                    f"❌ Недостатньо Решток! Потрібно: {stake}, у тебе: {db_user.balance}",
                    show_alert=True,
                )
                break

            # Confirm stake
            both_confirmed = await session_manager.confirm_battle_stake(callback_data.session_id, user.id)

            if not both_confirmed:
                await callback.answer("✅ Ставка підтверджена! Очікуємо підтвердження суперника...")
                break

            # Both confirmed - proceed to deck selection
            deck_text = (
                f"⚔️ **Ставка підтверджена!**\n\n"
                f"💰 Ставка: **{stake} Решток**\n\n"
                f"Тепер обидва гравці мають обрати по 3 картки для деки.\n"
                f"Використайте @DumpsterChroniclesBot для вибору карток."
            )

            # Store active battle session for deck selection
            import redis.asyncio as redis
            from config import settings
            redis_client = await redis.from_url(
                settings.redis_url, encoding="utf-8", decode_responses=True
            )
            await redis_client.setex(
                f"user_active_battle:{session_data['challenger_id']}", 600, callback_data.session_id
            )
            await redis_client.setex(
                f"user_active_battle:{session_data['opponent_id']}", 600, callback_data.session_id
            )
            await redis_client.aclose()

            await callback.message.edit_text(
                deck_text,
                parse_mode="Markdown",
            )
            await callback.answer("Оберіть 3 картки для деки через @DumpsterChroniclesBot")
            break

        except Exception as e:
            logger.error(
                "Error confirming battle stake",
                user_id=user.id,
                session_id=callback_data.session_id,
                error=str(e),
                exc_info=True,
            )
            await callback.answer("❌ Помилка", show_alert=True)
            break


async def handle_battle_card_selected(
    session_id: str, user_id: int, card_id: str, bot, chat_id: int, message_id: int
) -> None:
    """
    Handle when a user selects a card for their battle deck.

    Called from inline.py when a card is selected during active battle session.
    """
    session_data = await session_manager.get_battle_session(session_id)
    if not session_data:
        return

    # Add card to deck
    success, deck_size = await session_manager.add_card_to_deck(session_id, user_id, card_id)

    if not success:
        logger.warning(
            "Failed to add card to deck",
            session_id=session_id,
            user_id=user_id,
            card_id=card_id,
            deck_size=deck_size,
        )
        return

    # Check if both decks are ready
    updated_session = await session_manager.get_battle_session(session_id)
    if updated_session and updated_session["status"] == "decks_selected":
        # Both decks ready - execute battle
        await _execute_battle(session_id, bot, chat_id, message_id)
    else:
        # Update message with progress
        challenger_deck_size = len(updated_session["challenger_deck"])
        opponent_deck_size = len(updated_session["opponent_deck"])

        progress_text = (
            f"⚔️ **Вибір деки**\n\n"
            f"Гравець 1: {challenger_deck_size}/3 карток\n"
            f"Гравець 2: {opponent_deck_size}/3 карток\n\n"
            f"Продовжуйте обирати картки через @DumpsterChroniclesBot"
        )

        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=progress_text,
            parse_mode="Markdown",
        )


async def _execute_battle(session_id: str, bot, chat_id: int, message_id: int) -> None:
    """Execute battle and update message with results."""
    session_data = await session_manager.get_battle_session(session_id)
    if not session_data:
        return

    try:
        # Get both decks
        challenger_deck_ids = [UUID(cid) for cid in session_data["challenger_deck"]]
        opponent_deck_ids = [UUID(cid) for cid in session_data["opponent_deck"]]

        async for session in get_session():
            try:
                # Get challenger's cards
                challenger_cards_stmt = (
                    select(UserCard)
                    .where(
                        UserCard.id.in_(challenger_deck_ids),
                        UserCard.user_id == session_data["challenger_id"],
                    )
                    .options(selectinload(UserCard.template))
                )
                challenger_result = await session.execute(challenger_cards_stmt)
                challenger_cards = list(challenger_result.scalars().all())

                # Get opponent's cards
                opponent_cards_stmt = (
                    select(UserCard)
                    .where(
                        UserCard.id.in_(opponent_deck_ids),
                        UserCard.user_id == session_data["opponent_id"],
                    )
                    .options(selectinload(UserCard.template))
                )
                opponent_result = await session.execute(opponent_cards_stmt)
                opponent_cards = list(opponent_result.scalars().all())

                if len(challenger_cards) != 3 or len(opponent_cards) != 3:
                    logger.error(
                        "Invalid deck size",
                        session_id=session_id,
                        challenger_count=len(challenger_cards),
                        opponent_count=len(opponent_cards),
                    )
                    return

                # Get player names
                challenger_user_stmt = select(User).where(
                    User.telegram_id == session_data["challenger_id"]
                )
                opponent_user_stmt = select(User).where(User.telegram_id == session_data["opponent_id"])

                challenger_user_result = await session.execute(challenger_user_stmt)
                opponent_user_result = await session.execute(opponent_user_stmt)

                challenger_user = challenger_user_result.scalar_one_or_none()
                opponent_user = opponent_user_result.scalar_one_or_none()

                challenger_name = (
                    challenger_user.username
                    if challenger_user and challenger_user.username
                    else f"Гравець {session_data['challenger_id']}"
                )
                opponent_name = (
                    opponent_user.username
                    if opponent_user and opponent_user.username
                    else f"Гравець {session_data['opponent_id']}"
                )

                # Get chat biome
                chat_biome = get_chat_biome(chat_id)

                # Execute battle
                deck1_templates = [card.template for card in challenger_cards]
                deck2_templates = [card.template for card in opponent_cards]

                battle_result = execute_battle(
                    deck1_templates,
                    deck2_templates,
                    chat_biome,
                    player1_name=challenger_name,
                    player2_name=opponent_name,
                )

                stake = session_data.get("stake", 0)
                winner_id = (
                    session_data["challenger_id"]
                    if battle_result["winner"] == 1
                    else session_data["opponent_id"]
                )

                # Update balances atomically
                async with session.begin():
                    # Deduct stake from both
                    challenger_user.balance -= stake
                    opponent_user.balance -= stake

                    # Award winner (stake * 2)
                    if battle_result["winner"] == 1:
                        challenger_user.balance += stake * 2
                    else:
                        opponent_user.balance += stake * 2

                    session.add(challenger_user)
                    session.add(opponent_user)

                # Generate battle summary
                summary = generate_battle_summary(battle_result, stake)

                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=summary,
                    parse_mode="Markdown",
                )

                # Clean up
                await session_manager.delete_battle_session(session_id)
                import redis.asyncio as redis
                from config import settings
                redis_client = await redis.from_url(
                    settings.redis_url, encoding="utf-8", decode_responses=True
                )
                await redis_client.delete(f"user_active_battle:{session_data['challenger_id']}")
                await redis_client.delete(f"user_active_battle:{session_data['opponent_id']}")
                await redis_client.aclose()

                logger.info(
                    "Battle completed",
                    session_id=session_id,
                    winner_id=winner_id,
                    stake=stake,
                )
                break

            except Exception as e:
                logger.error(
                    "Error executing battle",
                    session_id=session_id,
                    error=str(e),
                    exc_info=True,
                )
                await session.rollback()
                break

    except Exception as e:
        logger.error(
            "Error in battle execution",
            session_id=session_id,
            error=str(e),
            exc_info=True,
        )
