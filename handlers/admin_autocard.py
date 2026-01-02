"""Admin handler for automatic card generation from user messages."""

from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaAnimation,
    InputMediaPhoto,
    Message,
)
from sqlalchemy import desc, distinct, func, select
from sqlalchemy.dialects.postgresql import insert

from config import settings
from database.enums import AttackType, BiomeType, Rarity, StatusEffect
from database.models import CardTemplate, MessageLog, User, UserCard
from database.session import get_session
from handlers.admin import check_admin
from logging_config import get_logger
from services.nano_banana import NanoBananaService
from services.session_manager import SessionManager
from utils.animations import send_card_animation
from utils.card_ids import generate_unique_display_id
from utils.text import escape_markdown
from utils.telegram_utils import safe_callback_answer

logger = get_logger(__name__)

router = Router(name="admin_autocard")

# Session manager for storing blueprint data
session_manager = SessionManager()


class CardEditStates(StatesGroup):
    """FSM states for card field editing."""
    waiting_for_value = State()


class AutocardCallback(CallbackData, prefix="autocard"):
    """Callback data for autocard approval/cancellation/regeneration/editing."""

    action: str  # "approve", "cancel", "regenerate", or "edit"
    blueprint_id: str  # UUID string for Redis-stored blueprint data


class AutocardEditCallback(CallbackData, prefix="aced"):
    """
    Callback data for the inline edit UI (short prefix to avoid Telegram limits).

    action codes:
    - m: show edit menu
    - b: back to main actions
    - bm: biome select menu
    - rm: rarity select menu
    - am: attacks menu
    - a: ask for typed value (field in `field`)
    - s: set choice value (field in `field`, value in `value`)
    - ci: cancel pending input (clears FSM, restores edit menu)
    """

    action: str
    blueprint_id: str
    field: str = ""
    value: str = ""


class AutocardAttackCallback(CallbackData, prefix="acat"):
    """
    Callback data for attack editing (short prefix to avoid Telegram limits).

    action codes:
    - m: show attacks menu
    - b: back to edit menu
    - x: select attack (idx)
    - p: add attack
    - d: delete attack (idx)
    - t: show attack type menu (idx)
    - u: show status effect menu (idx)
    - a: ask for typed value (field code in `field`)
    - s: set choice value (field code in `field`, value in `value`)
    """

    action: str
    blueprint_id: str
    idx: int
    field: str = ""
    value: str = ""


def get_biome_emoji(biome: BiomeType) -> str:
    """Get emoji for biome type."""
    emoji_map = {
        BiomeType.NORMAL: "🌍",
        BiomeType.FIRE: "🔥",
        BiomeType.WATER: "💧",
        BiomeType.GRASS: "🌿",
        BiomeType.PSYCHIC: "🔮",
        BiomeType.TECHNO: "⚙️",
        BiomeType.DARK: "🌑",
    }
    return emoji_map.get(biome, "🌍")


def get_rarity_emoji(rarity: Rarity) -> str:
    """Get emoji for rarity."""
    emoji_map = {
        Rarity.COMMON: "⚪",
        Rarity.RARE: "🔵",
        Rarity.EPIC: "🟣",
        Rarity.LEGENDARY: "🟠",
        Rarity.MYTHIC: "🔴",
    }
    return emoji_map.get(rarity, "⚪")


