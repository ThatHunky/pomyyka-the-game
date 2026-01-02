"""Shared test fixtures and configuration."""

import asyncio
import random
from typing import AsyncGenerator
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import Chat, User as TelegramUser
from faker import Faker
from fakeredis import aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database.enums import AttackType, BiomeType, Rarity, StatusEffect
from database.models import Base, CardTemplate, GroupChat, User, UserCard
from services.redis_lock import DropManager

# Seed random for deterministic tests
random.seed(42)
fake = Faker()
Faker.seed(42)


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def db_engine():
    """Create in-memory SQLite database for testing."""
    try:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )

    except (ImportError, ModuleNotFoundError):
        pytest.skip("aiosqlite not installed")

    # Ensure app-level `database.session.get_session()` uses this test engine.
    import database.session as session_module

    old_engine = session_module.engine
    old_session_maker = session_module.async_session_maker
    session_module.engine = engine
    session_module.async_session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        async with engine.begin() as conn:
            # Enable FK constraints so ON DELETE CASCADE works in SQLite tests.
            await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            await conn.run_sync(Base.metadata.create_all)

        yield engine
    finally:
        session_module.engine = old_engine
        session_module.async_session_maker = old_session_maker
        await engine.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create database session for testing."""
    async_session_maker = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    async with async_session_maker() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def redis_client():
    """Create fake Redis client for testing."""
    redis = await aioredis.FakeRedis(decode_responses=True)
    yield redis
    await redis.flushall()
    await redis.close()


@pytest.fixture
async def drop_manager(redis_client):
    """Create DropManager instance with fake Redis."""
    manager = DropManager(redis_client=redis_client, default_ttl=300)
    yield manager
    await manager.close()


@pytest.fixture
def mock_bot():
    """Create mock Bot instance."""
    session = AiohttpSession()
    bot = Bot(token="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11", session=session)
    return bot


@pytest.fixture
def mock_dispatcher():
    """Create mock Dispatcher instance."""
    return Dispatcher()


@pytest.fixture
def telegram_user() -> TelegramUser:
    """Create a mock Telegram user."""
    return TelegramUser(
        id=fake.random_int(min=100000, max=999999),
        is_bot=False,
        first_name=fake.first_name(),
        username=fake.user_name(),
    )


@pytest.fixture
def telegram_chat() -> Chat:
    """Create a mock Telegram chat."""
    return Chat(
        id=fake.random_int(min=-1000000000, max=-100000),
        type="group",
        title=fake.company(),
    )


@pytest.fixture
def sample_user(db_session) -> User:
    """Create a sample user in database."""
    user = User(
        telegram_id=fake.random_int(min=100000, max=999999),
        username=fake.user_name(),
        balance=1000,
    )
    return user


@pytest.fixture
async def sample_user_db(db_session) -> User:
    """Create and persist a sample user in database."""
    user = User(
        telegram_id=fake.random_int(min=100000, max=999999),
        username=fake.user_name(),
        balance=1000,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def sample_card_template() -> CardTemplate:
    """Create a sample card template."""
    return CardTemplate(
        id=uuid4(),
        name=fake.word().capitalize(),
        image_url=fake.image_url(),
        rarity=Rarity.COMMON,
        biome_affinity=BiomeType.NORMAL,
        stats={"atk": 50, "def": 50, "meme": 10},
        attacks=[
            {
                "name": "Базова атака",
                "type": AttackType.PHYSICAL,
                "damage": 30,
                "energy_cost": 1,
                "effect": "",
                "status_effect": StatusEffect.NONE,
            }
        ],
        weakness=None,
        resistance=None,
        print_date="01/2025",
    )


@pytest.fixture
async def sample_card_template_db(db_session, sample_user_db) -> CardTemplate:
    """Create and persist a sample card template in database."""
    template = CardTemplate(
        id=uuid4(),
        name=fake.word().capitalize(),
        image_url=fake.image_url(),
        rarity=Rarity.COMMON,
        biome_affinity=BiomeType.NORMAL,
        stats={"atk": 50, "def": 50, "meme": 10},
        attacks=[
            {
                "name": "Базова атака",
                "type": AttackType.PHYSICAL.value,
                "damage": 30,
                "energy_cost": 1,
                "effect": "",
                "status_effect": StatusEffect.NONE.value,
            }
        ],
        weakness=None,
        resistance=None,
        print_date="01/2025",
    )
    db_session.add(template)
    await db_session.commit()
    await db_session.refresh(template)
    return template


@pytest.fixture
async def sample_user_card(db_session, sample_user_db, sample_card_template_db) -> UserCard:
    """Create and persist a sample user card in database."""
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
    return user_card


@pytest.fixture
def sample_group_chat() -> GroupChat:
    """Create a sample group chat."""
    return GroupChat(
        chat_id=fake.random_int(min=-1000000000, max=-100000),
        title=fake.company(),
        is_active=True,
    )


@pytest.fixture
async def sample_group_chat_db(db_session) -> GroupChat:
    """Create and persist a sample group chat in database."""
    group = GroupChat(
        chat_id=fake.random_int(min=-1000000000, max=-100000),
        title=fake.company(),
        is_active=True,
    )
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)
    return group


@pytest.fixture
def epic_card_template() -> CardTemplate:
    """Create an epic rarity card template."""
    return CardTemplate(
        id=uuid4(),
        name="Epic Card",
        image_url=fake.image_url(),
        rarity=Rarity.EPIC,
        biome_affinity=BiomeType.FIRE,
        stats={"atk": 100, "def": 80, "meme": 30},
        attacks=[
            {
                "name": "Вогняна атака",
                "type": AttackType.FIRE.value,
                "damage": 80,
                "energy_cost": 2,
                "effect": "Завдає опік",
                "status_effect": StatusEffect.BURNED.value,
            }
        ],
        weakness={"type": AttackType.WATER.value, "multiplier": 2.0},
        resistance={"type": AttackType.GRASS.value, "reduction": 20},
        print_date="01/2025",
    )


@pytest.fixture
def legendary_card_template() -> CardTemplate:
    """Create a legendary rarity card template."""
    return CardTemplate(
        id=uuid4(),
        name="Legendary Card",
        image_url=fake.image_url(),
        rarity=Rarity.LEGENDARY,
        biome_affinity=BiomeType.PSYCHIC,
        stats={"atk": 150, "def": 120, "meme": 50},
        attacks=[
            {
                "name": "Психічна атака",
                "type": AttackType.PSYCHIC.value,
                "damage": 120,
                "energy_cost": 3,
                "effect": "Завдає плутанину",
                "status_effect": StatusEffect.CONFUSED.value,
            }
        ],
        weakness={"type": AttackType.DARK.value, "multiplier": 2.0},
        resistance=None,
        print_date="01/2025",
    )


@pytest.fixture
def mock_message(telegram_user, telegram_chat):
    """Create a mutable mock Telegram message (aiogram models are frozen)."""
    return SimpleNamespace(
        message_id=fake.random_int(min=1, max=1000000),
        date=fake.date_time(),
        chat=telegram_chat,
        from_user=SimpleNamespace(
            id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            last_name=getattr(telegram_user, "last_name", None),
        ),
        text="/test",
    )


@pytest.fixture
def mock_callback_query(telegram_user, telegram_chat, mock_message):
    """Create a mock callback query."""
    return SimpleNamespace(
        id=str(fake.uuid4()),
        from_user=SimpleNamespace(
            id=telegram_user.id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            last_name=getattr(telegram_user, "last_name", None),
        ),
        chat_instance=str(fake.random_int()),
        message=mock_message,
        data="test_callback",
    )


# Cleanup fixtures
@pytest.fixture(autouse=True)
async def cleanup_db(db_session):
    """Auto-cleanup database after each test."""
    yield
    # Rollback any uncommitted changes
    await db_session.rollback()
    # Delete all test data
    # Order matters when FK constraints are enabled.
    await db_session.execute(text("DELETE FROM message_logs"))
    await db_session.execute(text("DELETE FROM user_cards"))
    await db_session.execute(text("DELETE FROM card_templates"))
    await db_session.execute(text("DELETE FROM group_chats"))
    await db_session.execute(text("DELETE FROM users"))
    await db_session.commit()


@pytest.fixture(autouse=True)
async def cleanup_redis(redis_client):
    """Auto-cleanup Redis after each test."""
    yield
    await redis_client.flushall()
