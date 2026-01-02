"""Tests for user registration middleware."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import CallbackQuery, Message, User as TelegramUser
from middlewares.user_registration import UserRegistrationMiddleware


@pytest.mark.unit
class TestUserRegistrationMiddleware:
    """Test UserRegistrationMiddleware."""

    @pytest.mark.asyncio
    async def test_middleware_registers_new_user(self, db_session, telegram_user, mock_message):
        """Test that middleware registers new user."""
        middleware = UserRegistrationMiddleware()
        handler = AsyncMock(return_value=None)
        
        # Mock get_session to return our test session
        with patch("middlewares.user_registration.get_session") as mock_get_session:
            mock_get_session.return_value.__aiter__ = lambda x: iter([db_session])
            
            await middleware(handler, mock_message, {"bot": MagicMock()})
            
            # Verify user was created
            from sqlalchemy import select
            from database.models import User
            
            stmt = select(User).where(User.telegram_id == telegram_user.id)
            result = await db_session.execute(stmt)
            user = result.scalar_one_or_none()
            assert user is not None
            assert user.telegram_id == telegram_user.id

    @pytest.mark.asyncio
    async def test_middleware_skips_existing_user(self, db_session, sample_user_db, mock_message):
        """Test that middleware doesn't re-register existing user."""
        middleware = UserRegistrationMiddleware()
        handler = AsyncMock(return_value=None)
        
        original_balance = sample_user_db.balance
        
        with patch("middlewares.user_registration.get_session") as mock_get_session:
            mock_get_session.return_value.__aiter__ = lambda x: iter([db_session])
            
            # Update message to use existing user
            mock_message.from_user.id = sample_user_db.telegram_id
            
            await middleware(handler, mock_message, {"bot": MagicMock()})
            
            # Verify balance unchanged
            await db_session.refresh(sample_user_db)
            assert sample_user_db.balance == original_balance

    @pytest.mark.asyncio
    async def test_middleware_handles_callback_query(self, db_session, telegram_user, mock_callback_query):
        """Test that middleware works with callback queries."""
        middleware = UserRegistrationMiddleware()
        handler = AsyncMock(return_value=None)
        
        with patch("middlewares.user_registration.get_session") as mock_get_session:
            mock_get_session.return_value.__aiter__ = lambda x: iter([db_session])
            
            await middleware(handler, mock_callback_query, {"bot": MagicMock()})
            
            handler.assert_called_once()
