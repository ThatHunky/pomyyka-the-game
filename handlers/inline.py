"""Inline query handlers for player interactions (trading, battles, etc.)."""

from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    ChosenInlineResult,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Message,
)
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.enums import Rarity
from database.models import User, UserCard
from database.session import get_session
from logging_config import get_logger
from services.session_manager import SessionManager
from utils.emojis import get_biome_emoji, get_rarity_emoji
from utils.keyboards import DuelAcceptCallback, TradeProposeCallback
from utils.text import escape_markdown

logger = get_logger(__name__)

router = Router(name="inline")

# Global session manager instance
session_manager = SessionManager()

# Inline query result types
INLINE_ACTION_TRADE = "trade"
INLINE_ACTION_DUEL = "duel"
INLINE_ACTION_PROFILE = "profile"
INLINE_ACTION_COLLECTION = "collection"


@router.inline_query()
async def handle_inline_query(inline_query: InlineQuery) -> None:
    """
    Handle inline query - show main menu with action options.

    When user types @botname, shows:
    - 🔄 Трейдинг (Trade)
    - ⚔️ Виклик на бій (Duel)
    - 📊 Мій профіль (Profile)
    - 🎴 Моя колекція (Collection)
    """
    user = inline_query.from_user
    if not user:
        return

    query = inline_query.query.strip().lower()

    # If query is empty or just whitespace, show main menu
    if not query:
        results = [
            InlineQueryResultArticle(
                id=INLINE_ACTION_TRADE,
                title="🔄 Трейдинг",
                description="Обмінятися картками з іншими гравцями",
                input_message_content=InputTextMessageContent(
                    message_text="🔄 **Трейдинг**\n\nОберіть картку для обміну:",
                    parse_mode="Markdown",
                ),
            ),
            InlineQueryResultArticle(
                id=INLINE_ACTION_DUEL,
                title="⚔️ Виклик на бій",
                description="Викликати гравця на дуель",
                input_message_content=InputTextMessageContent(
                    message_text="⚔️ **Виклик на дуель**\n\nОберіть суперника:",
                    parse_mode="Markdown",
                ),
            ),
            InlineQueryResultArticle(
                id=INLINE_ACTION_PROFILE,
                title="📊 Мій профіль",
                description="Переглянути свій профіль та статистику",
                input_message_content=InputTextMessageContent(
                    message_text="📊 **Профіль**\n\nЗавантаження...",
                    parse_mode="Markdown",
                ),
            ),
            InlineQueryResultArticle(
                id=INLINE_ACTION_COLLECTION,
                title="🎴 Моя колекція",
                description="Переглянути свою колекцію карток",
                input_message_content=InputTextMessageContent(
                    message_text="🎴 **Колекція**\n\nЗавантаження...",
                    parse_mode="Markdown",
                ),
            ),
        ]

        await inline_query.answer(results, cache_time=1)
        return

    # If query starts with specific action, handle it
    if query.startswith("trade") or query.startswith("трейдинг"):
        await _handle_trade_query(inline_query)
    elif query.startswith("duel") or query.startswith("бій") or query.startswith("дуель"):
        await _handle_duel_query(inline_query)
    elif query.startswith("profile") or query.startswith("профіль"):
        await _handle_profile_query(inline_query)
    elif query.startswith("collection") or query.startswith("колекція"):
        await _handle_collection_query(inline_query)
    else:
        # Search cards by name
        await _handle_card_search(inline_query, query)


