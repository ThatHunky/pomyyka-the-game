"""Tests for cleanup service."""

import pytest

from services.cleanup import CleanupService


@pytest.mark.unit
class TestCleanupService:
    """Test CleanupService."""

    def test_cleanup_service_initialization(self):
        """Test cleanup service initialization."""
        service = CleanupService(retention_days=7)
        assert service._retention_days == 7

    @pytest.mark.asyncio
    async def test_cleanup_service_start_stop(self):
        """Test starting and stopping cleanup service."""
        service = CleanupService()
        await service.start()
        assert service._scheduler is not None
        await service.stop()
        assert service._scheduler is None

    @pytest.mark.asyncio
    async def test_cleanup_service_double_start(self):
        """Test that starting service twice doesn't cause issues."""
        service = CleanupService()
        await service.start()
        await service.start()  # Should not raise
        await service.stop()
