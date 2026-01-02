"""Tests for database session management."""

import pytest
from sqlalchemy import select

from database.models import User
from database.session import get_session


@pytest.mark.unit
class TestSession:
    """Test database session management."""

    @pytest.mark.asyncio
    async def test_get_session_yields_session(self, db_engine):
        """Test that get_session yields a session."""
        async for session in get_session():
            assert session is not None
            assert hasattr(session, "execute")

    @pytest.mark.asyncio
    async def test_get_session_commits_on_success(self, db_engine):
        """Test that session commits on successful completion."""
        user_id = 12345
        
        async for session in get_session():
            user = User(telegram_id=user_id, username="test")
            session.add(user)
            # Session should commit after context
        
        # Verify user was committed
        async with db_engine.begin() as conn:
            stmt = select(User).where(User.telegram_id == user_id)
            result = await conn.execute(stmt)
            user = result.scalar_one()
            assert user.telegram_id == user_id

    @pytest.mark.asyncio
    async def test_get_session_rollback_on_error(self, db_engine):
        """Test that session rolls back on error."""
        user_id = 12345
        
        try:
            async for session in get_session():
                user = User(telegram_id=user_id, username="test")
                session.add(user)
                raise ValueError("Test error")
        except ValueError:
            pass
        
        # Verify user was not committed
        async with db_engine.begin() as conn:
            stmt = select(User).where(User.telegram_id == user_id)
            result = await conn.execute(stmt)
            user = result.scalar_one_or_none()
            assert user is None
