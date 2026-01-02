"""Keyboard builders and callback data classes for bot interactions."""

from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
)


class NavigationCallback(CallbackData, prefix="nav"):
    """Callback data for main menu navigation."""

    action: str  # "menu", "profile", "inventory", "stats", "help"


class InventoryCallback(CallbackData, prefix="inv"):
    """Callback data for inventory pagination."""

    page: int  # Page number (0-indexed)


class CardViewCallback(CallbackData, prefix="card"):
    """Callback data for viewing card details."""

    card_id: str  # UUID as string
    return_page: int = 0  # Page to return to in inventory


class StatsCallback(CallbackData, prefix="stats"):
    """Callback data for stats sections."""

    section: str  # "main", "rarity", "biome", "refresh"


class ScrapCardCallback(CallbackData, prefix="scrap"):
    """Callback data for scrapping (deleting) cards."""

    card_id: str  # UUID as string
    return_page: int = 0  # Page to return to in inventory
    confirm: bool = False  # Whether this is a confirmation step


class TradeProposeCallback(CallbackData, prefix="trade_propose"):
    """Callback data for proposing a trade."""

    session_id: str  # Trade session ID


class TradeConfirmCallback(CallbackData, prefix="trade_confirm"):
    """Callback data for confirming a trade."""

    session_id: str  # Trade session ID


class TradeCancelCallback(CallbackData, prefix="trade_cancel"):
    """Callback data for cancelling a trade."""

    session_id: str  # Trade session ID


class DuelAcceptCallback(CallbackData, prefix="duel_accept"):
    """Callback data for accepting/rejecting a duel challenge."""

    session_id: str  # Battle session ID
    accept: bool  # True to accept, False to reject


class DuelStakeCallback(CallbackData, prefix="duel_stake"):
    """Callback data for setting duel stake."""

    session_id: str  # Battle session ID
    stake: int  # Stake amount in scraps


class DuelConfirmStakeCallback(CallbackData, prefix="duel_confirm_stake"):
    """Callback data for confirming duel stake."""

    session_id: str  # Battle session ID


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Create main menu Reply keyboard."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Профіль"),
                KeyboardButton(text="🎴 Колекція"),
            ],
            [
                KeyboardButton(text="📈 Статистика"),
                KeyboardButton(text="❓ Допомога"),
            ],
        ],
        resize_keyboard=True,
        persistent=True,
    )


def get_main_menu_inline_keyboard() -> InlineKeyboardMarkup:
    """Create main menu inline keyboard for message editing."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Профіль",
                    callback_data=NavigationCallback(action="profile").pack(),
                ),
                InlineKeyboardButton(
                    text="🎴 Колекція",
                    callback_data=NavigationCallback(action="inventory").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📈 Статистика",
                    callback_data=NavigationCallback(action="stats").pack(),
                ),
                InlineKeyboardButton(
                    text="❓ Допомога",
                    callback_data=NavigationCallback(action="help").pack(),
                ),
            ],
        ]
    )


def remove_keyboard() -> ReplyKeyboardRemove:
    """Remove Reply keyboard."""
    return ReplyKeyboardRemove(remove_keyboard=True)


def get_profile_keyboard() -> InlineKeyboardMarkup:
    """Create profile inline keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📈 Детальна статистика",
                    callback_data=NavigationCallback(action="stats").pack(),
                ),
                InlineKeyboardButton(
                    text="🎴 Моя колекція",
                    callback_data=NavigationCallback(action="inventory").pack(),
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


def get_inventory_keyboard(
    cards: list,
    current_page: int,
    total_pages: int,
    cards_per_page: int = 10,
) -> InlineKeyboardMarkup:
    """
    Create inventory inline keyboard with card buttons and pagination.

    Args:
        cards: List of UserCard objects for current page
        current_page: Current page number (0-indexed)
        total_pages: Total number of pages
        cards_per_page: Number of cards per page

    Returns:
        InlineKeyboardMarkup with card buttons and pagination
    """
    buttons = []

    # Add card buttons (max 2 cards per row for better UX)
    for i in range(0, len(cards), 2):
        row = []
        for card in cards[i : i + 2]:
            template = card.template
            # Truncate long names and add emoji for rarity
            card_name = template.name
            if len(card_name) > 20:
                card_name = card_name[:17] + "..."
            button_text = f"📛 {card_name}"
            row.append(
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=CardViewCallback(
                        card_id=str(card.id), return_page=current_page
                    ).pack(),
                )
            )
        if row:
            buttons.append(row)

    # Add pagination controls
    nav_buttons = []
    if current_page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                text="◀️ Попередня",
                callback_data=InventoryCallback(page=current_page - 1).pack(),
            )
        )
    if current_page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton(
                text="▶️ Наступна",
                callback_data=InventoryCallback(page=current_page + 1).pack(),
            )
        )

    if nav_buttons:
        buttons.append(nav_buttons)

    # Add back to menu button
    buttons.append(
        [
            InlineKeyboardButton(
                text="🏠 Головне меню",
                callback_data=NavigationCallback(action="menu").pack(),
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_card_detail_keyboard(
    card_id: str, return_page: int = 0, show_scrap: bool = True
) -> InlineKeyboardMarkup:
    """
    Create card detail view inline keyboard.

    Args:
        card_id: UUID of the card as string
        return_page: Page number to return to in inventory
        show_scrap: Whether to show the scrap button

    Returns:
        InlineKeyboardMarkup with navigation buttons
    """
    buttons = []
    
    if show_scrap:
        buttons.append([
            InlineKeyboardButton(
                text="🔩 Розпилити (Отримати Рештки)",
                callback_data=ScrapCardCallback(
                    card_id=card_id, return_page=return_page, confirm=False
                ).pack(),
            ),
        ])
    
    buttons.extend([
        [
            InlineKeyboardButton(
                text="◀️ Назад до колекції",
                callback_data=InventoryCallback(page=return_page).pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text="🏠 Головне меню",
                callback_data=NavigationCallback(action="menu").pack(),
            ),
        ],
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_scrap_confirm_keyboard(card_id: str, return_page: int = 0) -> InlineKeyboardMarkup:
    """
    Create confirmation keyboard for card scrapping.

    Args:
        card_id: UUID of the card as string
        return_page: Page number to return to in inventory

    Returns:
        InlineKeyboardMarkup with confirmation buttons
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Так, розпилити",
                    callback_data=ScrapCardCallback(
                        card_id=card_id, return_page=return_page, confirm=True
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="❌ Скасувати",
                    callback_data=CardViewCallback(
                        card_id=card_id, return_page=return_page
                    ).pack(),
                ),
            ],
        ]
    )


def get_stats_keyboard() -> InlineKeyboardMarkup:
    """Create stats dashboard inline keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Оновити",
                    callback_data=StatsCallback(section="refresh").pack(),
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


def get_help_keyboard() -> InlineKeyboardMarkup:
    """Create help guide inline keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏠 Головне меню",
                    callback_data=NavigationCallback(action="menu").pack(),
                ),
            ],
        ]
    )
