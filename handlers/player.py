"""Player handlers for user commands."""

from uuid import UUID

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import delete, func, select

from utils.animations import send_card_animation, send_card_animation_to_callback
from sqlalchemy.orm import selectinload

from database.enums import BiomeType, Rarity
from database.models import CardTemplate, User, UserCard
from database.session import get_session
from logging_config import get_logger
from utils.emojis import get_biome_emoji, get_rarity_emoji
from utils.keyboards import (
    CardViewCallback,
    InventoryCallback,
    NavigationCallback,
    ScrapCardCallback,
    StatsCallback,
    get_card_detail_keyboard,
    get_help_keyboard,
    get_inventory_keyboard,
    get_main_menu_inline_keyboard,
    get_main_menu_keyboard,
    get_profile_keyboard,
    get_scrap_confirm_keyboard,
    get_stats_keyboard,
)
from utils.text import escape_markdown
from utils.telegram_utils import safe_callback_answer

logger = get_logger(__name__)

router = Router(name="player")

CARDS_PER_PAGE = 10


async def safe_edit_text(
    message: Message,
    text: str,
    parse_mode: str | None = "Markdown",
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """
    Safely edit message text, handling "message not modified" errors.

    Args:
        message: Message to edit.
        text: New text content.
        parse_mode: Parse mode (default: Markdown).
        reply_markup: Inline keyboard markup.
    """
    try:
        await message.edit_text(
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as e:
        # Handle "message is not modified" error gracefully
        if "message is not modified" not in str(e):
            raise




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

            main_menu_kb = get_main_menu_keyboard()

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
                    reply_markup=main_menu_kb,
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
                    reply_markup=main_menu_kb,
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


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    """Show main menu."""
    await message.answer(
        "🏠 **Головне меню**\n\n"
        "Оберіть дію з меню нижче:",
        parse_mode="Markdown",
        reply_markup=get_main_menu_keyboard(),
    )


@router.message(F.text == "📊 Профіль")
@router.message(Command("me", "profile"))
async def cmd_profile(message: Message) -> None:
    """Show user profile."""
    user = message.from_user
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
                await message.answer(
                    "❌ Користувача не знайдено. Використайте /start для реєстрації.",
                    reply_markup=get_main_menu_keyboard(),
                )
                break

            # Get card statistics
            total_cards = len(db_user.cards)
            cards_by_rarity = {}
            cards_by_biome = {}

            for user_card in db_user.cards:
                template = user_card.template
                rarity = template.rarity.value
                biome = template.biome_affinity.value

                cards_by_rarity[rarity] = cards_by_rarity.get(rarity, 0) + 1
                cards_by_biome[biome] = cards_by_biome.get(biome, 0) + 1

            # Get last card acquired
            last_card = None
            if db_user.cards:
                sorted_cards = sorted(db_user.cards, key=lambda c: c.acquired_at, reverse=True)
                last_card = sorted_cards[0].template

            # Build profile text (escape user-provided content)
            profile_text = "📊 **Профіль Сміттяра**\n\n"
            profile_text += f"👤 **Ім'я:** {escape_markdown(user.first_name or 'Невідомо')}\n"
            if user.username:
                profile_text += f"🔗 **Username:** @{escape_markdown(user.username)}\n"
            profile_text += f"💰 **Баланс:** {db_user.balance}\n\n"

            profile_text += "📦 **Колекція:**\n"
            profile_text += f"  • Всього карток: {total_cards}\n"

            if cards_by_rarity:
                profile_text += "  • По рідкості:\n"
                for rarity, count in sorted(cards_by_rarity.items()):
                    emoji = get_rarity_emoji(Rarity(rarity))
                    profile_text += f"    {emoji} {escape_markdown(rarity)}: {count}\n"

            if last_card:
                profile_text += "\n🎴 **Остання картка:**\n"
                profile_text += f"  📛 {escape_markdown(last_card.name)}\n"
                profile_text += f"  {get_biome_emoji(last_card.biome_affinity)} {escape_markdown(last_card.biome_affinity.value)}\n"
                profile_text += f"  {get_rarity_emoji(last_card.rarity)} {escape_markdown(last_card.rarity.value)}"

            await message.answer(
                profile_text,
                parse_mode="Markdown",
                reply_markup=get_profile_keyboard(),
            )
            break

        except Exception as e:
            logger.error(
                "Error in profile command",
                user_id=user.id,
                error=str(e),
                exc_info=True,
            )
            await message.answer("❌ Помилка при завантаженні профілю.")
            break


@router.message(F.text == "🎴 Колекція")
@router.message(Command("inventory"))
async def cmd_inventory(message: Message, page: int = 0) -> None:
    """Show user inventory with pagination."""
    user = message.from_user
    if not user:
        return

    async for session in get_session():
        try:
            # Get total count
            count_stmt = select(func.count(UserCard.id)).where(UserCard.user_id == user.id)
            total_result = await session.execute(count_stmt)
            total_cards = total_result.scalar_one_or_none() or 0

            if total_cards == 0:
                await message.answer(
                    "📦 **Твоя колекція порожня**\n\n"
                    "Збирай картки з аномалій у чаті! Тисни кнопку **✋ Хапнути** швидше за інших.",
                    parse_mode="Markdown",
                    reply_markup=get_main_menu_keyboard(),
                )
                break

            # Calculate pagination
            total_pages = (total_cards + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE
            if page < 0:
                page = 0
            if page >= total_pages:
                page = total_pages - 1

            # Get cards for current page
            cards_stmt = (
                select(UserCard)
                .where(UserCard.user_id == user.id)
                .options(selectinload(UserCard.template))
                .order_by(UserCard.acquired_at.desc())
                .offset(page * CARDS_PER_PAGE)
                .limit(CARDS_PER_PAGE)
            )
            cards_result = await session.execute(cards_stmt)
            cards = list(cards_result.scalars().all())

            # Build inventory text
            inventory_text = f"🎴 **Колекція карток**\n\n"
            inventory_text += f"Сторінка {page + 1} з {total_pages} ({total_cards} карток)\n\n"

            for i, user_card in enumerate(cards, start=page * CARDS_PER_PAGE + 1):
                template = user_card.template
                rarity_emoji = get_rarity_emoji(template.rarity)
                biome_emoji = get_biome_emoji(template.biome_affinity)
                stats = template.stats

                inventory_text += (
                    f"{i}. {biome_emoji} **{escape_markdown(template.name)}** {rarity_emoji}\n"
                    f"   🆔 {user_card.display_id} | ⚔️ {stats.get('atk', 0)} / 🛡️ {stats.get('def', 0)}\n\n"
                )

            keyboard = get_inventory_keyboard(cards, page, total_pages, CARDS_PER_PAGE)

            await message.answer(
                inventory_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            break

        except Exception as e:
            logger.error(
                "Error in inventory command",
                user_id=user.id,
                error=str(e),
                exc_info=True,
            )
            await message.answer("❌ Помилка при завантаженні колекції.")
            break


@router.message(F.text == "📈 Статистика")
@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Show detailed statistics."""
    user = message.from_user
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
                await message.answer(
                    "❌ Користувача не знайдено. Використайте /start для реєстрації.",
                    reply_markup=get_main_menu_keyboard(),
                )
                break

            total_cards = len(db_user.cards)
            cards_by_rarity = {}
            cards_by_biome = {}

            for user_card in db_user.cards:
                template = user_card.template
                rarity = template.rarity.value
                biome = template.biome_affinity.value

                cards_by_rarity[rarity] = cards_by_rarity.get(rarity, 0) + 1
                cards_by_biome[biome] = cards_by_biome.get(biome, 0) + 1

            stats_text = "📈 **Детальна статистика**\n\n"
            stats_text += f"📊 **Загальна інформація:**\n"
            stats_text += f"  • Всього карток: {total_cards}\n\n"

            if cards_by_rarity:
                stats_text += "💎 **По рідкості:**\n"
                for rarity in [Rarity.COMMON, Rarity.RARE, Rarity.EPIC, Rarity.LEGENDARY, Rarity.MYTHIC]:
                    count = cards_by_rarity.get(rarity.value, 0)
                    if count > 0 or total_cards > 0:
                        percentage = (count / total_cards * 100) if total_cards > 0 else 0
                        emoji = get_rarity_emoji(rarity)
                        stats_text += f"  {emoji} {escape_markdown(rarity.value)}: {count} ({percentage:.1f}%)\n"
                stats_text += "\n"

            if cards_by_biome:
                stats_text += "🌍 **По біомам:**\n"
                for biome in BiomeType:
                    count = cards_by_biome.get(biome.value, 0)
                    if count > 0 or total_cards > 0:
                        percentage = (count / total_cards * 100) if total_cards > 0 else 0
                        emoji = get_biome_emoji(biome)
                        stats_text += f"  {emoji} {escape_markdown(biome.value)}: {count} ({percentage:.1f}%)\n"

            await message.answer(
                stats_text,
                parse_mode="Markdown",
                reply_markup=get_stats_keyboard(),
            )
            break

        except Exception as e:
            logger.error(
                "Error in stats command",
                user_id=user.id,
                error=str(e),
                exc_info=True,
            )
            await message.answer("❌ Помилка при завантаженні статистики.")
            break


@router.message(F.text == "❓ Допомога")
@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Show help guide."""
    help_text = (
        "❓ **Допомога**\n\n"
        "🎮 **Хроніки Помийки** - гра-колекціонер карток у Telegram!\n\n"
        "**Основні команди:**\n"
        "• /start - Реєстрація/початок\n"
        "• /menu - Головне меню\n"
        "• /profile або /me - Твій профіль\n"
        "• /inventory - Твоя колекція карток\n"
        "• /stats - Детальна статистика\n"
        "• /help - Ця довідка\n\n"
        "**Як грати:**\n"
        "1️⃣ Сиди в чаті та спілкуйся\n"
        "2️⃣ Іноді з'являються аномалії з картками\n"
        "3️⃣ Тисни **✋ Хапнути** швидше за інших\n"
        "4️⃣ Збирай унікальну колекцію!\n\n"
        "**Типи карток:**\n"
        "⚪ Common - Звичайні\n"
        "🔵 Rare - Рідкісні\n"
        "🟣 Epic - Епічні\n"
        "🟠 Legendary - Легендарні\n"
        "🔴 Mythic - Міфічні\n\n"
        "Бажаємо удачі у зборі карток! 🎴"
    )

    await message.answer(
        help_text,
        parse_mode="Markdown",
        reply_markup=get_help_keyboard(),
    )


# Callback handlers


@router.callback_query(NavigationCallback.filter(F.action == "menu"))
async def handle_menu_navigation(callback: CallbackQuery) -> None:
    """Handle main menu navigation callback."""
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    await safe_edit_text(
        callback.message,
        "🏠 **Головне меню**\n\n" "Оберіть дію з меню нижче:",
        parse_mode="Markdown",
        reply_markup=get_main_menu_inline_keyboard(),
    )
    await safe_callback_answer(callback)


@router.callback_query(NavigationCallback.filter(F.action == "profile"))
async def handle_profile_navigation(callback: CallbackQuery) -> None:
    """Handle profile navigation callback."""
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    # Redirect to profile command logic
    user = callback.from_user
    if not user:
        await safe_callback_answer(callback,"Помилка", show_alert=True)
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
                await callback.message.edit_text(
                    "❌ Користувача не знайдено. Використайте /start для реєстрації.",
                )
                await safe_callback_answer(callback)
                break

            total_cards = len(db_user.cards)
            cards_by_rarity = {}
            cards_by_biome = {}

            for user_card in db_user.cards:
                template = user_card.template
                rarity = template.rarity.value
                biome = template.biome_affinity.value

                cards_by_rarity[rarity] = cards_by_rarity.get(rarity, 0) + 1
                cards_by_biome[biome] = cards_by_biome.get(biome, 0) + 1

            last_card = None
            if db_user.cards:
                sorted_cards = sorted(db_user.cards, key=lambda c: c.acquired_at, reverse=True)
                last_card = sorted_cards[0].template

            profile_text = "📊 **Профіль Сміттяра**\n\n"
            profile_text += f"👤 **Ім'я:** {escape_markdown(user.first_name or 'Невідомо')}\n"
            if user.username:
                profile_text += f"🔗 **Username:** @{escape_markdown(user.username)}\n"
            profile_text += f"💰 **Баланс:** {db_user.balance}\n\n"

            profile_text += "📦 **Колекція:**\n"
            profile_text += f"  • Всього карток: {total_cards}\n"

            if cards_by_rarity:
                profile_text += "  • По рідкості:\n"
                for rarity, count in sorted(cards_by_rarity.items()):
                    emoji = get_rarity_emoji(Rarity(rarity))
                    profile_text += f"    {emoji} {escape_markdown(rarity)}: {count}\n"

            if last_card:
                profile_text += "\n🎴 **Остання картка:**\n"
                profile_text += f"  📛 {escape_markdown(last_card.name)}\n"
                profile_text += f"  {get_biome_emoji(last_card.biome_affinity)} {escape_markdown(last_card.biome_affinity.value)}\n"
                profile_text += f"  {get_rarity_emoji(last_card.rarity)} {escape_markdown(last_card.rarity.value)}"

            await safe_edit_text(
                callback.message,
                profile_text,
                parse_mode="Markdown",
                reply_markup=get_profile_keyboard(),
            )
            await safe_callback_answer(callback)
            break

        except Exception as e:
            logger.error(
                "Error in profile navigation",
                user_id=user.id,
                error=str(e),
                exc_info=True,
            )
            await safe_callback_answer(callback,"❌ Помилка", show_alert=True)
            break


@router.callback_query(NavigationCallback.filter(F.action == "inventory"))
async def handle_inventory_navigation(callback: CallbackQuery) -> None:
    """Handle inventory navigation callback."""
    await _show_inventory(callback, page=0)


@router.callback_query(NavigationCallback.filter(F.action == "stats"))
async def handle_stats_navigation(callback: CallbackQuery) -> None:
    """Handle stats navigation callback."""
    await _show_stats(callback)


@router.callback_query(NavigationCallback.filter(F.action == "help"))
async def handle_help_navigation(callback: CallbackQuery) -> None:
    """Handle help navigation callback."""
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    help_text = (
        "❓ **Допомога**\n\n"
        "🎮 **Хроніки Помийки** - гра-колекціонер карток у Telegram!\n\n"
        "**Основні команди:**\n"
        "• /start - Реєстрація/початок\n"
        "• /menu - Головне меню\n"
        "• /profile або /me - Твій профіль\n"
        "• /inventory - Твоя колекція карток\n"
        "• /stats - Детальна статистика\n"
        "• /help - Ця довідка\n\n"
        "**Як грати:**\n"
        "1️⃣ Сиди в чаті та спілкуйся\n"
        "2️⃣ Іноді з'являються аномалії з картками\n"
        "3️⃣ Тисни **✋ Хапнути** швидше за інших\n"
        "4️⃣ Збирай унікальну колекцію!\n\n"
        "**Типи карток:**\n"
        "⚪ Common - Звичайні\n"
        "🔵 Rare - Рідкісні\n"
        "🟣 Epic - Епічні\n"
        "🟠 Legendary - Легендарні\n"
        "🔴 Mythic - Міфічні\n\n"
        "Бажаємо удачі у зборі карток! 🎴"
    )

    await safe_edit_text(
        callback.message,
        help_text,
        parse_mode="Markdown",
        reply_markup=get_help_keyboard(),
    )
    await safe_callback_answer(callback)


@router.callback_query(InventoryCallback.filter())
async def handle_inventory_pagination(
    callback: CallbackQuery, callback_data: InventoryCallback
) -> None:
    """Handle inventory pagination."""
    await _show_inventory(callback, page=callback_data.page)


async def _show_inventory(callback: CallbackQuery, page: int) -> None:
    """Show inventory page (shared logic)."""
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    user = callback.from_user
    if not user:
        await safe_callback_answer(callback,"Помилка", show_alert=True)
        return

    async for session in get_session():
        try:
            count_stmt = select(func.count(UserCard.id)).where(UserCard.user_id == user.id)
            total_result = await session.execute(count_stmt)
            total_cards = total_result.scalar_one_or_none() or 0

            if total_cards == 0:
                await safe_edit_text(
                    callback.message,
                    "📦 **Твоя колекція порожня**\n\n"
                    "Збирай картки з аномалій у чаті! Тисни кнопку **✋ Хапнути** швидше за інших.",
                    parse_mode="Markdown",
                    reply_markup=get_help_keyboard(),  # Use inline keyboard for edit_text
                )
                await safe_callback_answer(callback)
                break

            total_pages = (total_cards + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE
            if page < 0:
                page = 0
            if page >= total_pages:
                page = total_pages - 1

            cards_stmt = (
                select(UserCard)
                .where(UserCard.user_id == user.id)
                .options(selectinload(UserCard.template))
                .order_by(UserCard.acquired_at.desc())
                .offset(page * CARDS_PER_PAGE)
                .limit(CARDS_PER_PAGE)
            )
            cards_result = await session.execute(cards_stmt)
            cards = list(cards_result.scalars().all())

            inventory_text = f"🎴 **Колекція карток**\n\n"
            inventory_text += f"Сторінка {page + 1} з {total_pages} ({total_cards} карток)\n\n"

            for i, user_card in enumerate(cards, start=page * CARDS_PER_PAGE + 1):
                template = user_card.template
                rarity_emoji = get_rarity_emoji(template.rarity)
                biome_emoji = get_biome_emoji(template.biome_affinity)
                stats = template.stats

                inventory_text += (
                    f"{i}. {biome_emoji} **{escape_markdown(template.name)}** {rarity_emoji}\n"
                    f"   🆔 {user_card.display_id} | ⚔️ {stats.get('atk', 0)} / 🛡️ {stats.get('def', 0)}\n\n"
                )

            keyboard = get_inventory_keyboard(cards, page, total_pages, CARDS_PER_PAGE)

            await safe_edit_text(
                callback.message,
                inventory_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            await safe_callback_answer(callback)
            break

        except Exception as e:
            logger.error(
                "Error in inventory pagination",
                user_id=user.id,
                error=str(e),
                exc_info=True,
            )
            await safe_callback_answer(callback,"❌ Помилка", show_alert=True)
            break


@router.callback_query(CardViewCallback.filter())
async def handle_card_view(
    callback: CallbackQuery, callback_data: CardViewCallback
) -> None:
    """Handle card detail view."""
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    user = callback.from_user
    if not user:
        await safe_callback_answer(callback,"Помилка", show_alert=True)
        return

    try:
        card_id = UUID(callback_data.card_id)
    except ValueError:
        await safe_callback_answer(callback,"❌ Невірний ID картки", show_alert=True)
        return

    async for session in get_session():
        try:
            card_stmt = (
                select(UserCard)
                .where(UserCard.id == card_id, UserCard.user_id == user.id)
                .options(selectinload(UserCard.template))
            )
            result = await session.execute(card_stmt)
            user_card = result.scalar_one_or_none()

            if not user_card:
                await safe_callback_answer(callback,"❌ Картка не знайдена", show_alert=True)
                break

            template = user_card.template
            stats = template.stats
            biome_emoji = get_biome_emoji(template.biome_affinity)
            rarity_emoji = get_rarity_emoji(template.rarity)

            card_text = f"{biome_emoji} **{escape_markdown(template.name)}**\n\n"
            card_text += f"🆔 **ID:** {user_card.display_id}\n"
            card_text += f"{biome_emoji} **Біом:** {escape_markdown(template.biome_affinity.value)}\n"
            card_text += f"⚔️ **АТАКА:** {stats.get('atk', 0)}\n"
            card_text += f"🛡️ **ЗАХИСТ:** {stats.get('def', 0)}\n"
            if 'meme' in stats:
                card_text += f"🎭 **МЕМНІСТЬ:** {stats.get('meme', 0)}\n"
            card_text += f"{rarity_emoji} **Рідкість:** {escape_markdown(template.rarity.value)}\n\n"
            
            # Display attacks if available
            attacks = template.attacks or []
            if attacks:
                card_text += "**⚔️ Атаки:**\n"
                for i, attack in enumerate(attacks, 1):
                    attack_name = attack.get("name", "Атака")
                    attack_type = attack.get("type", "PHYSICAL")
                    damage = attack.get("damage", 0)
                    energy_cost = attack.get("energy_cost", 1)
                    effect = attack.get("effect", "")
                    status_effect = attack.get("status_effect", "NONE")
                    
                    # Get attack type emoji
                    from database.enums import AttackType, StatusEffect
                    type_emoji_map = {
                        AttackType.FIRE: "🔥",
                        AttackType.WATER: "💧",
                        AttackType.GRASS: "🌿",
                        AttackType.PSYCHIC: "🔮",
                        AttackType.TECHNO: "⚙️",
                        AttackType.DARK: "🌑",
                        AttackType.MEME: "🎭",
                        AttackType.PHYSICAL: "⚔️",
                    }
                    type_emoji = type_emoji_map.get(AttackType(attack_type), "⚔️")
                    
                    card_text += f"{i}. {type_emoji} **{escape_markdown(attack_name)}**\n"
                    card_text += f"   💥 Шкода: {damage} | ⚡ Енергія: {energy_cost}\n"
                    if effect:
                        card_text += f"   📝 {escape_markdown(effect)}\n"
                    if status_effect and status_effect != "NONE":
                        status_emoji_map = {
                            StatusEffect.BURNED: "🔥",
                            StatusEffect.POISONED: "☠️",
                            StatusEffect.PARALYZED: "⚡",
                            StatusEffect.CONFUSED: "🌀",
                            StatusEffect.ASLEEP: "😴",
                            StatusEffect.FROZEN: "❄️",
                        }
                        status_emoji = status_emoji_map.get(StatusEffect(status_effect), "🔮")
                        card_text += f"   {status_emoji} Статус: {StatusEffect(status_effect).value}\n"
                    card_text += "\n"
            else:
                # Fallback: show basic attack using ATK stat
                card_text += "**⚔️ Атака:** Базова атака (використовує ATK)\n\n"
            
            # Display weakness if available
            if template.weakness:
                weak_type = AttackType(template.weakness.get("type", ""))
                multiplier = template.weakness.get("multiplier", 2.0)
                type_emoji_map = {
                    AttackType.FIRE: "🔥",
                    AttackType.WATER: "💧",
                    AttackType.GRASS: "🌿",
                    AttackType.PSYCHIC: "🔮",
                    AttackType.TECHNO: "⚙️",
                    AttackType.DARK: "🌑",
                    AttackType.MEME: "🎭",
                    AttackType.PHYSICAL: "⚔️",
                }
                type_emoji = type_emoji_map.get(weak_type, "⚔️")
                card_text += f"⚠️ **Слабкість:** {type_emoji} {weak_type.value} (x{multiplier})\n"
            
            # Display resistance if available
            if template.resistance:
                resist_type = AttackType(template.resistance.get("type", ""))
                reduction = template.resistance.get("reduction", 0)
                type_emoji_map = {
                    AttackType.FIRE: "🔥",
                    AttackType.WATER: "💧",
                    AttackType.GRASS: "🌿",
                    AttackType.PSYCHIC: "🔮",
                    AttackType.TECHNO: "⚙️",
                    AttackType.DARK: "🌑",
                    AttackType.MEME: "🎭",
                    AttackType.PHYSICAL: "⚔️",
                }
                type_emoji = type_emoji_map.get(resist_type, "⚔️")
                if reduction > 0:
                    card_text += f"🛡️ **Стійкість:** {type_emoji} {resist_type.value} (-{reduction} шкоди)\n"
                else:
                    card_text += f"🛡️ **Стійкість:** {type_emoji} {resist_type.value} (x0.5)\n"
            
            # Display print_date at bottom (like Pokemon TCG cards)
            if template.print_date:
                card_text += f"\n\n📅 {template.print_date}"

            keyboard = get_card_detail_keyboard(
                card_id=str(user_card.id), return_page=callback_data.return_page
            )

            # Try to send photo if image exists
            if template.image_url:
                try:
                    from pathlib import Path
                    from database.enums import Rarity

                    image_path = Path(template.image_url)
                    is_rare = template.rarity in (Rarity.EPIC, Rarity.LEGENDARY, Rarity.MYTHIC)
                    
                    await callback.message.delete()
                    
                    if is_rare:
                        # For rare cards, try animated MP4 first (sent as animation/GIF), then GIF fallback
                        animated_mp4_path = image_path.parent / f"{image_path.stem}_animated.mp4"
                        animated_gif_path = image_path.parent / f"{image_path.stem}_animated.gif"
                        
                        if animated_mp4_path.exists():
                            # Use helper function for proper animation parameters
                            await send_card_animation_to_callback(
                                callback.message,
                                animated_mp4_path,
                                card_text,
                                reply_markup=keyboard,
                                parse_mode="Markdown",
                            )
                            await safe_callback_answer(callback)
                            break
                        elif animated_gif_path.exists():
                            # Fallback to GIF if MP4 doesn't exist
                            await send_card_animation_to_callback(
                                callback.message,
                                animated_gif_path,
                                card_text,
                                reply_markup=keyboard,
                                parse_mode="Markdown",
                            )
                            await safe_callback_answer(callback)
                            break
                    
                    # Fallback to regular photo (for Common/Rare or if animated doesn't exist)
                    if image_path.exists():
                        photo_file = FSInputFile(str(image_path))
                        await callback.message.answer_photo(
                            photo=photo_file,
                            caption=card_text,
                            parse_mode="Markdown",
                            reply_markup=keyboard,
                        )
                        await safe_callback_answer(callback)
                        break
                except Exception as e:
                    logger.warning(
                        "Failed to send card image",
                        error=str(e),
                        image_url=template.image_url,
                    )

            # Fallback to text message
            await safe_edit_text(
                callback.message,
                card_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            await safe_callback_answer(callback)
            break

        except Exception as e:
            logger.error(
                "Error in card view",
                user_id=user.id,
                card_id=str(card_id),
                error=str(e),
                exc_info=True,
            )
            await safe_callback_answer(callback,"❌ Помилка при завантаженні картки", show_alert=True)
            break


@router.callback_query(StatsCallback.filter(F.section == "refresh"))
async def handle_stats_refresh(callback: CallbackQuery) -> None:
    """Handle stats refresh callback."""
    await _show_stats(callback)


async def _show_stats(callback: CallbackQuery) -> None:
    """Show stats (shared logic)."""
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    user = callback.from_user
    if not user:
        await safe_callback_answer(callback,"Помилка", show_alert=True)
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
                await callback.message.edit_text(
                    "❌ Користувача не знайдено. Використайте /start для реєстрації.",
                )
                await safe_callback_answer(callback)
                break

            total_cards = len(db_user.cards)
            cards_by_rarity = {}
            cards_by_biome = {}

            for user_card in db_user.cards:
                template = user_card.template
                rarity = template.rarity.value
                biome = template.biome_affinity.value

                cards_by_rarity[rarity] = cards_by_rarity.get(rarity, 0) + 1
                cards_by_biome[biome] = cards_by_biome.get(biome, 0) + 1

            stats_text = "📈 **Детальна статистика**\n\n"
            stats_text += f"📊 **Загальна інформація:**\n"
            stats_text += f"  • Всього карток: {total_cards}\n\n"

            if cards_by_rarity:
                stats_text += "💎 **По рідкості:**\n"
                for rarity in [Rarity.COMMON, Rarity.RARE, Rarity.EPIC, Rarity.LEGENDARY, Rarity.MYTHIC]:
                    count = cards_by_rarity.get(rarity.value, 0)
                    if count > 0 or total_cards > 0:
                        percentage = (count / total_cards * 100) if total_cards > 0 else 0
                        emoji = get_rarity_emoji(rarity)
                        stats_text += f"  {emoji} {escape_markdown(rarity.value)}: {count} ({percentage:.1f}%)\n"
                stats_text += "\n"

            if cards_by_biome:
                stats_text += "🌍 **По біомам:**\n"
                for biome in BiomeType:
                    count = cards_by_biome.get(biome.value, 0)
                    if count > 0 or total_cards > 0:
                        percentage = (count / total_cards * 100) if total_cards > 0 else 0
                        emoji = get_biome_emoji(biome)
                        stats_text += f"  {emoji} {escape_markdown(biome.value)}: {count} ({percentage:.1f}%)\n"

            await safe_edit_text(
                callback.message,
                stats_text,
                parse_mode="Markdown",
                reply_markup=get_stats_keyboard(),
            )
            await safe_callback_answer(callback)
            break

        except Exception as e:
            logger.error(
                "Error in stats refresh",
                user_id=user.id,
                error=str(e),
                exc_info=True,
            )
            await safe_callback_answer(callback,"❌ Помилка", show_alert=True)
            break


def get_scrap_reward(rarity: Rarity) -> int:
    """
    Calculate scrap reward based on card rarity.

    Args:
        rarity: Card rarity level

    Returns:
        Amount of scraps to award
    """
    reward_map = {
        Rarity.COMMON: 5,
        Rarity.RARE: 30,
        Rarity.EPIC: 75,
        Rarity.LEGENDARY: 500,
        Rarity.MYTHIC: 1000,
    }
    return reward_map.get(rarity, 5)


@router.callback_query(ScrapCardCallback.filter(F.confirm == False))
async def handle_scrap_card_request(
    callback: CallbackQuery, callback_data: ScrapCardCallback
) -> None:
    """Handle initial scrap card request (show confirmation)."""
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    user = callback.from_user
    if not user:
        await safe_callback_answer(callback,"Помилка", show_alert=True)
        return

    try:
        card_id = UUID(callback_data.card_id)
    except ValueError:
        await safe_callback_answer(callback,"❌ Невірний ID картки", show_alert=True)
        return

    async for session in get_session():
        try:
            card_stmt = (
                select(UserCard)
                .where(UserCard.id == card_id, UserCard.user_id == user.id)
                .options(selectinload(UserCard.template))
            )
            result = await session.execute(card_stmt)
            user_card = result.scalar_one_or_none()

            if not user_card:
                await safe_callback_answer(callback,"❌ Картка не знайдена", show_alert=True)
                break

            template = user_card.template
            reward = get_scrap_reward(template.rarity)
            rarity_emoji = get_rarity_emoji(template.rarity)

            confirm_text = (
                f"⚠️ **Підтвердження розпилення**\n\n"
                f"Ти збираєшся розпилити картку:\n"
                f"{rarity_emoji} **{escape_markdown(template.name)}**\n\n"
                f"🔩 Ти отримаєш: **{reward} Решток**\n\n"
                f"❌ **Увага:** Цю дію неможливо скасувати!"
            )

            keyboard = get_scrap_confirm_keyboard(
                card_id=callback_data.card_id, return_page=callback_data.return_page
            )

            await safe_edit_text(
                callback.message,
                confirm_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            await safe_callback_answer(callback)
            break

        except Exception as e:
            logger.error(
                "Error in scrap card request",
                user_id=user.id,
                card_id=str(card_id),
                error=str(e),
                exc_info=True,
            )
            await safe_callback_answer(callback,"❌ Помилка", show_alert=True)
            break


@router.callback_query(ScrapCardCallback.filter(F.confirm == True))
async def handle_scrap_card_confirm(
    callback: CallbackQuery, callback_data: ScrapCardCallback
) -> None:
    """Handle confirmed card scrapping (delete card and award scraps)."""
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    user = callback.from_user
    if not user:
        await safe_callback_answer(callback,"Помилка", show_alert=True)
        return

    try:
        card_id = UUID(callback_data.card_id)
    except ValueError:
        await safe_callback_answer(callback,"❌ Невірний ID картки", show_alert=True)
        return

    async for session in get_session():
        try:
            # Get card with template and user
            card_stmt = (
                select(UserCard)
                .where(UserCard.id == card_id, UserCard.user_id == user.id)
                .options(selectinload(UserCard.template), selectinload(UserCard.user))
            )
            result = await session.execute(card_stmt)
            user_card = result.scalar_one_or_none()

            if not user_card:
                await safe_callback_answer(callback,"❌ Картка не знайдена", show_alert=True)
                break

            template = user_card.template
            db_user = user_card.user
            reward = get_scrap_reward(template.rarity)
            rarity_emoji = get_rarity_emoji(template.rarity)
            card_name = template.name

            # Delete card and update balance
            delete_stmt = delete(UserCard).where(UserCard.id == card_id)
            await session.execute(delete_stmt)

            # Update user balance
            db_user.balance += reward
            session.add(db_user)

            await session.commit()

            success_text = (
                f"✅ **Картку розпилено!**\n\n"
                f"{rarity_emoji} **{escape_markdown(card_name)}** було знищено.\n\n"
                f"🔩 Ти отримав: **{reward} Решток**\n"
                f"💰 Твій баланс: **{db_user.balance} Решток**"
            )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="◀️ Назад до колекції",
                            callback_data=InventoryCallback(
                                page=callback_data.return_page
                            ).pack(),
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            text="🏠 Головне меню",
                            callback_data=NavigationCallback(action="menu").pack(),
                        ),
                    ],
                ]
            )

            await safe_edit_text(
                callback.message,
                success_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            await safe_callback_answer(callback,f"✅ Отримано {reward} Решток!")
            break

        except Exception as e:
            logger.error(
                "Error in scrap card confirm",
                user_id=user.id,
                card_id=str(card_id),
                error=str(e),
                exc_info=True,
            )
            await session.rollback()
            await safe_callback_answer(callback,"❌ Помилка при розпиленні картки", show_alert=True)
            break
