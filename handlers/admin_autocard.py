"""Admin handler for automatic card generation from user messages."""

from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import desc, select

from config import settings
from database.enums import BiomeType
from database.models import CardTemplate, MessageLog, User, UserCard
from database.session import get_session
from handlers.admin import check_admin
from logging_config import get_logger
from services.art_forge import ArtForgeService
from services.card_architect import CardArchitectService, CardBlueprint

logger = get_logger(__name__)

router = Router(name="admin_autocard")


class AutocardCallback(CallbackData, prefix="autocard"):
    """Callback data for autocard approval/cancellation."""

    action: str  # "approve" or "cancel"
    blueprint_data: str  # JSON-encoded blueprint data


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


@router.message(Command("autocard"))
async def cmd_autocard(message: Message) -> None:
    """Handle /autocard command - must be a reply to a user's message."""
    if not await check_admin(message):
        return

    # Check if message is a reply
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("❌ Будь ласка, відповідайте на повідомлення користувача для створення картки.")
        return

    target_user = message.reply_to_message.from_user
    target_user_id = target_user.id

    # Format user name for display
    user_display = target_user.first_name or "Користувач"
    if target_user.last_name:
        user_display += f" {target_user.last_name}"
    elif target_user.username:
        user_display = f"@{target_user.username}"

    # Send initial feedback
    status_msg = await message.answer(f"🕵️‍♂️ Аналізую особистість {user_display}...")

    try:
        # Fetch last 50 messages from MessageLog
        async for session in get_session():
            try:
                stmt = (
                    select(MessageLog.content)
                    .where(MessageLog.user_id == target_user_id)
                    .order_by(desc(MessageLog.created_at))
                    .limit(50)
                )
                result = await session.execute(stmt)
                message_logs = [row[0] for row in result.all()]

                if not message_logs:
                    await status_msg.edit_text(
                        f"❌ Не знайдено повідомлень для користувача {user_display}."
                    )
                    return

                # Flatten into list of strings
                logs_list = list(message_logs)

            except Exception as e:
                logger.error(
                    "Error fetching message logs",
                    target_user_id=target_user_id,
                    error=str(e),
                    exc_info=True,
                )
                await status_msg.edit_text("❌ Помилка при отриманні повідомлень.")
                return
            finally:
                break

        # Architect Step
        await status_msg.edit_text("🧠 Проєктую архітектуру картки...")

        architect = CardArchitectService()
        # Add target user ID to context for the AI service
        blueprint = await architect.generate_blueprint(logs_list, target_user_id=target_user_id)

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

        # Create callback data with blueprint info
        import json

        blueprint_json = json.dumps(
            {
                "name": blueprint.name,
                "raw_image_prompt_en": blueprint.raw_image_prompt_en,
                "biome": blueprint.biome.value,
                "rarity": blueprint.rarity.value,
                "atk": blueprint.stats["atk"],
                "def": blueprint.stats["def"],
                "lore": blueprint.lore,
                "target_user_id": target_user_id,
            }
        )

        # Create inline keyboard
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Затвердити та Видати",
                        callback_data=AutocardCallback(
                            action="approve", blueprint_data=blueprint_json
                        ).pack(),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❌ Скасувати",
                        callback_data=AutocardCallback(
                            action="cancel", blueprint_data=blueprint_json
                        ).pack(),
                    )
                ],
            ]
        )

        # Send preview
        if image_url:
            # If we have an image URL, send as photo
            await message.answer_photo(
                photo=image_url,
                caption=caption,
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
        import json

        blueprint_data = json.loads(callback_data.blueprint_data)
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

                # Edit message
                await callback.message.edit_text(
                    f"🎉 Картку **{blueprint_data['name']}** створено та видано {user_display}!",
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

            except Exception as e:
                logger.error(
                    "Error saving autocard",
                    error=str(e),
                    exc_info=True,
                )
                await callback.answer("❌ Помилка при збереженні картки.", show_alert=True)
            finally:
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

    await callback.message.edit_text("❌ Створення картки скасовано.")
    await callback.answer()
