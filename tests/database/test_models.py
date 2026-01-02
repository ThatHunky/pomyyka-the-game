"""Tests for database models."""

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from database.enums import AttackType, BiomeType, Rarity, StatusEffect
from database.models import CardTemplate, GroupChat, User, UserCard


@pytest.mark.unit
class TestUser:
    """Test User model."""

    def test_user_creation(self):
        """Test creating a user."""
        user = User(
            telegram_id=12345,
            username="testuser",
            balance=1000,
        )
        assert user.telegram_id == 12345
        assert user.username == "testuser"
        assert user.balance == 1000

    def test_user_default_balance(self):
        """Test user default balance."""
        user = User(telegram_id=12345)
        assert user.balance == 0

    @pytest.mark.asyncio
    async def test_user_relationship_cards(self, db_session, sample_user_db, sample_card_template_db):
        """Test user relationship with cards."""
        from utils.card_ids import generate_unique_display_id
        
        display_id = await generate_unique_display_id(db_session)
        user_card = UserCard(
            user_id=sample_user_db.telegram_id,
            template_id=sample_card_template_db.id,
            display_id=display_id,
        )
        db_session.add(user_card)
        await db_session.commit()
        await db_session.refresh(sample_user_db)
        
        assert len(sample_user_db.cards) == 1
        assert sample_user_db.cards[0].display_id == display_id


@pytest.mark.unit
class TestCardTemplate:
    """Test CardTemplate model."""

    def test_card_template_creation(self):
        """Test creating a card template."""
        template = CardTemplate(
            id=uuid4(),
            name="Test Card",
            rarity=Rarity.COMMON,
            biome_affinity=BiomeType.NORMAL,
            stats={"atk": 50, "def": 50, "meme": 10},
        )
        assert template.name == "Test Card"
        assert template.rarity == Rarity.COMMON
        assert template.biome_affinity == BiomeType.NORMAL
        assert template.stats["atk"] == 50
        # Soft-delete defaults
        assert template.is_deleted is False
        assert template.deleted_at is None
        assert template.deleted_by is None

    def test_card_template_with_attacks(self):
        """Test card template with attacks."""
        template = CardTemplate(
            id=uuid4(),
            name="Test Card",
            rarity=Rarity.COMMON,
            biome_affinity=BiomeType.NORMAL,
            stats={"atk": 50, "def": 50, "meme": 10},
            attacks=[{
                "name": "Fire Attack",
                "type": AttackType.FIRE.value,
                "damage": 30,
                "energy_cost": 1,
                "effect": "",
                "status_effect": StatusEffect.NONE.value,
            }],
        )
        assert len(template.attacks) == 1
        assert template.attacks[0]["name"] == "Fire Attack"

    def test_card_template_with_weakness(self):
        """Test card template with weakness."""
        template = CardTemplate(
            id=uuid4(),
            name="Test Card",
            rarity=Rarity.COMMON,
            biome_affinity=BiomeType.NORMAL,
            stats={"atk": 50, "def": 50, "meme": 10},
            weakness={"type": AttackType.WATER.value, "multiplier": 2.0},
        )
        assert template.weakness["type"] == AttackType.WATER.value
        assert template.weakness["multiplier"] == 2.0


