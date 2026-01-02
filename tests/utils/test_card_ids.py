"""Tests for card ID generation utilities."""

import pytest

from database.models import UserCard
from sqlalchemy import select
from utils.card_ids import generate_display_id, generate_unique_display_id


@pytest.mark.unit
class TestCardIds:
    """Test card display ID generation."""

    def test_generate_display_id_format(self):
        """Test that generated IDs follow the correct format."""
        display_id = generate_display_id()
        assert display_id.startswith("POM-"), "ID should start with 'POM-'"
        assert len(display_id) == 8, "ID should be 8 characters (POM-XXXX)"
        assert len(display_id.split("-")[1]) == 4, "Code part should be 4 characters"

    def test_generate_display_id_characters(self):
        """Test that generated IDs use valid characters."""
        display_id = generate_display_id()
        code = display_id.split("-")[1]
        valid_chars = "ABCDEFGHJKLMNPQRSTUVWXYZ2346789"
        assert all(c in valid_chars for c in code), "Code should only use valid characters"

    def test_generate_display_id_uniqueness(self):
        """Test that multiple calls generate different IDs (high probability)."""
        ids = {generate_display_id() for _ in range(100)}
        # With 4 characters from 30 char set, collision probability is low
        assert len(ids) > 90, "Most IDs should be unique"

    @pytest.mark.asyncio
    async def test_generate_unique_display_id_success(self, db_session):
        """Test generating a unique display ID when database is empty."""
        display_id = await generate_unique_display_id(db_session)
        assert display_id.startswith("POM-"), "ID should follow format"
        
        # Verify it's actually unique
        stmt = select(UserCard).where(UserCard.display_id == display_id)
        result = await db_session.execute(stmt)
        existing = result.scalar_one_or_none()
        assert existing is None, "Generated ID should not exist in database"

    @pytest.mark.asyncio
    async def test_generate_unique_display_id_handles_duplicates(self, db_session, sample_user_db, sample_card_template_db):
        """Test that function handles duplicate IDs by retrying."""
        # Create a card with a specific ID
        from database.models import UserCard
        from utils.card_ids import generate_unique_display_id
        
        # Manually create a card with known ID
        test_id = "POM-TEST"
        user_card = UserCard(
            user_id=sample_user_db.telegram_id,
            template_id=sample_card_template_db.id,
            display_id=test_id,
        )
        db_session.add(user_card)
        await db_session.commit()
        
        # Generate new ID (should avoid the one we just created)
        new_id = await generate_unique_display_id(db_session)
        assert new_id != test_id, "Should generate different ID when duplicate exists"
        assert new_id.startswith("POM-"), "Should still follow format"

    @pytest.mark.asyncio
    async def test_generate_unique_display_id_fallback(self, db_session, sample_user_db, sample_card_template_db):
        """Test fallback to timestamp-based ID when max attempts reached."""
        # Fill database with many IDs to increase collision chance
        from database.models import UserCard
        
        # Create many cards to increase collision probability
        for i in range(50):
            user_card = UserCard(
                user_id=sample_user_db.telegram_id,
                template_id=sample_card_template_db.id,
                display_id=f"POM-{i:04d}",
            )
            db_session.add(user_card)
        await db_session.commit()
        
        # Generate ID with very low max_attempts to trigger fallback
        display_id = await generate_unique_display_id(db_session, max_attempts=1)
        assert display_id.startswith("POM-"), "Fallback should still follow format"
        # Fallback uses timestamp, so should be numeric
        code = display_id.split("-")[1]
        assert code.isdigit(), "Fallback should use numeric timestamp code"
