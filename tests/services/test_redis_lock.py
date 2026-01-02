"""Tests for Redis lock service."""

import pytest

from services.redis_lock import DropManager


@pytest.mark.unit
class TestDropManager:
    """Test DropManager atomic operations."""

    @pytest.mark.asyncio
    async def test_try_claim_drop_success(self, drop_manager):
        """Test successful drop claim."""
        message_id = 12345
        user_id = 67890
        
        claimed = await drop_manager.try_claim_drop(message_id, user_id)
        assert claimed is True, "Should successfully claim drop"

    @pytest.mark.asyncio
    async def test_try_claim_drop_already_claimed(self, drop_manager):
        """Test that second claim attempt fails."""
        message_id = 12345
        user_id1 = 67890
        user_id2 = 11111
        
        # First claim should succeed
        claimed1 = await drop_manager.try_claim_drop(message_id, user_id1)
        assert claimed1 is True, "First claim should succeed"
        
        # Second claim should fail
        claimed2 = await drop_manager.try_claim_drop(message_id, user_id2)
        assert claimed2 is False, "Second claim should fail"

    @pytest.mark.asyncio
    async def test_try_claim_drop_different_messages(self, drop_manager):
        """Test that different messages can be claimed independently."""
        user_id = 67890
        
        claimed1 = await drop_manager.try_claim_drop(111, user_id)
        claimed2 = await drop_manager.try_claim_drop(222, user_id)
        
        assert claimed1 is True, "First message should be claimable"
        assert claimed2 is True, "Second message should be claimable independently"

    @pytest.mark.asyncio
    async def test_try_claim_drop_custom_ttl(self, drop_manager):
        """Test drop claim with custom TTL."""
        message_id = 12345
        user_id = 67890
        
        claimed = await drop_manager.try_claim_drop(message_id, user_id, ttl=600)
        assert claimed is True, "Should claim with custom TTL"

    @pytest.mark.asyncio
    async def test_release_drop_success(self, drop_manager):
        """Test releasing a claimed drop."""
        message_id = 12345
        user_id = 67890
        
        # Claim drop
        await drop_manager.try_claim_drop(message_id, user_id)
        
        # Release drop
        released = await drop_manager.release_drop(message_id)
        assert released is True, "Should successfully release drop"
        
        # Should be claimable again
        claimed_again = await drop_manager.try_claim_drop(message_id, user_id)
        assert claimed_again is True, "Should be claimable after release"

    @pytest.mark.asyncio
    async def test_release_drop_not_claimed(self, drop_manager):
        """Test releasing a drop that was never claimed."""
        message_id = 12345
        
        released = await drop_manager.release_drop(message_id)
        assert released is False, "Should return False for unclaimed drop"

    @pytest.mark.asyncio
    async def test_get_claim_owner_success(self, drop_manager):
        """Test getting the owner of a claimed drop."""
        message_id = 12345
        user_id = 67890
        
        await drop_manager.try_claim_drop(message_id, user_id)
        
        owner = await drop_manager.get_claim_owner(message_id)
        assert owner == user_id, "Should return correct owner"

    @pytest.mark.asyncio
    async def test_get_claim_owner_not_claimed(self, drop_manager):
        """Test getting owner of unclaimed drop."""
        message_id = 12345
        
        owner = await drop_manager.get_claim_owner(message_id)
        assert owner is None, "Should return None for unclaimed drop"

    @pytest.mark.asyncio
    async def test_get_claim_owner_after_release(self, drop_manager):
        """Test getting owner after drop is released."""
        message_id = 12345
        user_id = 67890
        
        await drop_manager.try_claim_drop(message_id, user_id)
        await drop_manager.release_drop(message_id)
        
        owner = await drop_manager.get_claim_owner(message_id)
        assert owner is None, "Should return None after release"

    @pytest.mark.asyncio
    async def test_race_condition_prevention(self, drop_manager):
        """Test that race conditions are prevented (atomic operation)."""
        message_id = 12345
        user_id1 = 67890
        user_id2 = 11111
        
        # Simulate concurrent claims
        import asyncio
        
        async def claim(user_id):
            return await drop_manager.try_claim_drop(message_id, user_id)
        
        results = await asyncio.gather(claim(user_id1), claim(user_id2))
        
        # Only one should succeed
        assert sum(results) == 1, "Only one claim should succeed in race condition"

    @pytest.mark.asyncio
    async def test_close_cleanup(self, redis_client):
        """Test that close properly cleans up resources."""
        manager = DropManager(redis_client=redis_client)
        
        # Should not raise
        await manager.close()
        
        # Second close should be safe
        await manager.close()
