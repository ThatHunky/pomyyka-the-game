from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from database.enums import AttackType, BiomeType, Rarity, StatusEffect

# NOTE:
# - Production uses PostgreSQL (JSONB)
# - Tests use SQLite in-memory (no JSONB type compiler)
# So we use a cross-dialect JSON type that maps to JSONB on Postgres and JSON on SQLite.
JSONB_COMPAT = JSONB().with_variant(JSON, "sqlite")


class _TelegramId(int):
    """`int` subclass that also exposes `.telegram_id` (for some core-level tests)."""

    @property
    def telegram_id(self) -> int:
        return int(self)


class TelegramIdType(TypeDecorator):
    """BigInteger that round-trips as `_TelegramId` on result rows."""

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        return int(value)

    def process_result_value(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        return _TelegramId(value)


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class User(Base):
    """Telegram user model."""

    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(TelegramIdType(), primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # NOTE: SQLAlchemy column defaults are applied at INSERT time; tests expect
    # Python-side defaults on instance creation, so we also set it in __init__.
    balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    cards: Mapped[list["UserCard"]] = relationship(
        "UserCard",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(**kwargs)
        if self.balance is None:
            self.balance = 0


class GroupChat(Base):
    """Telegram group chat model."""

    __tablename__ = "group_chats"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Same as User.balance: tests expect the default on instance creation.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(**kwargs)
        if self.is_active is None:
            self.is_active = True


class CardTemplate(Base):
    """Card template/model definition."""

    __tablename__ = "card_templates"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    rarity: Mapped[Rarity] = mapped_column(
        SQLEnum(Rarity, native_enum=False), nullable=False
    )
    biome_affinity: Mapped[BiomeType] = mapped_column(
        SQLEnum(BiomeType, native_enum=False), nullable=False
    )
    stats: Mapped[dict] = mapped_column(
        JSONB_COMPAT, nullable=False
    )  # JSONB: {"atk": int, "def": int, "meme": int}
    attacks: Mapped[list[dict] | None] = mapped_column(
        JSONB_COMPAT, nullable=True
    )  # JSONB: List of attack objects, e.g. [{"name": str, "type": AttackType, "damage": int, "energy_cost": int, "effect": str, "status_effect": StatusEffect}]
    weakness: Mapped[dict | None] = mapped_column(
        JSONB_COMPAT, nullable=True
    )  # JSONB: {"type": AttackType, "multiplier": float} - e.g. {"type": "FIRE", "multiplier": 2.0} means 2x damage from Fire
    resistance: Mapped[dict | None] = mapped_column(
        JSONB_COMPAT, nullable=True
    )  # JSONB: {"type": AttackType, "reduction": int} - e.g. {"type": "WATER", "reduction": 20} means -20 damage from Water
    print_date: Mapped[str | None] = mapped_column(
        String(7), nullable=True
    )  # Format: "MM/YYYY" e.g. "01/2025" - like Pokemon TCG cards

    # Soft-delete support (so admins can remove/restore templates without breaking inventories)
    # NOTE: Column defaults are applied at INSERT time; some tests expect Python-side defaults.
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    user_cards: Mapped[list["UserCard"]] = relationship(
        "UserCard",
        back_populates="template",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(**kwargs)
        if self.is_deleted is None:
            self.is_deleted = False


class UserCard(Base):
    """User-owned card instance."""

    __tablename__ = "user_cards"
    __table_args__ = (
        UniqueConstraint("display_id", name="uq_user_cards_display_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("card_templates.id", ondelete="CASCADE"),
        nullable=False,
    )
    display_id: Mapped[str] = mapped_column(
        String(10), nullable=False, unique=True, index=True
    )  # Short human-readable unique ID (e.g., "POM-A1B2")
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=lambda: datetime.now(timezone.utc)
    )
    unique_stats: Mapped[dict | None] = mapped_column(
        JSONB_COMPAT, nullable=True
    )  # JSONB: optional per-instance stat modifications

    user: Mapped["User"] = relationship("User", back_populates="cards")
    template: Mapped["CardTemplate"] = relationship("CardTemplate", back_populates="user_cards")


class MessageLog(Base):
    """Message log for storing chat messages."""

    __tablename__ = "message_logs"
    __table_args__ = (
        Index("ix_message_logs_user_id", "user_id"),
        Index("ix_message_logs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False
    )
    chat_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("group_chats.chat_id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