@pytest.mark.unit
class TestUserCard:
    """Test UserCard model."""

    @pytest.mark.asyncio
    async def test_user_card_creation(self, db_session, sample_user_db, sample_card_template_db):
        """Test creating a user card."""
        from utils.card_ids import generate_unique_display_id
        
        display_id = await generate_unique_display_id(db_session)
        user_card = UserCard(
            user_id=sample_user_db.telegram_id,
            template_id=sample_card_template_db.id,
            display_id=display_id,
        )
        db_session.add(user_card)
        await db_session.commit()
        
        assert user_card.user_id == sample_user_db.telegram_id
        assert user_card.template_id == sample_card_template_db.id
        assert user_card.display_id == display_id

    @pytest.mark.asyncio
    async def test_user_card_acquired_at(self, db_session, sample_user_db, sample_card_template_db):
        """Test that acquired_at is set automatically."""
        from utils.card_ids import generate_unique_display_id
        
        display_id = await generate_unique_display_id(db_session)
        user_card = UserCard(
            user_id=sample_user_db.telegram_id,
            template_id=sample_card_template_db.id,
            display_id=display_id,
        )
        db_session.add(user_card)
        await db_session.commit()
        await db_session.refresh(user_card)
        
        assert user_card.acquired_at is not None
        assert isinstance(user_card.acquired_at, datetime)

    @pytest.mark.asyncio
    async def test_user_card_unique_display_id(self, db_session, sample_user_db, sample_card_template_db):
        """Test that display_id must be unique."""
        from utils.card_ids import generate_unique_display_id
        
        display_id = await generate_unique_display_id(db_session)
        user_card1 = UserCard(
            user_id=sample_user_db.telegram_id,
            template_id=sample_card_template_db.id,
            display_id=display_id,
        )
        db_session.add(user_card1)
        await db_session.commit()
        
        # Try to create another card with same display_id
        user_card2 = UserCard(
            user_id=sample_user_db.telegram_id,
            template_id=sample_card_template_db.id,
            display_id=display_id,
        )
        db_session.add(user_card2)
        
        with pytest.raises(Exception):  # Should raise integrity error
            await db_session.commit()

    @pytest.mark.asyncio
    async def test_delete_user_card_by_display_id(self, db_session, sample_user_db, sample_card_template_db):
        """Test deleting a user card identified by display_id."""
        from sqlalchemy import select
        from utils.card_ids import generate_unique_display_id

        display_id = await generate_unique_display_id(db_session)
        user_card = UserCard(
            user_id=sample_user_db.telegram_id,
            template_id=sample_card_template_db.id,
            display_id=display_id,
        )
        db_session.add(user_card)
        await db_session.commit()

        stmt = select(UserCard).where(UserCard.display_id == display_id)
        result = await db_session.execute(stmt)
        found = result.scalar_one_or_none()
        assert found is not None

        await db_session.delete(found)
        await db_session.commit()

        result2 = await db_session.execute(stmt)
        assert result2.scalar_one_or_none() is None


@pytest.mark.unit
class TestGroupChat:
    """Test GroupChat model."""

    def test_group_chat_creation(self):
        """Test creating a group chat."""
        chat = GroupChat(
            chat_id=-12345,
            title="Test Group",
            is_active=True,
        )
        assert chat.chat_id == -12345
        assert chat.title == "Test Group"
        assert chat.is_active is True

    def test_group_chat_default_active(self):
        """Test group chat default is_active."""
        chat = GroupChat(chat_id=-12345)
        assert chat.is_active is True


class TestModelRelationships:
    """Test relationships between models."""

    @pytest.mark.asyncio
    async def test_card_template_user_cards_relationship(self, db_session, sample_card_template_db, sample_user_db):
        """Test relationship between CardTemplate and UserCard."""
        from utils.card_ids import generate_unique_display_id
        
        display_id = await generate_unique_display_id(db_session)
        user_card = UserCard(
            user_id=sample_user_db.telegram_id,
            template_id=sample_card_template_db.id,
            display_id=display_id,
        )
        db_session.add(user_card)
        await db_session.commit()
        await db_session.refresh(sample_card_template_db)
        
        assert len(sample_card_template_db.user_cards) == 1
        assert sample_card_template_db.user_cards[0].display_id == display_id

    async def test_cascade_delete_user(self, db_session, sample_user_db, sample_card_template_db):
        """Test that deleting user deletes user cards."""
        from utils.card_ids import generate_unique_display_id
        
        display_id = await generate_unique_display_id(db_session)
        user_card = UserCard(
            user_id=sample_user_db.telegram_id,
            template_id=sample_card_template_db.id,
            display_id=display_id,
        )
        db_session.add(user_card)
        await db_session.commit()
        
        # Delete user
        await db_session.delete(sample_user_db)
        await db_session.commit()
        
        # Check that user card is also deleted
        from sqlalchemy import select
        stmt = select(UserCard).where(UserCard.display_id == display_id)
        result = await db_session.execute(stmt)
        assert result.scalar_one_or_none() is None