async def _handle_trade_query(inline_query: InlineQuery) -> None:
    """Handle trade inline query - show user's cards for trading."""
    user = inline_query.from_user
    if not user:
        return

    async for session in get_session():
        try:
            # Get user's cards
            cards_stmt = (
                select(UserCard)
                .where(UserCard.user_id == user.id)
                .options(selectinload(UserCard.template))
                .order_by(UserCard.acquired_at.desc())
                .limit(50)  # Limit to 50 cards for inline results
            )
            result = await session.execute(cards_stmt)
            cards = list(result.scalars().all())

            if not cards:
                results = [
                    InlineQueryResultArticle(
                        id="no_cards",
                        title="❌ Немає карток",
                        description="У вас немає карток для обміну",
                        input_message_content=InputTextMessageContent(
                            message_text="❌ У вас немає карток для обміну.",
                            parse_mode="Markdown",
                        ),
                    )
                ]
                await inline_query.answer(results, cache_time=1)
                return

            # Build inline results for cards
            results = []
            for card in cards:
                template = card.template
                rarity_emoji = get_rarity_emoji(template.rarity)
                stats = template.stats

                card_text = (
                    f"{rarity_emoji} **{escape_markdown(template.name)}**\n"
                    f"⚔️ {stats.get('atk', 0)} / 🛡️ {stats.get('def', 0)}"
                )

                results.append(
                    InlineQueryResultArticle(
                        id=f"trade_card:{card.id}",
                        title=f"{rarity_emoji} {template.name}",
                        description=f"⚔️ {stats.get('atk', 0)} / 🛡️ {stats.get('def', 0)}",
                        input_message_content=InputTextMessageContent(
                            message_text=card_text,
                            parse_mode="Markdown",
                        ),
                    )
                )

            await inline_query.answer(results, cache_time=1)
            break

        except Exception as e:
            logger.error(
                "Error in trade query",
                user_id=user.id,
                error=str(e),
                exc_info=True,
            )
            break


async def _handle_duel_query(inline_query: InlineQuery) -> None:
    """Handle duel inline query - show available opponents or user's cards for deck selection."""
    user = inline_query.from_user
    if not user:
        return

    query = inline_query.query.strip().lower()

    # If query contains username or user ID, it's a challenge
    # Otherwise, show user's cards for deck selection
    if "@" in query or query.isdigit():
        # This will be handled by chosen_inline_result
        results = [
            InlineQueryResultArticle(
                id=f"duel_challenge:{query}",
                title="⚔️ Виклик на дуель",
                description=f"Викликати {query} на бій",
                input_message_content=InputTextMessageContent(
                    message_text=f"⚔️ **Виклик на дуель**\n\nЗавантаження...",
                    parse_mode="Markdown",
                ),
            )
        ]
        await inline_query.answer(results, cache_time=1)
        return

    # Show user's cards for deck selection
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
                results = [
                    InlineQueryResultArticle(
                        id="no_cards_duel",
                        title="❌ Немає карток",
                        description="У вас немає карток для бою",
                        input_message_content=InputTextMessageContent(
                            message_text="❌ У вас немає карток для бою.",
                            parse_mode="Markdown",
                        ),
                    )
                ]
                await inline_query.answer(results, cache_time=1)
                return

            results = []
            for card in cards:
                template = card.template
                rarity_emoji = get_rarity_emoji(template.rarity)
                stats = template.stats

                results.append(
                    InlineQueryResultArticle(
                        id=f"duel_card:{card.id}",
                        title=f"{rarity_emoji} {template.name}",
                        description=f"⚔️ {stats.get('atk', 0)} / 🛡️ {stats.get('def', 0)}",
                        input_message_content=InputTextMessageContent(
                            message_text=f"{rarity_emoji} **{escape_markdown(template.name)}**",
                            parse_mode="Markdown",
                        ),
                    )
                )

            await inline_query.answer(results, cache_time=1)
            break

        except Exception as e:
            logger.error(
                "Error in duel query",
                user_id=user.id,
                error=str(e),
                exc_info=True,
            )
            break


async def _handle_profile_query(inline_query: InlineQuery) -> None:
    """Handle profile inline query."""
    user = inline_query.from_user
    if not user:
        return

    async for session in get_session():
        try:
            user_stmt = (
                select(User)
                .where(User.telegram_id == user.id)
                .options(selectinload(User.cards).selectinload(UserCard.template))
            )
            result = await session.execute(user_stmt)
            db_user = result.scalar_one_or_none()

            if not db_user:
                results = [
                    InlineQueryResultArticle(
                        id="profile_not_found",
                        title="❌ Профіль не знайдено",
                        description="Використайте /start для реєстрації",
                        input_message_content=InputTextMessageContent(
                            message_text="❌ Профіль не знайдено. Використайте /start для реєстрації.",
                            parse_mode="Markdown",
                        ),
                    )
                ]
                await inline_query.answer(results, cache_time=1)
                return

            total_cards = len(db_user.cards)
            profile_text = (
                f"📊 **Профіль Сміттяра**\n\n"
                f"👤 **Ім'я:** {escape_markdown(user.first_name or 'Невідомо')}\n"
            )
            if user.username:
                profile_text += f"🔗 **Username:** @{escape_markdown(user.username)}\n"
            profile_text += f"💰 **Баланс:** {db_user.balance} Решток\n"
            profile_text += f"📦 **Карток:** {total_cards}"

            results = [
                InlineQueryResultArticle(
                    id="profile",
                    title="📊 Мій профіль",
                    description=f"Баланс: {db_user.balance} | Карток: {total_cards}",
                    input_message_content=InputTextMessageContent(
                        message_text=profile_text,
                        parse_mode="Markdown",
                    ),
                )
            ]

            await inline_query.answer(results, cache_time=1)
            break

        except Exception as e:
            logger.error(
                "Error in profile query",
                user_id=user.id,
                error=str(e),
                exc_info=True,
            )
            break


