"""Command definitions for bot command hints."""

from aiogram.types import BotCommand

from config import settings


def get_player_commands() -> list[BotCommand]:
    """
    Get list of player commands with Ukrainian descriptions.

    Returns:
        List of BotCommand objects for regular users.
    """
    return [
        BotCommand(command="start", description="Реєстрація/початок гри"),
        BotCommand(command="menu", description="Головне меню"),
        BotCommand(command="me", description="Твій профіль"),
        BotCommand(command="profile", description="Твій профіль"),
        BotCommand(command="inventory", description="Твоя колекція карток"),
        BotCommand(command="stats", description="Детальна статистика"),
        BotCommand(command="help", description="Довідка"),
    ]


def get_admin_commands() -> list[BotCommand]:
    """
    Get list of admin commands with Ukrainian descriptions.

    Returns:
        List of BotCommand objects for admin users.
    """
    return [
        BotCommand(command="newcard", description="Створити нову картку вручну"),
        BotCommand(command="autocard", description="Автоматично створити картку з повідомлення користувача"),
    ]


def get_all_commands() -> list[BotCommand]:
    """
    Get list of all commands (player + admin) with Ukrainian descriptions.

    Returns:
        List of BotCommand objects for admin users.
    """
    return get_player_commands() + get_admin_commands()


def is_admin(user_id: int) -> bool:
    """
    Check if user is an admin.

    Args:
        user_id: Telegram user ID.

    Returns:
        True if user is admin, False otherwise.
    """
    return user_id in settings.admin_user_ids
