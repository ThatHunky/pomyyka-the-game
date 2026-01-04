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
from utils.telegram_utils import safe_callback_answer

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
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    user = callback.from_user
    if not user:
        await safe_callback_answer(callback,"Помилка", show_alert=True)
        return

    session_data = await session_manager.get_battle_session(callback_data.session_id)
    if not session_data:
        await safe_callback_answer(callback,"❌ Сесія бою не знайдена або застаріла", show_alert=True)
        return

    # Check if user is the opponent
    if session_data["opponent_id"] != user.id:
        await safe_callback_answer(callback,"❌ Ти не є суперником у цьому бою", show_alert=True)
        return

    if not callback_data.accept:
        # Rejected
        await session_manager.delete_battle_session(callback_data.session_id)
        await callback.message.edit_text(
            "❌ **Виклик відхилено**",
            parse_mode="Markdown",
        )
        await safe_callback_answer(callback,"Виклик відхилено")
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
    await safe_callback_answer(callback,"Оберіть ставку")


@router.callback_query(DuelStakeCallback.filter())
async def handle_duel_stake(callback: CallbackQuery, callback_data: DuelStakeCallback) -> None:
    """
    Handle stake selection.

    Store stake in session and request confirmation from both players.
    """
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    user = callback.from_user
    if not user:
        await safe_callback_answer(callback,"Помилка", show_alert=True)
        return

    session_data = await session_manager.get_battle_session(callback_data.session_id)
    if not session_data:
        await safe_callback_answer(callback,"❌ Сесія бою не знайдена", show_alert=True)
        return

    # Check if user is part of this battle
    if user.id not in [session_data["challenger_id"], session_data["opponent_id"]]:
        await safe_callback_answer(callback,"❌ Ти не є учасником цього бою", show_alert=True)
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
    await safe_callback_answer(callback,f"Ставка встановлена: {callback_data.stake} Решток")


@router.callback_query(DuelConfirmStakeCallback.filter())
async def handle_duel_confirm_stake(
    callback: CallbackQuery, callback_data: DuelConfirmStakeCallback
) -> None:
    """
    Handle stake confirmation.

    When both confirm, proceed to deck selection.
    """
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    user = callback.from_user
    if not user:
        await safe_callback_answer(callback,"Помилка", show_alert=True)
        return

    session_data = await session_manager.get_battle_session(callback_data.session_id)
    if not session_data:
        await safe_callback_answer(callback,"❌ Сесія бою не знайдена", show_alert=True)
        return

    # Check if user is part of this battle
    if user.id not in [session_data["challenger_id"], session_data["opponent_id"]]:
        await safe_callback_answer(callback,"❌ Ти не є учасником цього бою", show_alert=True)
        return

    # Check balance
    async for session in get_session():
        try:
            user_stmt = select(User).where(User.telegram_id == user.id)
            result = await session.execute(user_stmt)
            db_user = result.scalar_one_or_none()

            if not db_user:
                await safe_callback_answer(callback,"❌ Користувача не знайдено", show_alert=True)
                break

            stake = session_data.get("stake", 0)
            if db_user.balance < stake:
                await safe_callback_answer(callback,
                    f"❌ Недостатньо Решток! Потрібно: {stake}, у тебе: {db_user.balance}",
                    show_alert=True,
                )
                break

            # Confirm stake
            both_confirmed = await session_manager.confirm_battle_stake(callback_data.session_id, user.id)

            if not both_confirmed:
                await safe_callback_answer(callback,"✅ Ставка підтверджена! Очікуємо підтвердження суперника...")
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
            await safe_callback_answer(callback,"Оберіть 3 картки для деки через @DumpsterChroniclesBot")
            break

        except Exception as e:
            logger.error(
                "Error confirming battle stake",
                user_id=user.id,
                session_id=callback_data.session_id,
                error=str(e),
                exc_info=True,
            )
            await safe_callback_answer(callback,"❌ Помилка", show_alert=True)
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
    """Initialize turn-based battle and show UI."""
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
                    logger.error("Invalid deck size", session_id=session_id)
                    return

                # Get player names
                challenger_user_stmt = select(User).where(
                    User.telegram_id == session_data["challenger_id"]
                )
                opponent_user_stmt = select(User).where(User.telegram_id == session_data["opponent_id"])

                c_user = (await session.execute(challenger_user_stmt)).scalar_one_or_none()
                o_user = (await session.execute(opponent_user_stmt)).scalar_one_or_none()

                c_name = c_user.username if c_user and c_user.username else f"Гравець {session_data['challenger_id']}"
                o_name = o_user.username if o_user and o_user.username else f"Гравець {session_data['opponent_id']}"

                # INITIALIZE NEW BATTLE ENGINE
                from services.turn_battle import create_initial_state, resolve_initiative
                from handlers.turn_battle_handler import render_battle_ui

                p1_data = {
                    "id": session_data["challenger_id"],
                    "name": c_name,
                    "cards": challenger_cards
                }
                p2_data = {
                    "id": session_data["opponent_id"],
                    "name": o_name,
                    "cards": opponent_cards
                }

                # Create State
                battle_state = create_initial_state(session_id, chat_id, p1_data, p2_data)
                
                # Roll Initiative
                resolve_initiative(battle_state)
                
                # Save State
                await session_manager.save_turn_battle_state(battle_state)

                # Render UI
                text, markup = render_battle_ui(battle_state, 0) # 0 means neutral view? No, we need to handle permissions.
                # Actually render_battle_ui takes user_id to determine perspective.
                # The message in chat is shared.
                # So we should probably render standard view, or maybe perspective of active player?
                # The callback handler manages personalized views during interaction, but initial message is public.
                # Let's render from Player 1 perspective for now, or ensure UI is robust for spectators.
                # Wait, Telegram messages are same for everyone.
                # So the keyboard needs to handle permission checks (which it does in handler).
                # But buttons might say "Your Turn". 
                # Let's render from correct active player perspective just for the text.
                
                active_uid = battle_state.get_player(battle_state.active_player_idx).user_id
                text, markup = render_battle_ui(battle_state, active_uid)
                
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=markup
                )

                # Clean up legacy session pointers?
                # We need to keep pointing to this battle session actually?
                # The legacy session data is used for "setup", "turn_battle" uses same session_id key?
                # Yes, session_id is consistent.
                
                # Clear "active_battle" pointers so users can't modify decks anymore?
                # Actually we might want to keep them to know they are IN a battle.
                # But logic in inline.py checks this key.
                # Let's keep them engaged.

                logger.info("Turn-based battle started", session_id=session_id)
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