async def _handle_collection_query(inline_query: InlineQuery) -> None:
    """Handle collection inline query - show user's cards."""
    await _handle_trade_query(inline_query)  # Same logic as trade


async def _handle_card_search(inline_query: InlineQuery, query: str) -> None:
    """Handle card search by name."""
    user = inline_query.from_user
    if not user:
        return

    async for session in get_session():
        try:
            # Search user's cards by name
            cards_stmt = (
                select(UserCard)
                .where(UserCard.user_id == user.id)
                .options(selectinload(UserCard.template))
            )
            result = await session.execute(cards_stmt)
            all_cards = list(result.scalars().all())

            # Filter by query (case-insensitive)
            matching_cards = [
                card
                for card in all_cards
                if query.lower() in card.template.name.lower()
            ][:50]  # Limit to 50 results

            if not matching_cards:
                results = [
                    InlineQueryResultArticle(
                        id="no_results",
                        title="❌ Нічого не знайдено",
                        description=f"Картки з назвою '{query}' не знайдено",
                        input_message_content=InputTextMessageContent(
                            message_text=f"❌ Картки з назвою '{query}' не знайдено.",
                            parse_mode="Markdown",
                        ),
                    )
                ]
                await inline_query.answer(results, cache_time=1)
                return

            results = []
            for card in matching_cards:
                template = card.template
                rarity_emoji = get_rarity_emoji(template.rarity)
                stats = template.stats

                results.append(
                    InlineQueryResultArticle(
                        id=f"card:{card.id}",
                        title=f"{rarity_emoji} {template.name}",
                        description=f"⚔️ {stats.get('atk', 0)} / 🛡️ {stats.get('def', 0)}",
                        input_message_content=InputTextMessageContent(
                            message_text=f"{rarity_emoji} **{escape_markdown(template.name)}**",
                            parse_mode="Markdown",
                        ),
                    )
                )

            await inline_query.answer(results, cache_time=1)
            break

        except Exception as e:
            logger.error(
                "Error in card search",
                user_id=user.id,
                query=query,
                error=str(e),
                exc_info=True,
            )
            break


@router.chosen_inline_result()
async def handle_chosen_inline_result(chosen_result: ChosenInlineResult) -> None:
    """
    Handle chosen inline result - when user selects an option.

    This is where we can store session data in Redis for trading/battles.
    """
    user = chosen_result.from_user
    if not user:
        return

    result_id = chosen_result.result_id
    chat_id = chosen_result.chat.id if chosen_result.chat else None

    logger.info(
        "Chosen inline result",
        user_id=user.id,
        result_id=result_id,
        query=chosen_result.query,
        chat_id=chat_id,
    )

    # Parse result_id to determine action
    if result_id.startswith("trade_card:"):
        card_id = result_id.split(":", 1)[1]
        await _initiate_trade_session(user.id, card_id, chosen_result)
    elif result_id.startswith("duel_card:"):
        card_id = result_id.split(":", 1)[1]
        # This will be handled in battles.py when deck selection is active
        await _handle_duel_card_selection(user.id, card_id)
    elif result_id.startswith("duel_challenge:"):
        opponent = result_id.split(":", 1)[1]
        await _initiate_duel_challenge(user.id, opponent, chosen_result)
    elif result_id.startswith("card:"):
        # Generic card selection - check if user has active trade session
        card_id = result_id.split(":", 1)[1]
        await _handle_generic_card_selection(user.id, card_id, chat_id)


