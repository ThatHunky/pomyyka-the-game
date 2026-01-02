"""Admin handler for automatic card generation from user messages."""

import json
from uuid import UUID

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import desc, distinct, func, select
from sqlalchemy.dialects.postgresql import insert

from config import settings
from database.enums import BiomeType
from database.models import CardTemplate, MessageLog, User, UserCard
from database.session import get_session
from handlers.admin import check_admin
from logging_config import get_logger
from services.art_forge import ArtForgeService
from services.card_architect import CardArchitectService, CardBlueprint
from services.session_manager import SessionManager
from utils.text import escape_markdown

logger = get_logger(__name__)

router = Router(name="admin_autocard")

# Session manager for storing blueprint data
session_manager = SessionManager()


class AutocardCallback(CallbackData, prefix="autocard"):
    """Callback data for autocard approval/cancellation."""

    action: str  # "approve" or "cancel"
    blueprint_id: str  # UUID string for Redis-stored blueprint data


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
    """
    if not await check_admin(message):
        return

    # Parse command arguments
    command_args = message.text.split(maxsplit=1)
    arg = command_args[1] if len(command_args) > 1 else None

    # Resolve target user
    resolved = await resolve_target_user(message, bot, arg)
    if not resolved:
        await message.answer(
            "❌ Не вдалося знайти користувача.\n\n"
            "Використання:\n"
            "• `/autocard` (у відповідь на повідомлення)\n"
            "• `/autocard @username`\n"
            "• `/autocard 392817811`",
            parse_mode="Markdown",
        )
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
        # Fetch messages from MessageLog (chronological order for better context)
        async for session in get_session():
            try:
                stmt = (
                    select(MessageLog.content, MessageLog.created_at)
                    .where(MessageLog.user_id == target_user_id)
                    .where(MessageLog.content.isnot(None))  # Exclude empty messages
                    .where(MessageLog.content != "")  # Exclude empty strings
                    .order_by(MessageLog.created_at.asc())  # Oldest first for chronological context
                    .limit(100)  # Increased to 100 for better context
                )
                result = await session.execute(stmt)
                message_rows = result.all()

                if not message_rows:
                    await status_msg.edit_text(
                        f"❌ Не знайдено повідомлень для користувача {escaped_display}."
                    )
                    return

                # Format messages with better structure for AI context
                # Filter out very short messages, single characters, or just mentions
                logs_list = []
                for content, created_at in message_rows:
                    if content and content.strip():
                        content_clean = content.strip()
                        # Filter out:
                        # - Very short messages (less than 3 chars) unless they're meaningful
                        # - Single emoji or punctuation
                        # - Just mentions (@username)
                        if len(content_clean) >= 3 or content_clean in ["ok", "да", "ні", "yes", "no"]:
                            # Skip if it's just a mention
                            if not (content_clean.startswith("@") and len(content_clean.split()) == 1):
                                logs_list.append(content_clean)

                # Take the most recent messages (last 50-100) for context
                # Keep chronological order so AI sees conversation flow
                if logs_list:
                    # Get last 100 messages for better context, but prioritize recent ones
                    if len(logs_list) > 100:
                        # Take last 100, but weight towards recent
                        logs_list = logs_list[-100:]
                    # Keep all if less than 100
                    
                    logger.info(
                        "Fetched message logs for autocard",
                        target_user_id=target_user_id,
                        total_messages=len(message_rows),
                        filtered_messages=len(logs_list),
                        sample_messages=logs_list[:3] if len(logs_list) >= 3 else logs_list,
                    )
                else:
                    logger.warning(
                        "No valid messages found after filtering",
                        target_user_id=target_user_id,
                        total_rows=len(message_rows),
                    )

            except Exception as e:
                logger.error(
                    "Error fetching message logs",
                    target_user_id=target_user_id,
                    error=str(e),
                    exc_info=True,
                )
                await status_msg.edit_text("❌ Помилка при отриманні повідомлень.")
                return
            break

        # Architect Step
        await status_msg.edit_text("🧠 Проєктую архітектуру картки...")

        architect = CardArchitectService()
        # Pass target user ID and name to context for persona-based card generation
        blueprint = await architect.generate_blueprint(
            logs_list, 
            target_user_id=target_user_id,
            user_name=target_user_name
        )

        if not blueprint:
            await status_msg.edit_text("❌ Помилка при генерації архітектури картки.")
            return

        # Art Forge Step
        await status_msg.edit_text("🎨 Кую візуал у нано-горні...")

        art_forge = ArtForgeService()
        image_url = await art_forge.forge_card_image(
            blueprint.raw_image_prompt_en, blueprint.biome
        )

        # Delete status message
        await status_msg.delete()

        # Format caption
        biome_emoji = get_biome_emoji(blueprint.biome)
        caption = (
            f"**{blueprint.name}**\n\n"
            f"{biome_emoji} **Біом:** {blueprint.biome.value}\n"
            f"⚔️ **АТАКА:** {blueprint.stats['atk']}\n"
            f"🛡️ **ЗАХИСТ:** {blueprint.stats['def']}\n"
            f"💎 **Рідкість:** {blueprint.rarity.value}\n\n"
            f"📖 **Лоре:** {blueprint.lore}"
        )

        # Store blueprint data in Redis (TTL: 1 hour)
        blueprint_data = {
            "name": blueprint.name,
            "raw_image_prompt_en": blueprint.raw_image_prompt_en,
            "biome": blueprint.biome.value,
            "rarity": blueprint.rarity.value,
            "atk": blueprint.stats["atk"],
            "def": blueprint.stats["def"],
            "lore": blueprint.lore,
            "target_user_id": target_user_id,
        }
        blueprint_id = await session_manager.store_blueprint(blueprint_data, ttl=3600)

        # Create inline keyboard
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
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
            # If we have an image path, send as photo using FSInputFile
            from pathlib import Path

            image_path = Path(image_url)
            if image_path.exists():
                photo = FSInputFile(str(image_path))
                await message.answer_photo(
                    photo=photo,
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


@router.callback_query(AutocardCallback.filter(F.action == "approve"))
async def handle_autocard_approve(
    callback: CallbackQuery, callback_data: AutocardCallback
) -> None:
    """Handle autocard approval - save card and issue to user."""
    if not callback.message:
        await callback.answer("Помилка: повідомлення не знайдено", show_alert=True)
        return

    # Check admin
    if not callback.from_user or callback.from_user.id not in settings.admin_user_ids:
        await callback.answer("❌ У вас немає прав доступу.", show_alert=True)
        return

    try:
        # Retrieve blueprint data from Redis
        blueprint_data = await session_manager.get_blueprint(callback_data.blueprint_id)
        if not blueprint_data:
            await callback.answer("❌ Дані картки не знайдено або застаріли.", show_alert=True)
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
                    stats={"atk": blueprint_data["atk"], "def": blueprint_data["def"]},
                )
                session.add(card_template)
                await session.flush()

                # Create UserCard for target user
                user_card = UserCard(
                    user_id=db_user.telegram_id,
                    template_id=card_template.id,
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

                # Edit message - handle both photo and text messages
                if callback.message.photo:
                    # Photo message - edit caption
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
                await callback.answer()

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
                await callback.answer("❌ Помилка при збереженні картки.", show_alert=True)
            break

    except Exception as e:
        logger.error(
            "Error processing autocard approval",
            error=str(e),
            exc_info=True,
        )
        await callback.answer("❌ Помилка при обробці запиту.", show_alert=True)


@router.callback_query(AutocardCallback.filter(F.action == "cancel"))
async def handle_autocard_cancel(
    callback: CallbackQuery, callback_data: AutocardCallback
) -> None:
    """Handle autocard cancellation."""
    if not callback.message:
        await callback.answer("Помилка: повідомлення не знайдено", show_alert=True)
        return

    # Check admin
    if not callback.from_user or callback.from_user.id not in settings.admin_user_ids:
        await callback.answer("❌ У вас немає прав доступу.", show_alert=True)
        return

    # Clean up blueprint data from Redis
    await session_manager.delete_blueprint(callback_data.blueprint_id)

    # Edit message - handle both photo and text messages
    cancel_text = "❌ Створення картки скасовано."
    if callback.message.photo:
        # Photo message - edit caption
        await callback.message.edit_caption(caption=cancel_text)
    else:
        # Text message - edit text
        await callback.message.edit_text(text=cancel_text)
    await callback.answer()
