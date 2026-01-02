"""Tests for command utility functions."""

import pytest
from unittest.mock import patch

from aiogram.types import BotCommand
from utils.commands import get_admin_commands, get_all_commands, get_player_commands, is_admin


@pytest.mark.unit
class TestCommands:
    """Test command utility functions."""

    def test_get_player_commands_returns_list(self):
        """Test that get_player_commands returns a list."""
        commands = get_player_commands()
        assert isinstance(commands, list), "Should return a list"

    def test_get_player_commands_contains_start(self):
        """Test that player commands include /start."""
        commands = get_player_commands()
        command_names = [cmd.command for cmd in commands]
        assert "start" in command_names, "Should include start command"

    def test_get_player_commands_all_bot_commands(self):
        """Test that all returned items are BotCommand instances."""
        commands = get_player_commands()
        assert all(isinstance(cmd, BotCommand) for cmd in commands), "All items should be BotCommand"

    def test_get_admin_commands_returns_list(self):
        """Test that get_admin_commands returns a list."""
        commands = get_admin_commands()
        assert isinstance(commands, list), "Should return a list"

    def test_get_admin_commands_contains_addcard(self):
        """Test that admin commands include /addcard."""
        commands = get_admin_commands()
        command_names = [cmd.command for cmd in commands]
        assert "addcard" in command_names, "Should include addcard command"

    def test_get_all_commands_includes_player_and_admin(self):
        """Test that get_all_commands includes both player and admin commands."""
        all_commands = get_all_commands()
        player_commands = get_player_commands()
        admin_commands = get_admin_commands()
        
        assert len(all_commands) == len(player_commands) + len(admin_commands), "Should combine both lists"
        
        all_names = [cmd.command for cmd in all_commands]
        player_names = [cmd.command for cmd in player_commands]
        admin_names = [cmd.command for cmd in admin_commands]
        
        assert all(name in all_names for name in player_names), "Should include all player commands"
        assert all(name in all_names for name in admin_names), "Should include all admin commands"

    @patch("utils.commands.settings")
    def test_is_admin_true_when_in_list(self, mock_settings):
        """Test that is_admin returns True when user is in admin list."""
        mock_settings.admin_user_ids = [123, 456, 789]
        assert is_admin(123) is True, "Should return True for admin user"
        assert is_admin(456) is True, "Should return True for admin user"

    @patch("utils.commands.settings")
    def test_is_admin_false_when_not_in_list(self, mock_settings):
        """Test that is_admin returns False when user is not in admin list."""
        mock_settings.admin_user_ids = [123, 456, 789]
        assert is_admin(999) is False, "Should return False for non-admin user"

    @patch("utils.commands.settings")
    def test_is_admin_false_when_list_empty(self, mock_settings):
        """Test that is_admin returns False when admin list is empty."""
        mock_settings.admin_user_ids = []
        assert is_admin(123) is False, "Should return False when no admins configured"

    @patch("utils.commands.settings")
    def test_is_admin_handles_single_admin(self, mock_settings):
        """Test that is_admin works with single admin."""
        mock_settings.admin_user_ids = [123]
        assert is_admin(123) is True, "Should return True for single admin"
        assert is_admin(456) is False, "Should return False for non-admin"
