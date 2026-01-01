from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, Enum as SQLEnum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from database.enums import BiomeType, Rarity


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class User(Base):
    """Telegram user model."""

    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    balance: Mapped[int] = mapped_column(BigInteger, default=0)

    cards: Mapped[list["UserCard"]] = relationship(
        "UserCard", back_populates="user", cascade="all, delete-orphan"
    )


class GroupChat(Base):
    """Telegram group chat model."""

    __tablename__ = "group_chats"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


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
        JSONB, nullable=False
    )  # JSONB: {"atk": int, "def": int}

    user_cards: Mapped[list["UserCard"]] = relationship(
        "UserCard", back_populates="template", cascade="all, delete-orphan"
    )


class UserCard(Base):
    """User-owned card instance."""

    __tablename__ = "user_cards"

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
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=lambda: datetime.now(timezone.utc)
    )
    unique_stats: Mapped[dict] = mapped_column(
        JSONB, nullable=True
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
