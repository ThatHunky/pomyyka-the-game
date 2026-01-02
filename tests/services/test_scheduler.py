"""Tests for drop scheduler service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.scheduler import DropScheduler


@pytest.mark.unit
class TestDropScheduler:
    """Test DropScheduler service."""

    @pytest.mark.asyncio
    async def test_scheduler_initialization(self, mock_bot):
        """Test scheduler initialization."""
        scheduler = DropScheduler(mock_bot, interval_minutes=10, drop_chance=0.05)
        assert scheduler._bot == mock_bot
        assert scheduler._interval_minutes == 10
        assert scheduler._drop_chance == 0.05

    @pytest.mark.asyncio
    async def test_scheduler_start(self, mock_bot):
        """Test starting the scheduler."""
        scheduler = DropScheduler(mock_bot)
        await scheduler.start()
        assert scheduler._scheduler is not None
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_scheduler_stop(self, mock_bot):
        """Test stopping the scheduler."""
        scheduler = DropScheduler(mock_bot)
        await scheduler.start()
        await scheduler.stop()
        assert scheduler._scheduler is None

    @pytest.mark.asyncio
    async def test_scheduler_double_start(self, mock_bot):
        """Test that starting scheduler twice doesn't cause issues."""
        scheduler = DropScheduler(mock_bot)
        await scheduler.start()
        await scheduler.start()  # Should not raise
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_scheduler_stop_when_not_started(self, mock_bot):
        """Test stopping scheduler when not started."""
        scheduler = DropScheduler(mock_bot)
        await scheduler.stop()  # Should not raise