async def _initiate_trade_session(
    user_id: int, card_id: str, chosen_result: ChosenInlineResult
) -> None:
    """Create trade session and send message to chat with propose button."""
    if not chosen_result.chat:
        logger.warning("Trade initiated outside of chat", user_id=user_id)
        return

    chat_id = chosen_result.chat.id
    bot = chosen_result.bot

    try:
        # Get card details
        async for session in get_session():
            try:
                card_stmt = (
                    select(UserCard)
                    .where(UserCard.id == UUID(card_id), UserCard.user_id == user_id)
                    .options(selectinload(UserCard.template))
                )
                result = await session.execute(card_stmt)
                user_card = result.scalar_one_or_none()

                if not user_card:
                    logger.warning(
                        "Card not found for trade",
                        user_id=user_id,
                        card_id=card_id,
                    )
                    return

                template = user_card.template
                rarity_emoji = get_rarity_emoji(template.rarity)
                biome_emoji = get_biome_emoji(template.biome_affinity)
                stats = template.stats

                # Create trade session
                session_id = await session_manager.create_trade_session(
                    initiator_id=user_id,
                    card_id=card_id,
                    message_id=0,  # Will be updated after sending message
                    chat_id=chat_id,
                )

                # Build trade message
                trade_text = (
                    f"🔄 **Пропозиція обміну**\n\n"
                    f"👤 {escape_markdown(chosen_result.from_user.first_name or 'Гравець')} пропонує обмінятися:\n\n"
                    f"{biome_emoji} {rarity_emoji} **{escape_markdown(template.name)}**\n"
                    f"⚔️ {stats.get('atk', 0)} / 🛡️ {stats.get('def', 0)}\n\n"
                    f"Натисніть кнопку нижче, щоб запропонувати свою картку для обміну."
                )

                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🔄 Запропонувати обмін",
                                callback_data=TradeProposeCallback(session_id=session_id).pack(),
                            ),
                        ],
                    ]
                )

                # Send message to chat
                message = await bot.send_message(
                    chat_id=chat_id,
                    text=trade_text,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )

                # Update session with message_id
                session_data = await session_manager.get_trade_session(session_id)
                if session_data:
                    session_data["message_id"] = message.message_id
                    key = f"trade:{session_id}"
                    client = await session_manager._get_redis()
                    ttl = await client.ttl(key)
                    if ttl > 0:
                        import json
                        await client.setex(key, ttl, json.dumps(session_data))

                logger.info(
                    "Trade session initiated",
                    session_id=session_id,
                    user_id=user_id,
                    card_id=card_id,
                    message_id=message.message_id,
                )
                break

            except Exception as e:
                logger.error(
                    "Error initiating trade session",
                    user_id=user_id,
                    card_id=card_id,
                    error=str(e),
                    exc_info=True,
                )
                break

    except ValueError:
        logger.error("Invalid card ID", card_id=card_id, user_id=user_id)


async def _handle_generic_card_selection(user_id: int, card_id: str, chat_id: int | None) -> None:
    """
    Handle generic card selection - check if user has active trade session.

    When opponent selects a card after clicking "Propose trade", we need to find
    the active trade session and update it.
    """
    if not chat_id:
        return

    # Check for active trade session for this user
    import redis.asyncio as redis
    from config import settings
    redis_client = await redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        session_id = await redis_client.get(f"user_active_trade:{user_id}")
        if session_id:
            # User has an active trade session - update it with selected card
            await _update_trade_with_opponent_card(session_id, user_id, card_id, chat_id)
            await redis_client.delete(f"user_active_trade:{user_id}")
    finally:
        await redis_client.aclose()


async def _update_trade_with_opponent_card(
    session_id: str, opponent_id: int, card_id: str, chat_id: int
) -> None:
    """Update trade session with opponent's selected card and update message."""
    session_data = await session_manager.get_trade_session(session_id)
    if not session_data:
        return

    # Update session with opponent's card
    await session_manager.update_trade_session(session_id, opponent_card_id=card_id)

    # Get both cards details and update message
    async for session in get_session():
        try:
            from aiogram import Bot
            from utils.keyboards import TradeConfirmCallback, TradeCancelCallback

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

            # Get bot instance and update message
            from aiogram import Bot
            from config import settings
            bot = Bot(token=settings.bot_token)
            message_id = session_data.get("message_id", 0)
            if message_id:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=trade_text,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
            await bot.session.close()
            break

        except Exception as e:
            logger.error(
                "Error updating trade message",
                session_id=session_id,
                error=str(e),
                exc_info=True,
            )