def build_autocard_main_keyboard(blueprint_id: str) -> InlineKeyboardMarkup:
    """Main preview actions keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Перегенерувати Зображення",
                    callback_data=AutocardCallback(
                        action="regenerate", blueprint_id=blueprint_id
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Редагувати Поля",
                    callback_data=AutocardCallback(
                        action="edit", blueprint_id=blueprint_id
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Затвердити та Видати",
                    callback_data=AutocardCallback(
                        action="approve", blueprint_id=blueprint_id
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Скасувати",
                    callback_data=AutocardCallback(
                        action="cancel", blueprint_id=blueprint_id
                    ).pack(),
                )
            ],
        ]
    )


def build_autocard_edit_keyboard(blueprint_id: str) -> InlineKeyboardMarkup:
    """Edit menu keyboard (field-by-field, no JSON)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📛 Назва",
                    callback_data=AutocardEditCallback(
                        action="a", blueprint_id=blueprint_id, field="name"
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🌍 Біом",
                    callback_data=AutocardEditCallback(
                        action="bm", blueprint_id=blueprint_id
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="💎 Рідкість",
                    callback_data=AutocardEditCallback(
                        action="rm", blueprint_id=blueprint_id
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⚔️ ATK",
                    callback_data=AutocardEditCallback(
                        action="a", blueprint_id=blueprint_id, field="atk"
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="🛡️ DEF",
                    callback_data=AutocardEditCallback(
                        action="a", blueprint_id=blueprint_id, field="def"
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="🎭 MEME",
                    callback_data=AutocardEditCallback(
                        action="a", blueprint_id=blueprint_id, field="meme"
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📖 Лор",
                    callback_data=AutocardEditCallback(
                        action="a", blueprint_id=blueprint_id, field="lore"
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚡ Атаки",
                    callback_data=AutocardEditCallback(
                        action="am", blueprint_id=blueprint_id
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🖼 Prompt",
                    callback_data=AutocardEditCallback(
                        action="a",
                        blueprint_id=blueprint_id,
                        field="raw_image_prompt_en",
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗓 Дата (MM/YYYY)",
                    callback_data=AutocardEditCallback(
                        action="a", blueprint_id=blueprint_id, field="print_date"
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=AutocardEditCallback(
                        action="b", blueprint_id=blueprint_id
                    ).pack(),
                )
            ],
        ]
    )


def build_autocard_input_keyboard(blueprint_id: str) -> InlineKeyboardMarkup:
    """Keyboard shown while waiting for typed input."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Скасувати введення",
                    callback_data=AutocardEditCallback(
                        action="ci", blueprint_id=blueprint_id
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ До меню редагування",
                    callback_data=AutocardEditCallback(
                        action="m", blueprint_id=blueprint_id
                    ).pack(),
                )
            ],
        ]
    )


def build_autocard_biome_keyboard(blueprint_id: str) -> InlineKeyboardMarkup:
    """Biome selection keyboard."""
    rows: list[list[InlineKeyboardButton]] = []
    for biome in BiomeType:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{get_biome_emoji(biome)} {biome.value}",
                    callback_data=AutocardEditCallback(
                        action="s", blueprint_id=blueprint_id, field="biome", value=biome.name
                    ).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=AutocardEditCallback(action="m", blueprint_id=blueprint_id).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_autocard_rarity_keyboard(blueprint_id: str) -> InlineKeyboardMarkup:
    """Rarity selection keyboard."""
    rows: list[list[InlineKeyboardButton]] = []
    for rarity in Rarity:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{get_rarity_emoji(rarity)} {rarity.value.upper()}",
                    callback_data=AutocardEditCallback(
                        action="s", blueprint_id=blueprint_id, field="rarity", value=rarity.name
                    ).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=AutocardEditCallback(action="m", blueprint_id=blueprint_id).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_autocard_attacks_keyboard(blueprint_id: str, attacks: list[dict] | None) -> InlineKeyboardMarkup:
    """Attacks menu keyboard."""
    attacks = attacks or []
    rows: list[list[InlineKeyboardButton]] = []

    if attacks:
        for i, atk in enumerate(attacks[:2]):
            name = str(atk.get("name", f"Атака {i+1}")).strip() or f"Атака {i+1}"
            if len(name) > 20:
                name = name[:17] + "..."
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{i+1}️⃣ {name}",
                        callback_data=AutocardAttackCallback(
                            action="x", blueprint_id=blueprint_id, idx=i
                        ).pack(),
                    )
                ]
            )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="(Немає атак) ➕ Додати",
                    callback_data=AutocardAttackCallback(
                        action="p", blueprint_id=blueprint_id, idx=0
                    ).pack(),
                )
            ]
        )

    if len(attacks) < 2:
        rows.append(
            [
                InlineKeyboardButton(
                    text="➕ Додати атаку",
                    callback_data=AutocardAttackCallback(
                        action="p", blueprint_id=blueprint_id, idx=0
                    ).pack(),
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=AutocardEditCallback(action="m", blueprint_id=blueprint_id).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_autocard_attack_fields_keyboard(blueprint_id: str, idx: int) -> InlineKeyboardMarkup:
    """Attack field edit keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📛 Назва",
                    callback_data=AutocardAttackCallback(
                        action="a", blueprint_id=blueprint_id, idx=idx, field="n"
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="🎨 Тип",
                    callback_data=AutocardAttackCallback(
                        action="t", blueprint_id=blueprint_id, idx=idx
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💥 Урон",
                    callback_data=AutocardAttackCallback(
                        action="a", blueprint_id=blueprint_id, idx=idx, field="d"
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="⚡ Вартість",
                    callback_data=AutocardAttackCallback(
                        action="a", blueprint_id=blueprint_id, idx=idx, field="e"
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✨ Ефект",
                    callback_data=AutocardAttackCallback(
                        action="a", blueprint_id=blueprint_id, idx=idx, field="f"
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="🌀 Статус",
                    callback_data=AutocardAttackCallback(
                        action="u", blueprint_id=blueprint_id, idx=idx
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Видалити атаку",
                    callback_data=AutocardAttackCallback(
                        action="d", blueprint_id=blueprint_id, idx=idx
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ До атак",
                    callback_data=AutocardAttackCallback(
                        action="m", blueprint_id=blueprint_id, idx=0
                    ).pack(),
                )
            ],
        ]
    )


def build_autocard_attack_type_keyboard(blueprint_id: str, idx: int) -> InlineKeyboardMarkup:
    """Attack type selection keyboard."""
    rows: list[list[InlineKeyboardButton]] = []
    for t in AttackType:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t.value,
                    callback_data=AutocardAttackCallback(
                        action="s", blueprint_id=blueprint_id, idx=idx, field="t", value=t.name
                    ).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=AutocardAttackCallback(
                    action="x", blueprint_id=blueprint_id, idx=idx
                ).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_autocard_attack_status_keyboard(blueprint_id: str, idx: int) -> InlineKeyboardMarkup:
    """Status effect selection keyboard."""
    rows: list[list[InlineKeyboardButton]] = []
    for s in StatusEffect:
        rows.append(
            [
                InlineKeyboardButton(
                    text=s.value,
                    callback_data=AutocardAttackCallback(
                        action="s", blueprint_id=blueprint_id, idx=idx, field="s", value=s.name
                    ).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=AutocardAttackCallback(
                    action="x", blueprint_id=blueprint_id, idx=idx
                ).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_caption_from_blueprint_data(blueprint_data: dict, extra: str | None = None) -> str:
    """Build preview caption (safe-ish for Markdown)."""
    name = escape_markdown(str(blueprint_data.get("name", "")))
    biome_val = str(blueprint_data.get("biome", ""))
    rarity_val = str(blueprint_data.get("rarity", ""))
    atk = blueprint_data.get("atk", 0)
    defense = blueprint_data.get("def", 0)
    meme = blueprint_data.get("meme", 0)
    lore = escape_markdown(str(blueprint_data.get("lore", "")))

    try:
        biome_enum = BiomeType(biome_val)
        biome_emoji = get_biome_emoji(biome_enum)
    except Exception:
        biome_emoji = "🌍"

    caption = (
        f"**{name}**\n\n"
        f"{biome_emoji} **Біом:** {escape_markdown(biome_val)}\n"
        f"⚔️ **АТАКА:** {atk}\n"
        f"🛡️ **ЗАХИСТ:** {defense}\n"
        f"🎭 **МЕМНІСТЬ:** {meme}\n"
        f"💎 **Рідкість:** {escape_markdown(rarity_val)}\n\n"
        f"📖 **Лор:** {lore}"
    )

    if extra:
        caption = f"{caption}\n\n{extra}"
    return caption


def _pick_preview_media_path(image_url: str, rarity_value: str) -> tuple[Path, bool]:
    """Pick the best media file for preview (animation for rare, else static)."""
    image_path = Path(image_url)
    try:
        rarity = Rarity(rarity_value)
    except Exception:
        rarity = None

    is_rare = rarity in (Rarity.EPIC, Rarity.LEGENDARY, Rarity.MYTHIC)
    if is_rare:
        animated_mp4_path = image_path.parent / f"{image_path.stem}_animated.mp4"
        animated_gif_path = image_path.parent / f"{image_path.stem}_animated.gif"
        if animated_mp4_path.exists():
            return animated_mp4_path, True
        if animated_gif_path.exists():
            return animated_gif_path, True

    return image_path, False


async def _edit_preview_media(
    bot: Bot,
    chat_id: int,
    message_id: int,
    blueprint_data: dict,
    blueprint_id: str,
    *,
    reply_markup: InlineKeyboardMarkup,
    caption_extra: str | None = None,
) -> None:
    """Edit the existing preview message in-place (media + caption + keyboard)."""
    caption = _format_caption_from_blueprint_data(blueprint_data, extra=caption_extra)

    image_url = str(blueprint_data.get("image_url") or "")
    if image_url:
        media_path, is_animation = _pick_preview_media_path(image_url, str(blueprint_data.get("rarity", "")))
        if media_path.exists():
            media_file = FSInputFile(str(media_path))
            if is_animation:
                media = InputMediaAnimation(
                    media=media_file,
                    caption=caption,
                    parse_mode="Markdown",
                )
            else:
                media = InputMediaPhoto(
                    media=media_file,
                    caption=caption,
                    parse_mode="Markdown",
                )

            try:
                await bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=message_id,
                    media=media,
                    reply_markup=reply_markup,
                )
                return
            except Exception as e:
                logger.warning(
                    "Failed to edit preview media, falling back to caption only",
                    chat_id=chat_id,
                    message_id=message_id,
                    error=str(e),
                )

    # Fallback: just update caption/text + keyboard
    try:
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
    except Exception:
        # Last resort: try editing as text message
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=caption,
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )


async def resolve_target_user(
    message: Message, bot: Bot, arg: str | None = None
) -> tuple[int, str] | None:
    """
    Resolve target user from command argument or reply.
    
    Args:
        message: The command message.
        bot: Bot instance for Telegram API calls.
        arg: Command argument (username or userID).
    
    Returns:
        Tuple of (user_id, user_display_name) or None if not found.
    """
    # If argument provided, parse it
    if arg:
        arg = arg.strip()
        
        # Check if it's a username (starts with @)
        if arg.startswith("@"):
            username = arg[1:].strip().lower()  # Normalize to lowercase
            if not username:
                return None
            
            # Try to find in database first (case-insensitive)
            async for session in get_session():
                try:
                    # Use func.lower for case-insensitive search (PostgreSQL)
                    stmt = select(User).where(func.lower(User.username) == username)
                    result = await session.execute(stmt)
                    # Use first() instead of scalar_one_or_none() to handle duplicates
                    db_user = result.first()
                    
                    if db_user:
                        db_user = db_user[0]  # Unpack from Row tuple
                        user_display = f"@{db_user.username}" if db_user.username else f"ID: {db_user.telegram_id}"
                        return (db_user.telegram_id, user_display)
                except Exception as e:
                    logger.error(
                        "Error querying user by username",
                        username=username,
                        error=str(e),
                        exc_info=True,
                    )
                break
            
            # If not found by exact username, try to find user by searching message logs
            # Some users might have messages but no username stored
            async for session in get_session():
                try:
                    # Find user_id from message logs where content mentions this username
                    # This helps when username wasn't stored during import
                    stmt = (
                        select(distinct(MessageLog.user_id))
                        .where(
                            func.lower(MessageLog.content).like(f"%@{username}%")
                        )
                        .limit(5)  # Get a few candidates
                    )
                    result = await session.execute(stmt)
                    candidate_user_ids = [row[0] for row in result.all()]
                    
                    # If we found candidates, use the first one (most likely match)
                    # Even if username doesn't match exactly, if they mentioned this username,
                    # they're likely the user we're looking for
                    if candidate_user_ids:
                        # Try to find exact username match first
                        for candidate_id in candidate_user_ids:
                            user_stmt = select(User).where(User.telegram_id == candidate_id)
                            user_result = await session.execute(user_stmt)
                            candidate_user = user_result.scalar_one_or_none()
                            
                            if candidate_user:
                                # Check if username matches (case-insensitive)
                                if candidate_user.username and candidate_user.username.lower() == username:
                                    user_display = f"@{candidate_user.username}"
                                    logger.info(
                                        "Found user by message content search (exact username match)",
                                        username=username,
                                        user_id=candidate_id,
                                    )
                                    return (candidate_id, user_display)
                        
                        # If no exact match, use the first candidate (user who mentioned this username)
                        # This handles cases where username wasn't stored during import
                        first_candidate_id = candidate_user_ids[0]
                        user_stmt = select(User).where(User.telegram_id == first_candidate_id)
                        user_result = await session.execute(user_stmt)
                        candidate_user = user_result.scalar_one_or_none()
                        
                        # If user has messages but doesn't exist in User table, create them
                        if not candidate_user:
                            try:
                                stmt = insert(User).values(
                                    telegram_id=first_candidate_id,
                                    username=username,  # Store the username we're looking for
                                    balance=0,
                                )
                                stmt = stmt.on_conflict_do_update(
                                    index_elements=["telegram_id"],
                                    set_={"username": stmt.excluded.username},
                                    where=User.username.is_(None)
                                )
                                await session.execute(stmt)
                                await session.commit()
                                
                                # Re-fetch the user
                                user_result = await session.execute(user_stmt)
                                candidate_user = user_result.scalar_one_or_none()
                            except Exception as e:
                                logger.warning(
                                    "Error creating user from message logs",
                                    user_id=first_candidate_id,
                                    error=str(e),
                                )
                        
                        if candidate_user:
                            user_display = f"@{username}" if username else f"ID: {first_candidate_id}"
                            logger.info(
                                "Found user by message content search (best match)",
                                username=username,
                                user_id=first_candidate_id,
                                stored_username=candidate_user.username,
                            )
                            return (first_candidate_id, user_display)
                except Exception as e:
                    logger.warning(
                        "Error searching users by message content",
                        username=username,
                        error=str(e),
                    )
                break
            
            # If not in DB, try Telegram API as last resort
            try:
                chat = await bot.get_chat(f"@{username}")
                if chat and chat.id:
                    user_display = f"@{username}"
                    # Create user in DB if found via API
                    async for session in get_session():
                        try:
                            stmt = insert(User).values(
                                telegram_id=chat.id,
                                username=username,
                                balance=0,
                            )
                            stmt = stmt.on_conflict_do_nothing(index_elements=["telegram_id"])
                            await session.execute(stmt)
                            await session.commit()
                        except Exception:
                            pass
                        break
                    return (chat.id, user_display)
            except Exception as e:
                logger.warning(
                    "Could not resolve username via Telegram API",
                    username=username,
                    error=str(e),
                )
                return None
        
        # Check if it's a numeric userID
        elif arg.isdigit():
            user_id = int(arg)
            # Try to find in database
            async for session in get_session():
                try:
                    stmt = select(User).where(User.telegram_id == user_id)
                    result = await session.execute(stmt)
                    db_user = result.scalar_one_or_none()
                    
                    if db_user:
                        user_display = f"@{db_user.username}" if db_user.username else f"ID: {user_id}"
                        return (user_id, user_display)
                except Exception as e:
                    logger.error(
                        "Error querying user by ID",
                        user_id=user_id,
                        error=str(e),
                        exc_info=True,
                    )
                break
            
            # If not in DB, try Telegram API
            try:
                chat = await bot.get_chat(user_id)
                if chat:
                    user_display = f"@{chat.username}" if chat.username else f"ID: {user_id}"
                    return (user_id, user_display)
            except Exception as e:
                logger.warning(
                    "Could not resolve userID via Telegram API",
                    user_id=user_id,
                    error=str(e),
                )
                return None
    
    # Fallback to reply-to-message mode
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        
        # Format user name for display
        user_display = target_user.first_name or "Користувач"
        if target_user.last_name:
            user_display += f" {target_user.last_name}"
        elif target_user.username:
            user_display = f"@{target_user.username}"
        
        return (target_user_id, user_display)
    
    return None


@router.message(Command("autocard"))
async def cmd_autocard(message: Message, bot: Bot) -> None:
    """
    Handle /autocard command.
    
    Usage:
    - /autocard (reply to a message)
    - /autocard @username
    - /autocard 392817811
    - /autocard (with photo attached)
    - /autocard (reply to message with photo)
    """
    if not await check_admin(message):
        return

    # Extract photo from command message or replied message
    custom_photo_bytes = None
    custom_description = None
    
    # Helper function to extract photo bytes from a message
    async def extract_photo_bytes(msg: Message) -> bytes | None:
        """Extract photo bytes from a Telegram message."""
        if not msg or not msg.photo:
            return None
        try:
            # Get largest photo size
            largest_photo = msg.photo[-1]
            # Download the file
            photo_file = await bot.get_file(largest_photo.file_id)
            photo_bytes = await bot.download_file(photo_file.file_path)
            return photo_bytes.read()
        except Exception as e:
            logger.warning(
                "Could not extract photo from message",
                message_id=msg.message_id if msg else None,
                error=str(e),
            )
            return None
    
    # Parse command arguments - check both text and caption
    command_text = message.text or message.caption or ""
    arg = None
    
    # Extract photo and description first
    if message.photo:
        custom_photo_bytes = await extract_photo_bytes(message)
        # Parse caption to extract command args and description
        if message.caption:
            caption = message.caption
            # Look for /autocard in the caption (case insensitive)
            caption_lower = caption.lower()
            if "/autocard" in caption_lower:
                # Find the position of /autocard (case insensitive)
                autocard_pos = caption_lower.find("/autocard")
                # Get everything after /autocard
                remaining = caption[autocard_pos + len("/autocard"):].strip()
                if remaining:
                    # Try to parse as command args (username/userID) + description
                    remaining_parts = remaining.split(maxsplit=1)
                    # Check if first part looks like username (@username) or userID (digits)
                    if remaining_parts and (remaining_parts[0].startswith("@") or remaining_parts[0].isdigit()):
                        arg = remaining_parts[0]
                        # Rest is description
                        if len(remaining_parts) > 1:
                            custom_description = remaining_parts[1]
                    else:
                        # Everything is description (no username/userID)
                        custom_description = remaining
            else:
                # No /autocard found, use entire caption as description
                custom_description = caption
    
    # If no caption parsing happened, parse from text
    if not arg and command_text:
        command_args = command_text.split(maxsplit=1)
        arg = command_args[1] if len(command_args) > 1 else None
    
    # Check if replied message has a photo (if no photo in command message)
    if not custom_photo_bytes and message.reply_to_message:
        if message.reply_to_message.photo:
            custom_photo_bytes = await extract_photo_bytes(message.reply_to_message)
            # Extract description from replied message caption or text
            if message.reply_to_message.caption:
                custom_description = message.reply_to_message.caption
            elif message.reply_to_message.text:
                custom_description = message.reply_to_message.text

    # Resolve target user
    resolved = await resolve_target_user(message, bot, arg)
    
    # If no user resolved but we have a photo, use the message sender as target
    if not resolved:
        if custom_photo_bytes and message.from_user:
            # Use message sender as target when photo is provided
            target_user = message.from_user
            target_user_id = target_user.id
            user_display = target_user.first_name or "Користувач"
            if target_user.last_name:
                user_display += f" {target_user.last_name}"
            elif target_user.username:
                user_display = f"@{target_user.username}"
            resolved = (target_user_id, user_display)
            logger.info(
                "Using message sender as target user for photo-based generation",
                user_id=target_user_id,
            )
        else:
            await message.answer(
                "❌ Не вдалося знайти користувача.\n\n"
                "Використання:\n"
                "• `/autocard` (у відповідь на повідомлення)\n"
                "• `/autocard @username`\n"
                "• `/autocard 392817811`\n"
                "• `/autocard` (з фото та описом)\n"
                "• `/autocard` (у відповідь на повідомлення з фото)",
                parse_mode="Markdown",
            )
            return
    
    if not resolved:
        return

    target_user_id, user_display = resolved

    # Retrieve user's actual name/username for persona-based card generation
    target_user_name = None
    async for session in get_session():
        try:
            user_stmt = select(User).where(User.telegram_id == target_user_id)
            result = await session.execute(user_stmt)
            db_user = result.scalar_one_or_none()
            
            if db_user and db_user.username:
                target_user_name = db_user.username
            elif db_user:
                # If no username, try to get from Telegram API
                try:
                    chat = await bot.get_chat(target_user_id)
                    if chat and chat.username:
                        target_user_name = chat.username
                    elif chat and chat.first_name:
                        # Use first_name + last_name if available
                        target_user_name = chat.first_name
                        if chat.last_name:
                            target_user_name = f"{chat.first_name} {chat.last_name}"
                except Exception:
                    pass
            
            # If still no name, use the display name (remove @ prefix if present)
            if not target_user_name and user_display:
                target_user_name = user_display.lstrip("@")
        except Exception as e:
            logger.warning(
                "Error retrieving user name for card generation",
                target_user_id=target_user_id,
                error=str(e),
            )
        break

    # Send initial feedback (escape user_display to avoid Markdown parsing errors)
    escaped_display = escape_markdown(user_display)
    status_msg = await message.answer(f"🕵️‍♂️ Аналізую особистість {escaped_display}...")

    try:
        # Get chat ID from message
        chat_id = message.chat.id if message.chat else target_user_id

        # Update status
        await status_msg.edit_text("🧠 Проєктую архітектуру картки...")

        # Use NanoBananaService for complete AI-driven generation
        nano_banana = NanoBananaService()
        image_url, blueprint = await nano_banana.generate_card_for_user(
            user_id=target_user_id,
            chat_id=chat_id,
            bot=bot,
            user_name=target_user_name,
            custom_photo_bytes=custom_photo_bytes,
            custom_description=custom_description,
        )

        if not blueprint or not image_url:
            await status_msg.edit_text(
                f"❌ Не вдалося згенерувати картку для користувача {escaped_display}."
            )
            return

        # Delete status message
        await status_msg.delete()

        # Format caption
        biome_emoji = get_biome_emoji(blueprint.biome)
        caption = (
            f"**{blueprint.name}**\n\n"
            f"{biome_emoji} **Біом:** {blueprint.biome.value}\n"
            f"⚔️ **АТАКА:** {blueprint.stats['atk']}\n"
            f"🛡️ **ЗАХИСТ:** {blueprint.stats['def']}\n"
            f"🎭 **МЕМНІСТЬ:** {blueprint.stats.get('meme', 0)}\n"
            f"💎 **Рідкість:** {blueprint.rarity.value}\n\n"
            f"📖 **Лор:** {blueprint.lore}"
        )

        # Store blueprint data in Redis (TTL: 1 hour)
        blueprint_data = {
            "name": blueprint.name,
            "raw_image_prompt_en": blueprint.raw_image_prompt_en,
            "biome": blueprint.biome.value,
            "rarity": blueprint.rarity.value,
            "atk": blueprint.stats["atk"],
            "def": blueprint.stats["def"],
            "meme": blueprint.stats.get("meme", 0),
            "lore": blueprint.lore,
            "dominant_color_hex": blueprint.dominant_color_hex,
            "accent_color_hex": blueprint.accent_color_hex,
            "attacks": blueprint.attacks,
            "weakness": blueprint.weakness,
            "resistance": blueprint.resistance,
            "print_date": blueprint.print_date,
            "target_user_id": target_user_id,
            "image_url": image_url,
        }
        blueprint_id = await session_manager.store_blueprint(blueprint_data, ttl=3600)

        keyboard = build_autocard_main_keyboard(blueprint_id)

        # Send preview
        if image_url:
            # If we have an image path, send as photo using FSInputFile
            from pathlib import Path
            from database.enums import Rarity

            image_path = Path(image_url)
            is_rare = blueprint.rarity in (Rarity.EPIC, Rarity.LEGENDARY, Rarity.MYTHIC)
            
            if is_rare:
                # For rare cards, try animated MP4 first, then GIF fallback
                animated_mp4_path = image_path.parent / f"{image_path.stem}_animated.mp4"
                animated_gif_path = image_path.parent / f"{image_path.stem}_animated.gif"
                
                if animated_mp4_path.exists():
                    # Use helper function for proper animation parameters
                    await send_card_animation(
                        message,
                        animated_mp4_path,
                        caption,
                        reply_markup=keyboard,
                        parse_mode="Markdown",
                    )
                elif animated_gif_path.exists():
                    # Fallback to GIF if MP4 doesn't exist
                    await send_card_animation(
                        message,
                        animated_gif_path,
                        caption,
                        reply_markup=keyboard,
                        parse_mode="Markdown",
                    )
                elif image_path.exists():
                    # Fallback to regular photo
                    photo_file = FSInputFile(str(image_path))
                    await message.answer_photo(
                        photo=photo_file,
                        caption=caption,
                        reply_markup=keyboard,
                        parse_mode="Markdown",
                    )
            elif image_path.exists():
                # Common/Rare: always send as photo
                photo_file = FSInputFile(str(image_path))
                await message.answer_photo(
                    photo=photo_file,
                    caption=caption,
                    reply_markup=keyboard,
                    parse_mode="Markdown",
                )
            else:
                # If file doesn't exist, send as text message
                logger.warning(
                    "Image file not found, sending text message",
                    image_path=str(image_path),
                )
                await message.answer(
                    text=caption,
                    reply_markup=keyboard,
                    parse_mode="Markdown",
                )
        else:
            # If no image, send as text message
            await message.answer(
                text=caption,
                reply_markup=keyboard,
                parse_mode="Markdown",
            )

    except Exception as e:
        logger.error(
            "Error in autocard generation",
            target_user_id=target_user_id,
            error=str(e),
            exc_info=True,
        )
        try:
            await status_msg.edit_text("❌ Помилка при генерації картки.")
        except Exception:
            pass


async def _regenerate_card_image(
    blueprint_data: dict,
    bot: Bot
) -> str | None:
    """
    Regenerate card image from blueprint data.
    
    Args:
        blueprint_data: Blueprint data dictionary from Redis.
        bot: Bot instance (unused but kept for consistency).
    
    Returns:
        Relative filepath to the new image if successful, otherwise None.
    """
    try:
        from services.art_forge import ArtForgeService
        
        # Create ArtForgeService instance
        art_forge = ArtForgeService()
        
        # Get placeholder path
        nano_banana = NanoBananaService()
        biome = BiomeType(blueprint_data["biome"])
        rarity = Rarity(blueprint_data["rarity"])
        placeholder_path = nano_banana._get_placeholder_path(biome, rarity)
        
        # Generate new image
        logger.info(
            "Regenerating card image",
            card_name=blueprint_data["name"],
            biome=blueprint_data["biome"],
            rarity=blueprint_data["rarity"],
        )
        
        new_image_path = await art_forge.forge_card_image(
            blueprint_prompt=blueprint_data["raw_image_prompt_en"],
            biome=biome,
            rarity=rarity,
            placeholder_path=placeholder_path,
            user_photo_bytes=None,
            group_photo_bytes=None,
            card_fields=blueprint_data,
        )
        
        logger.info(
            "Card image regenerated successfully",
            new_image_path=new_image_path,
        )
        
        return new_image_path
        
    except Exception as e:
        logger.error(
            "Error regenerating card image",
            error=str(e),
            exc_info=True,
        )
        return None


async def _send_card_preview(
    message: Message,
    blueprint_data: dict,
    image_url: str,
    blueprint_id: str,
) -> None:
    """
    Send card preview with image and caption.
    
    Args:
        message: Message to reply to (or bot for sending).
        blueprint_data: Blueprint data dictionary.
        image_url: Path to card image.
        blueprint_id: Blueprint ID for callbacks.
    """
    from pathlib import Path
    
    # Format caption
    biome_emoji = get_biome_emoji(BiomeType(blueprint_data["biome"]))
    caption = (
        f"**{blueprint_data['name']}**\n\n"
        f"{biome_emoji} **Біом:** {blueprint_data['biome']}\n"
        f"⚔️ **АТАКА:** {blueprint_data['atk']}\n"
        f"🛡️ **ЗАХИСТ:** {blueprint_data['def']}\n"
        f"💎 **Рідкість:** {blueprint_data['rarity']}\n\n"
        f"📖 **Лор:** {blueprint_data['lore']}"
    )
    
    # Create keyboard with all four options
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Перегенерувати Зображення",
                    callback_data=AutocardCallback(
                        action="regenerate", blueprint_id=blueprint_id
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Редагувати Поля",
                    callback_data=AutocardCallback(
                        action="edit", blueprint_id=blueprint_id
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Затвердити та Видати",
                    callback_data=AutocardCallback(
                        action="approve", blueprint_id=blueprint_id
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Скасувати",
                    callback_data=AutocardCallback(
                        action="cancel", blueprint_id=blueprint_id
                    ).pack(),
                )
            ],
        ]
    )
    
    # Send preview
    if image_url:
        image_path = Path(image_url)
        rarity = Rarity(blueprint_data["rarity"])
        is_rare = rarity in (Rarity.EPIC, Rarity.LEGENDARY, Rarity.MYTHIC)
        
        if is_rare:
            # For rare cards, try animated MP4 first, then GIF fallback
            animated_mp4_path = image_path.parent / f"{image_path.stem}_animated.mp4"
            animated_gif_path = image_path.parent / f"{image_path.stem}_animated.gif"
            
            if animated_mp4_path.exists():
                await send_card_animation(
                    message,
                    animated_mp4_path,
                    caption,
                    reply_markup=keyboard,
                    parse_mode="Markdown",
                )
            elif animated_gif_path.exists():
                await send_card_animation(
                    message,
                    animated_gif_path,
                    caption,
                    reply_markup=keyboard,
                    parse_mode="Markdown",
                )
            elif image_path.exists():
                photo_file = FSInputFile(str(image_path))
                await message.answer_photo(
                    photo=photo_file,
                    caption=caption,
                    reply_markup=keyboard,
                    parse_mode="Markdown",
                )
        elif image_path.exists():
            photo_file = FSInputFile(str(image_path))
            await message.answer_photo(
                photo=photo_file,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="Markdown",
            )
        else:
            await message.answer(
                text=caption,
                reply_markup=keyboard,
                parse_mode="Markdown",
            )
    else:
        await message.answer(
            text=caption,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )


@router.callback_query(AutocardCallback.filter(F.action == "regenerate"))
async def handle_autocard_regenerate(
    callback: CallbackQuery, callback_data: AutocardCallback, bot: Bot
) -> None:
    """Handle card image regeneration request."""
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return
    
    # Check admin
    if not callback.from_user or callback.from_user.id not in settings.admin_user_ids:
        await safe_callback_answer(callback,"❌ У вас немає прав доступу.", show_alert=True)
        return
    
    try:
        # Retrieve blueprint data from Redis
        blueprint_data = await session_manager.get_blueprint(callback_data.blueprint_id)
        if not blueprint_data:
            await safe_callback_answer(callback,"❌ Дані картки не знайдено або застаріли.", show_alert=True)
            return
        
        # Show status
        await safe_callback_answer(callback,"🔄 Генерую нове зображення...")
        
        # Regenerate image
        new_image_path = await _regenerate_card_image(blueprint_data, bot)
        
        if not new_image_path:
            # Keep message in place; just alert.
            await safe_callback_answer(callback,"❌ Помилка при генерації зображення. Спробуйте ще раз.", show_alert=True)
            return
        
        # Update blueprint in Redis with new image path
        blueprint_data["image_url"] = new_image_path
        await session_manager.update_blueprint(
            callback_data.blueprint_id, blueprint_data, ttl=3600
        )

        # Update preview message in-place (media + caption + keyboard)
        await _edit_preview_media(
            bot,
            callback.message.chat.id,
            callback.message.message_id,
            blueprint_data,
            callback_data.blueprint_id,
            reply_markup=build_autocard_main_keyboard(callback_data.blueprint_id),
        )
        
        logger.info(
            "Card image regenerated",
            card_name=blueprint_data["name"],
            admin_id=callback.from_user.id,
        )
        
    except Exception as e:
        logger.error(
            "Error processing regenerate request",
            error=str(e),
            exc_info=True,
        )
        await safe_callback_answer(callback,"❌ Помилка при обробці запиту.", show_alert=True)


@router.callback_query(AutocardCallback.filter(F.action == "edit"))
async def handle_autocard_edit(
    callback: CallbackQuery, callback_data: AutocardCallback, state: FSMContext
) -> None:
    """Switch the preview message into the inline edit UI (no JSON)."""
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return
    
    # Check admin
    if not callback.from_user or callback.from_user.id not in settings.admin_user_ids:
        await safe_callback_answer(callback,"❌ У вас немає прав доступу.", show_alert=True)
        return
    
    try:
        # Retrieve blueprint data from Redis
        blueprint_data = await session_manager.get_blueprint(callback_data.blueprint_id)
        if not blueprint_data:
            await safe_callback_answer(callback,"❌ Дані картки не знайдено або застаріли.", show_alert=True)
            return

        # Clear any pending input state and show edit keyboard on the same message.
        await state.clear()

        try:
            await callback.message.edit_reply_markup(
                reply_markup=build_autocard_edit_keyboard(callback_data.blueprint_id)
            )
        except Exception as e:
            logger.warning("Could not edit reply markup for edit menu", error=str(e))

        await safe_callback_answer(callback, "✏️ Оберіть поле для редагування")
        
    except Exception as e:
        logger.error(
            "Error processing edit request",
            error=str(e),
            exc_info=True,
        )
        await safe_callback_answer(callback,"❌ Помилка при обробці запиту.", show_alert=True)


@router.callback_query(AutocardEditCallback.filter())
async def handle_autocard_edit_actions(
    callback: CallbackQuery,
    callback_data: AutocardEditCallback,
    state: FSMContext,
    bot: Bot,
) -> None:
    """Handle inline edit UI actions (field menus, typed prompts, choice sets)."""
    if not callback.message:
        await safe_callback_answer(callback, "Помилка: повідомлення не знайдено", show_alert=True)
        return

    if not callback.from_user or callback.from_user.id not in settings.admin_user_ids:
        await safe_callback_answer(callback, "❌ У вас немає прав доступу.", show_alert=True)
        return

    blueprint_data = await session_manager.get_blueprint(callback_data.blueprint_id)
    if not blueprint_data:
        await safe_callback_answer(callback, "❌ Дані картки не знайдено або застаріли.", show_alert=True)
        return

    action = callback_data.action

    # Navigation
    if action == "b":
        await state.clear()
        try:
            await callback.message.edit_reply_markup(
                reply_markup=build_autocard_main_keyboard(callback_data.blueprint_id)
            )
        except Exception:
            pass
        await safe_callback_answer(callback)
        return

    if action == "m":
        await state.clear()
        try:
            await callback.message.edit_reply_markup(
                reply_markup=build_autocard_edit_keyboard(callback_data.blueprint_id)
            )
        except Exception:
            pass
        await safe_callback_answer(callback)
        return

    if action == "bm":
        await state.clear()
        try:
            await callback.message.edit_reply_markup(
                reply_markup=build_autocard_biome_keyboard(callback_data.blueprint_id)
            )
        except Exception:
            pass
        await safe_callback_answer(callback)
        return

    if action == "rm":
        await state.clear()
        try:
            await callback.message.edit_reply_markup(
                reply_markup=build_autocard_rarity_keyboard(callback_data.blueprint_id)
            )
        except Exception:
            pass
        await safe_callback_answer(callback)
        return

    if action == "am":
        await state.clear()
        attacks = blueprint_data.get("attacks") or []
        try:
            await callback.message.edit_reply_markup(
                reply_markup=build_autocard_attacks_keyboard(callback_data.blueprint_id, attacks)
            )
        except Exception:
            pass
        await safe_callback_answer(callback)
        return

    # Cancel pending typed input
    if action == "ci":
        data = await state.get_data()
        await state.clear()

        # Restore caption without prompt, and keyboard back to last known menu.
        return_mode = data.get("return_mode", "edit_menu")
        if return_mode == "attack_fields":
            idx = int(data.get("attack_idx", 0) or 0)
            keyboard = build_autocard_attack_fields_keyboard(callback_data.blueprint_id, idx)
        else:
            keyboard = build_autocard_edit_keyboard(callback_data.blueprint_id)

        try:
            # Use in-place edit helper so we refresh the caption consistently.
            await _edit_preview_media(
                bot,
                callback.message.chat.id,
                callback.message.message_id,
                blueprint_data,
                callback_data.blueprint_id,
                reply_markup=keyboard,
            )
        except Exception:
            pass

        await safe_callback_answer(callback)
        return

    # Ask for typed value
    if action == "a":
        field = callback_data.field.strip()
        allowed = {"name", "atk", "def", "meme", "lore", "raw_image_prompt_en", "print_date"}
        if field not in allowed:
            await safe_callback_answer(callback, "❌ Це поле поки що не підтримується.", show_alert=True)
            return

        prompt = ""
        if field == "name":
            prompt = "✏️ Введіть нову **назву** одним повідомленням."
        elif field in {"atk", "def", "meme"}:
            prompt = f"✏️ Введіть нове значення **{field.upper()}** (0–100)."
        elif field == "lore":
            prompt = "✏️ Введіть новий **лор** (українською, до ~500 символів)."
        elif field == "raw_image_prompt_en":
            prompt = "✏️ Введіть новий **image prompt** (англійською)."
        elif field == "print_date":
            prompt = "✏️ Введіть нову **дату друку** у форматі `MM/YYYY` (наприклад `01/2026`)."

        await state.update_data(
            blueprint_id=callback_data.blueprint_id,
            scope="card",
            field=field,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            return_mode="edit_menu",
        )
        await state.set_state(CardEditStates.waiting_for_value)

        # Show prompt on the same message and swap keyboard to input controls.
        caption_extra = prompt
        try:
            if callback.message.photo or callback.message.animation or callback.message.video:
                await callback.message.edit_caption(
                    caption=_format_caption_from_blueprint_data(blueprint_data, extra=caption_extra),
                    parse_mode="Markdown",
                    reply_markup=build_autocard_input_keyboard(callback_data.blueprint_id),
                )
            else:
                await callback.message.edit_text(
                    text=_format_caption_from_blueprint_data(blueprint_data, extra=caption_extra),
                    parse_mode="Markdown",
                    reply_markup=build_autocard_input_keyboard(callback_data.blueprint_id),
                )
        except Exception as e:
            logger.warning("Could not show input prompt on preview message", error=str(e))

        await safe_callback_answer(callback)
        return

    # Set choice value (biome/rarity)
    if action == "s":
        await state.clear()
        field = callback_data.field.strip()
        value = callback_data.value.strip()

        if field == "biome":
            try:
                blueprint_data["biome"] = BiomeType[value].value
            except Exception:
                await safe_callback_answer(callback, "❌ Невірний біом.", show_alert=True)
                return
        elif field == "rarity":
            try:
                blueprint_data["rarity"] = Rarity[value].value
            except Exception:
                await safe_callback_answer(callback, "❌ Невірна рідкість.", show_alert=True)
                return
        else:
            await safe_callback_answer(callback, "❌ Невірне поле.", show_alert=True)
            return

        # Persist changes before regen
        await session_manager.update_blueprint(callback_data.blueprint_id, blueprint_data, ttl=3600)

        await safe_callback_answer(callback, "🔄 Оновлюю...")

        new_image_path = await _regenerate_card_image(blueprint_data, bot)
        if not new_image_path:
            await safe_callback_answer(callback, "❌ Помилка при генерації зображення.", show_alert=True)
            return

        blueprint_data["image_url"] = new_image_path
        await session_manager.update_blueprint(callback_data.blueprint_id, blueprint_data, ttl=3600)

        await _edit_preview_media(
            bot,
            callback.message.chat.id,
            callback.message.message_id,
            blueprint_data,
            callback_data.blueprint_id,
            reply_markup=build_autocard_edit_keyboard(callback_data.blueprint_id),
        )
        await safe_callback_answer(callback, "✅ Готово")
        return

    # Unknown action
    await safe_callback_answer(callback)


@router.callback_query(AutocardAttackCallback.filter())
async def handle_autocard_attack_actions(
    callback: CallbackQuery,
    callback_data: AutocardAttackCallback,
    state: FSMContext,
    bot: Bot,
) -> None:
    """Handle attack editing actions."""
    if not callback.message:
        await safe_callback_answer(callback, "Помилка: повідомлення не знайдено", show_alert=True)
        return

    if not callback.from_user or callback.from_user.id not in settings.admin_user_ids:
        await safe_callback_answer(callback, "❌ У вас немає прав доступу.", show_alert=True)
        return

    blueprint_data = await session_manager.get_blueprint(callback_data.blueprint_id)
    if not blueprint_data:
        await safe_callback_answer(callback, "❌ Дані картки не знайдено або застаріли.", show_alert=True)
        return

    attacks = blueprint_data.get("attacks") or []
    action = callback_data.action

    if action == "m":
        try:
            await callback.message.edit_reply_markup(
                reply_markup=build_autocard_attacks_keyboard(callback_data.blueprint_id, attacks)
            )
        except Exception:
            pass
        await safe_callback_answer(callback)
        return

    if action == "b":
        try:
            await callback.message.edit_reply_markup(
                reply_markup=build_autocard_edit_keyboard(callback_data.blueprint_id)
            )
        except Exception:
            pass
        await safe_callback_answer(callback)
        return

    if action == "x":
        idx = int(callback_data.idx)
        if idx < 0 or idx >= len(attacks):
            await safe_callback_answer(callback, "❌ Невірний індекс атаки.", show_alert=True)
            return
        try:
            await callback.message.edit_reply_markup(
                reply_markup=build_autocard_attack_fields_keyboard(callback_data.blueprint_id, idx)
            )
        except Exception:
            pass
        await safe_callback_answer(callback)
        return

    if action == "t":
        idx = int(callback_data.idx)
        if idx < 0 or idx >= len(attacks):
            await safe_callback_answer(callback, "❌ Невірний індекс атаки.", show_alert=True)
            return
        try:
            await callback.message.edit_reply_markup(
                reply_markup=build_autocard_attack_type_keyboard(callback_data.blueprint_id, idx)
            )
        except Exception:
            pass
        await safe_callback_answer(callback)
        return

    if action == "u":
        idx = int(callback_data.idx)
        if idx < 0 or idx >= len(attacks):
            await safe_callback_answer(callback, "❌ Невірний індекс атаки.", show_alert=True)
            return
        try:
            await callback.message.edit_reply_markup(
                reply_markup=build_autocard_attack_status_keyboard(callback_data.blueprint_id, idx)
            )
        except Exception:
            pass
        await safe_callback_answer(callback)
        return

    if action == "p":
        await state.clear()
        if len(attacks) >= 2:
            await safe_callback_answer(callback, "❌ Максимум 2 атаки.", show_alert=True)
            return

        attacks.append(
            {
                "name": "Нова атака",
                "type": AttackType.PHYSICAL.value,
                "damage": 10,
                "energy_cost": 1,
                "effect": None,
                "status_effect": StatusEffect.NONE.value,
            }
        )
        blueprint_data["attacks"] = attacks
        await session_manager.update_blueprint(callback_data.blueprint_id, blueprint_data, ttl=3600)

        await safe_callback_answer(callback, "🔄 Додаю атаку та оновлюю...")
        new_image_path = await _regenerate_card_image(blueprint_data, bot)
        if not new_image_path:
            await safe_callback_answer(callback, "❌ Помилка при генерації зображення.", show_alert=True)
            return

        blueprint_data["image_url"] = new_image_path
        await session_manager.update_blueprint(callback_data.blueprint_id, blueprint_data, ttl=3600)

        await _edit_preview_media(
            bot,
            callback.message.chat.id,
            callback.message.message_id,
            blueprint_data,
            callback_data.blueprint_id,
            reply_markup=build_autocard_attacks_keyboard(callback_data.blueprint_id, attacks),
        )
        await safe_callback_answer(callback, "✅ Готово")
        return

    if action == "d":
        await state.clear()
        idx = int(callback_data.idx)
        if idx < 0 or idx >= len(attacks):
            await safe_callback_answer(callback, "❌ Невірний індекс атаки.", show_alert=True)
            return

        attacks.pop(idx)
        blueprint_data["attacks"] = attacks
        await session_manager.update_blueprint(callback_data.blueprint_id, blueprint_data, ttl=3600)

        await safe_callback_answer(callback, "🔄 Видаляю атаку та оновлюю...")
        new_image_path = await _regenerate_card_image(blueprint_data, bot)
        if not new_image_path:
            await safe_callback_answer(callback, "❌ Помилка при генерації зображення.", show_alert=True)
            return

        blueprint_data["image_url"] = new_image_path
        await session_manager.update_blueprint(callback_data.blueprint_id, blueprint_data, ttl=3600)

        await _edit_preview_media(
            bot,
            callback.message.chat.id,
            callback.message.message_id,
            blueprint_data,
            callback_data.blueprint_id,
            reply_markup=build_autocard_attacks_keyboard(callback_data.blueprint_id, attacks),
        )
        await safe_callback_answer(callback, "✅ Готово")
        return

    if action == "s":
        await state.clear()
        idx = int(callback_data.idx)
        if idx < 0 or idx >= len(attacks):
            await safe_callback_answer(callback, "❌ Невірний індекс атаки.", show_alert=True)
            return

        field_code = callback_data.field.strip()
        value = callback_data.value.strip()

        if field_code == "t":
            try:
                attacks[idx]["type"] = AttackType[value].value
            except Exception:
                await safe_callback_answer(callback, "❌ Невірний тип атаки.", show_alert=True)
                return
        elif field_code == "s":
            try:
                attacks[idx]["status_effect"] = StatusEffect[value].value
            except Exception:
                await safe_callback_answer(callback, "❌ Невірний статус.", show_alert=True)
                return
        else:
            await safe_callback_answer(callback, "❌ Невірне поле.", show_alert=True)
            return

        blueprint_data["attacks"] = attacks
        await session_manager.update_blueprint(callback_data.blueprint_id, blueprint_data, ttl=3600)

        await safe_callback_answer(callback, "🔄 Оновлюю...")
        new_image_path = await _regenerate_card_image(blueprint_data, bot)
        if not new_image_path:
            await safe_callback_answer(callback, "❌ Помилка при генерації зображення.", show_alert=True)
            return

        blueprint_data["image_url"] = new_image_path
        await session_manager.update_blueprint(callback_data.blueprint_id, blueprint_data, ttl=3600)

        await _edit_preview_media(
            bot,
            callback.message.chat.id,
            callback.message.message_id,
            blueprint_data,
            callback_data.blueprint_id,
            reply_markup=build_autocard_attack_fields_keyboard(callback_data.blueprint_id, idx),
        )
        await safe_callback_answer(callback, "✅ Готово")
        return

    if action == "a":
        idx = int(callback_data.idx)
        if idx < 0 or idx >= len(attacks):
            await safe_callback_answer(callback, "❌ Невірний індекс атаки.", show_alert=True)
            return

        field_code = callback_data.field.strip()
        if field_code not in {"n", "d", "e", "f"}:
            await safe_callback_answer(callback, "❌ Це поле поки що не підтримується.", show_alert=True)
            return

        prompt = ""
        if field_code == "n":
            prompt = "✏️ Введіть нову **назву атаки** одним повідомленням."
        elif field_code == "d":
            prompt = "✏️ Введіть новий **урон** (0–100)."
        elif field_code == "e":
            prompt = "✏️ Введіть нову **вартість енергії** (1–3)."
        elif field_code == "f":
            prompt = "✏️ Введіть **ефект** (або `-` щоб очистити)."

        await state.update_data(
            blueprint_id=callback_data.blueprint_id,
            scope="attack",
            attack_idx=idx,
            attack_field=field_code,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            return_mode="attack_fields",
        )
        await state.set_state(CardEditStates.waiting_for_value)

        try:
            if callback.message.photo or callback.message.animation or callback.message.video:
                await callback.message.edit_caption(
                    caption=_format_caption_from_blueprint_data(blueprint_data, extra=prompt),
                    parse_mode="Markdown",
                    reply_markup=build_autocard_input_keyboard(callback_data.blueprint_id),
                )
            else:
                await callback.message.edit_text(
                    text=_format_caption_from_blueprint_data(blueprint_data, extra=prompt),
                    parse_mode="Markdown",
                    reply_markup=build_autocard_input_keyboard(callback_data.blueprint_id),
                )
        except Exception as e:
            logger.warning("Could not show attack input prompt on preview message", error=str(e))

        await safe_callback_answer(callback)
        return

    await safe_callback_answer(callback)


@router.callback_query(AutocardCallback.filter(F.action == "approve"))
async def handle_autocard_approve(
    callback: CallbackQuery, callback_data: AutocardCallback
) -> None:
    """Handle autocard approval - save card and issue to user."""
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    # Check admin
    if not callback.from_user or callback.from_user.id not in settings.admin_user_ids:
        await safe_callback_answer(callback,"❌ У вас немає прав доступу.", show_alert=True)
        return

    try:
        # Retrieve blueprint data from Redis
        blueprint_data = await session_manager.get_blueprint(callback_data.blueprint_id)
        if not blueprint_data:
            await safe_callback_answer(callback,"❌ Дані картки не знайдено або застаріли.", show_alert=True)
            return
        
        target_user_id = blueprint_data["target_user_id"]

        # Save CardTemplate and create UserCard
        async for session in get_session():
            try:
                # Get or create target user
                user_stmt = select(User).where(User.telegram_id == target_user_id)
                result = await session.execute(user_stmt)
                db_user = result.scalar_one_or_none()

                if not db_user:
                    db_user = User(
                        telegram_id=target_user_id,
                        username=None,
                        balance=0,
                    )
                    session.add(db_user)
                    await session.flush()

                # Create CardTemplate
                card_template = CardTemplate(
                    name=blueprint_data["name"],
                    image_url=None,  # Will be set if image was generated
                    rarity=blueprint_data["rarity"],
                    biome_affinity=BiomeType(blueprint_data["biome"]),
                    stats={"atk": blueprint_data["atk"], "def": blueprint_data["def"], "meme": blueprint_data.get("meme", 0)},
                    attacks=blueprint_data.get("attacks", []),
                    weakness=blueprint_data.get("weakness"),
                    resistance=blueprint_data.get("resistance"),
                    print_date=blueprint_data.get("print_date"),
                )
                session.add(card_template)
                await session.flush()

                # Generate unique display ID for the card
                display_id = await generate_unique_display_id(session)
                
                # Create UserCard for target user
                user_card = UserCard(
                    user_id=db_user.telegram_id,
                    template_id=card_template.id,
                    display_id=display_id,
                )
                session.add(user_card)
                await session.commit()

                # Get target user for display
                target_user_stmt = select(User).where(User.telegram_id == target_user_id)
                target_result = await session.execute(target_user_stmt)
                target_db_user = target_result.scalar_one_or_none()

                # Format target user name
                user_display = "Користувач"
                if target_db_user and target_db_user.username:
                    user_display = f"@{target_db_user.username}"
                elif target_db_user:
                    # Try to get from Telegram API if needed, but for now use ID
                    user_display = f"користувачу (ID: {target_user_id})"

                # Escape markdown to prevent parsing errors
                escaped_card_name = escape_markdown(blueprint_data['name'])
                escaped_user_display = escape_markdown(user_display)
                success_text = f"🎉 Картку *{escaped_card_name}* створено та видано {escaped_user_display}!"

                # Edit message - handle photo, animation, video and text messages
                if callback.message.photo or callback.message.animation or callback.message.video:
                    # Media message - edit caption
                    await callback.message.edit_caption(
                        caption=success_text,
                        parse_mode="Markdown",
                    )
                else:
                    # Text message - edit text
                    await callback.message.edit_text(
                        text=success_text,
                        parse_mode="Markdown",
                    )
                await safe_callback_answer(callback)

                logger.info(
                    "Autocard created and issued",
                    card_name=blueprint_data["name"],
                    target_user_id=target_user_id,
                    admin_id=callback.from_user.id,
                    template_id=str(card_template.id),
                )

                # Clean up blueprint data from Redis
                await session_manager.delete_blueprint(callback_data.blueprint_id)

            except Exception as e:
                logger.error(
                    "Error saving autocard",
                    error=str(e),
                    exc_info=True,
                )
                await safe_callback_answer(callback,"❌ Помилка при збереженні картки.", show_alert=True)
            break

    except Exception as e:
        logger.error(
            "Error processing autocard approval",
            error=str(e),
            exc_info=True,
        )
        await safe_callback_answer(callback,"❌ Помилка при обробці запиту.", show_alert=True)


@router.callback_query(AutocardCallback.filter(F.action == "cancel"))
async def handle_autocard_cancel(
    callback: CallbackQuery, callback_data: AutocardCallback
) -> None:
    """Handle autocard cancellation."""
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    # Check admin
    if not callback.from_user or callback.from_user.id not in settings.admin_user_ids:
        await safe_callback_answer(callback,"❌ У вас немає прав доступу.", show_alert=True)
        return

    # Clean up blueprint data from Redis
    await session_manager.delete_blueprint(callback_data.blueprint_id)

    # Edit message - handle photo, animation, and text messages
    cancel_text = "❌ Створення картки скасовано."
    if callback.message.photo or callback.message.animation or callback.message.video:
        # Photo/animation/video message - edit caption
        try:
            await callback.message.edit_caption(caption=cancel_text)
        except Exception as e:
            logger.warning(
                "Could not edit message caption, trying to send new message",
                error=str(e),
            )
            await callback.message.answer(cancel_text)
    elif callback.message.text:
        # Text message - edit text
        try:
            await callback.message.edit_text(text=cancel_text)
        except Exception as e:
            logger.warning(
                "Could not edit message text, trying to send new message",
                error=str(e),
            )
            await callback.message.answer(cancel_text)
    else:
        # Fallback: send new message
        await callback.message.answer(cancel_text)
    await safe_callback_answer(callback)


@router.message(CardEditStates.waiting_for_value)
async def process_card_edit_value(message: Message, state: FSMContext, bot: Bot) -> None:
    """Process typed input for the inline edit UI."""
    if not message.from_user or message.from_user.id not in settings.admin_user_ids:
        await message.answer("❌ У вас немає прав доступу.")
        await state.clear()
        return
    
    try:
        data = await state.get_data()
        blueprint_id = data.get("blueprint_id")
        chat_id = data.get("chat_id")
        preview_message_id = data.get("message_id")
        scope = data.get("scope")

        text = (message.text or "").strip()

        if not blueprint_id or not chat_id or not preview_message_id:
            await message.answer("❌ Помилка: не знайдено контекст редагування. Почніть спочатку.")
            await state.clear()
            return

        if text.lower() in {"/cancel", "cancel"}:
            await state.clear()
            await message.answer("✅ Редагування скасовано.")
            return

        blueprint_data = await session_manager.get_blueprint(blueprint_id)
        if not blueprint_data:
            await message.answer("❌ Дані картки не знайдено або застаріли. Почніть спочатку.")
            await state.clear()
            return

        # Apply update based on scope
        if scope == "card":
            field = data.get("field")
            if field not in {"name", "atk", "def", "meme", "lore", "raw_image_prompt_en", "print_date"}:
                await message.answer("❌ Невідоме поле для редагування.")
                return

            if field in {"atk", "def", "meme"}:
                try:
                    value_int = int(text)
                except ValueError:
                    await message.answer("❌ Введіть число.")
                    return
                if value_int < 0 or value_int > 100:
                    await message.answer("❌ Значення повинно бути від 0 до 100.")
                    return
                blueprint_data[field] = value_int
            elif field == "print_date":
                import re

                if not re.fullmatch(r"(0[1-9]|1[0-2])/[0-9]{4}", text):
                    await message.answer("❌ Невірний формат. Приклад: 01/2026")
                    return
                blueprint_data["print_date"] = text
            else:
                # text fields
                if not text:
                    await message.answer("❌ Значення не може бути порожнім.")
                    return
                if field == "name" and len(text) > 80:
                    await message.answer("❌ Назва занадто довга (макс 80 символів).")
                    return
                if field == "lore" and len(text) > 500:
                    await message.answer("❌ Лор занадто довгий (макс 500 символів).")
                    return
                if field == "raw_image_prompt_en" and len(text) > 1200:
                    await message.answer("❌ Промпт занадто довгий (макс 1200 символів).")
                    return
                blueprint_data[field] = text

            reply_markup = build_autocard_edit_keyboard(blueprint_id)

        elif scope == "attack":
            idx = int(data.get("attack_idx", 0) or 0)
            field_code = (data.get("attack_field") or "").strip()
            attacks = blueprint_data.get("attacks") or []

            if idx < 0 or idx >= len(attacks):
                await message.answer("❌ Атака не знайдена.")
                await state.clear()
                return

            if field_code == "n":
                if not text:
                    await message.answer("❌ Назва не може бути порожньою.")
                    return
                if len(text) > 60:
                    await message.answer("❌ Назва атаки занадто довга (макс 60 символів).")
                    return
                attacks[idx]["name"] = text
            elif field_code == "d":
                try:
                    dmg = int(text)
                except ValueError:
                    await message.answer("❌ Введіть число (0–100).")
                    return
                if dmg < 0 or dmg > 100:
                    await message.answer("❌ Урон повинен бути від 0 до 100.")
                    return
                attacks[idx]["damage"] = dmg
            elif field_code == "e":
                try:
                    cost = int(text)
                except ValueError:
                    await message.answer("❌ Введіть число (1–3).")
                    return
                if cost < 1 or cost > 3:
                    await message.answer("❌ Вартість енергії повинна бути 1–3.")
                    return
                attacks[idx]["energy_cost"] = cost
            elif field_code == "f":
                if text in {"-", "none", "null"}:
                    attacks[idx]["effect"] = None
                else:
                    if len(text) > 200:
                        await message.answer("❌ Ефект занадто довгий (макс 200 символів).")
                        return
                    attacks[idx]["effect"] = text
            else:
                await message.answer("❌ Невідоме поле атаки.")
                return

            blueprint_data["attacks"] = attacks
            reply_markup = build_autocard_attack_fields_keyboard(blueprint_id, idx)

        else:
            await message.answer("❌ Невідомий режим редагування.")
            await state.clear()
            return

        # Persist updated blueprint before regeneration
        await session_manager.update_blueprint(blueprint_id, blueprint_data, ttl=3600)

        # Regenerate image using updated blueprint
        new_image_path = await _regenerate_card_image(blueprint_data, bot)
        if not new_image_path:
            await message.answer("❌ Помилка при генерації зображення. Спробуйте ще раз.")
            await state.clear()
            return

        blueprint_data["image_url"] = new_image_path
        await session_manager.update_blueprint(blueprint_id, blueprint_data, ttl=3600)

        await _edit_preview_media(
            bot,
            int(chat_id),
            int(preview_message_id),
            blueprint_data,
            blueprint_id,
            reply_markup=reply_markup,
        )

        logger.info(
            "Card fields updated and image regenerated",
            card_name=blueprint_data.get("name"),
            admin_id=message.from_user.id,
            scope=scope,
        )

        await state.clear()
        
    except Exception as e:
        logger.error(
            "Error processing card edit value",
            error=str(e),
            exc_info=True,
        )
        await message.answer("❌ Помилка при обробці запиту.")
        await state.clear()
