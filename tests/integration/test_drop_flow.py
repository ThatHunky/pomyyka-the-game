"""Integration tests for drop claim flow."""

import pytest
from uuid import uuid4

from database.enums import BiomeType, Rarity
from database.models import CardTemplate, GroupChat, User
from services.redis_lock import DropManager


@pytest.mark.integration
class TestDropFlow:
    """Test end-to-end drop claim flow."""

    @pytest.mark.asyncio
    async def test_complete_drop_claim_flow(self, db_session, redis_client, drop_manager):
        """Test complete flow from drop creation to claim."""
        # Create user
        user = User(telegram_id=12345, username="testuser", balance=1000)
        db_session.add(user)
        await db_session.commit()
        
        # Create group chat
        group = GroupChat(chat_id=-12345, title="Test Group", is_active=True)
        db_session.add(group)
        await db_session.commit()
        
        # Create card template
        template = CardTemplate(
            id=uuid4(),
            name="Test Card",
            rarity=Rarity.COMMON,
            biome_affinity=BiomeType.NORMAL,
            stats={"atk": 50, "def": 50, "meme": 10},
        )
        db_session.add(template)
        await db_session.commit()
        
        # Simulate drop claim
        message_id = 99999
        claimed = await drop_manager.try_claim_drop(message_id, user.telegram_id)
        assert claimed is True, "Should successfully claim drop"
        
        # Verify claim owner
        owner = await drop_manager.get_claim_owner(message_id)
        assert owner == user.telegram_id, "Should return correct owner"
        
        # Try to claim again (should fail)
        claimed_again = await drop_manager.try_claim_drop(message_id, 99999)
        assert claimed_again is False, "Second claim should fail"