async def _handle_duel_card_selection(user_id: int, card_id: str) -> None:
    """
    Handle duel card selection for deck building.

    Check if user has active battle session and add card to deck.
    """
    # Check for active battle session for this user
    import redis.asyncio as redis
    from config import settings
    redis_client = await redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    try:
        session_id = await redis_client.get(f"user_active_battle:{user_id}")
        if session_id:
            # User has an active battle session - add card to deck
            session_data = await session_manager.get_battle_session(session_id)
            if session_data:
                chat_id = session_data.get("chat_id")
                message_id = session_data.get("message_id", 0)
                if chat_id and message_id:
                    # Import here to avoid circular dependency
                    from handlers.battles import handle_battle_card_selected
                    from aiogram import Bot
                    bot = Bot(token=settings.bot_token)
                    await handle_battle_card_selected(session_id, user_id, card_id, bot, chat_id, message_id)
                    await bot.session.close()
    finally:
        await redis_client.aclose()


async def _initiate_duel_challenge(
    user_id: int, opponent: str, chosen_result: ChosenInlineResult
) -> None:
    """
    Initiate duel challenge.

    Parse opponent username/ID and create battle session.
    """
    if not chosen_result.chat:
        logger.warning("Duel initiated outside of chat", user_id=user_id)
        return

    chat_id = chosen_result.chat.id
    bot = chosen_result.bot

    try:
        # Parse opponent - could be @username or user ID
        opponent_id = None
        if opponent.startswith("@"):
            # Username - need to resolve (simplified: for now, require user ID)
            logger.warning("Username resolution not implemented", opponent=opponent)
            return
        elif opponent.isdigit():
            opponent_id = int(opponent)
        else:
            # Try to find user by username in database
            async for session in get_session():
                try:
                    from database.models import User
                    user_stmt = select(User).where(User.username == opponent.lstrip("@"))
                    result = await session.execute(user_stmt)
                    db_user = result.scalar_one_or_none()
                    if db_user:
                        opponent_id = db_user.telegram_id
                    break
                except Exception as e:
                    logger.error("Error finding opponent", opponent=opponent, error=str(e))
                    break

        if not opponent_id:
            logger.warning("Opponent not found", opponent=opponent)
            return

        if opponent_id == user_id:
            logger.warning("User tried to challenge themselves", user_id=user_id)
            return

        # Create battle session
        session_id = await session_manager.create_battle_session(
            challenger_id=user_id,
            opponent_id=opponent_id,
            message_id=0,  # Will be updated after sending message
            chat_id=chat_id,
        )

        # Get challenger name
        challenger_name = chosen_result.from_user.first_name or "Гравець"
        if chosen_result.from_user.username:
            challenger_name = f"@{chosen_result.from_user.username}"

        # Build challenge message
        challenge_text = (
            f"⚔️ **Виклик на дуель!**\n\n"
            f"👤 {escape_markdown(challenger_name)} викликає на бій!\n\n"
            f"Натисніть кнопку нижче, щоб прийняти або відхилити виклик."
        )

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Прийняти",
                        callback_data=DuelAcceptCallback(session_id=session_id, accept=True).pack(),
                    ),
                    InlineKeyboardButton(
                        text="❌ Відхилити",
                        callback_data=DuelAcceptCallback(session_id=session_id, accept=False).pack(),
                    ),
                ],
            ]
        )

        # Send message to chat
        message = await bot.send_message(
            chat_id=chat_id,
            text=challenge_text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

        # Update session with message_id
        session_data = await session_manager.get_battle_session(session_id)
        if session_data:
            session_data["message_id"] = message.message_id
            key = f"battle:{session_id}"
            client = await session_manager._get_redis()
            ttl = await client.ttl(key)
            if ttl > 0:
                import json
                await client.setex(key, ttl, json.dumps(session_data))

        logger.info(
            "Duel challenge initiated",
            session_id=session_id,
            challenger_id=user_id,
            opponent_id=opponent_id,
            message_id=message.message_id,
        )

    except Exception as e:
        logger.error(
            "Error initiating duel challenge",
            user_id=user_id,
            opponent=opponent,
            error=str(e),
            exc_info=True,
        )
