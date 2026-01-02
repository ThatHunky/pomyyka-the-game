"""Admin handlers for card creation and management."""

import re
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import settings
from database.enums import BiomeType, Rarity
from database.models import CardTemplate
from database.session import get_session
from logging_config import get_logger
from services.art_forge import ArtForgeService
from services.card_architect import CardArchitectService
from services.chat_import import ChatImportService
from services.nano_banana import NanoBananaService

logger = get_logger(__name__)

router = Router(name="admin")


class CardCreationStates(StatesGroup):
    """FSM states for card creation flow."""

    waiting_for_name = State()
    waiting_for_biome = State()
    waiting_for_art_prompt = State()
    waiting_for_stats = State()


class BiomeCallback(CallbackData, prefix="biome"):
    """Callback data for biome selection."""

    biome: str


def is_admin(user_id: int) -> bool:
    """Check if user is an admin."""
    return user_id in settings.admin_user_ids


async def check_admin(message: Message) -> bool:
    """Check if message sender is admin and respond if not."""
    user_id = message.from_user.id
    is_user_admin = is_admin(user_id)
    
    if not is_user_admin:
        logger.warning(
            "Admin command attempted by non-admin user",
            user_id=user_id,
            username=message.from_user.username,
            admin_user_ids=settings.admin_user_ids,
            admin_user_ids_type=[type(uid).__name__ for uid in settings.admin_user_ids],
            user_id_type=type(user_id).__name__,
        )
        await message.answer("❌ У вас немає прав доступу до цієї команди.")
        return False
    
    logger.debug(
        "Admin command authorized",
        user_id=user_id,
        username=message.from_user.username,
    )
    return True


@router.message(Command("newcard"))
async def cmd_newcard(message: Message, state: FSMContext) -> None:
    """Start card creation flow."""
    if not await check_admin(message):
        return

    await state.set_state(CardCreationStates.waiting_for_name)
    await message.answer(
        "🎴 **Створення нової картки**\n\nВведіть назву картки:",
        parse_mode="Markdown",
    )


@router.message(CardCreationStates.waiting_for_name)
async def process_card_name(message: Message, state: FSMContext) -> None:
    """Process card name input and show biome selection."""
    card_name = message.text.strip()
    if not card_name:
        await message.answer("❌ Назва не може бути порожньою. Будь ласка, введіть назву:")
        return

    await state.update_data(card_name=card_name)

    # Create inline keyboard with biomes
    keyboard_buttons = []
    for biome in BiomeType:
        keyboard_buttons.append(
            [
                InlineKeyboardButton(
                    text=biome.value,
                    callback_data=BiomeCallback(biome=biome.value).pack(),
                )
            ]
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await message.answer(
        f"✅ Назва картки: **{card_name}**\n\nОберіть біом для картки:",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )
    await state.set_state(CardCreationStates.waiting_for_biome)


@router.callback_query(BiomeCallback.filter(), CardCreationStates.waiting_for_biome)
async def process_biome_selection(
    callback: CallbackQuery,
    callback_data: BiomeCallback,
    state: FSMContext,
) -> None:
    """Process biome selection and request art prompt."""
    if not callback.message:
        await callback.answer("Помилка: повідомлення не знайдено", show_alert=True)
        return

    # Validate biome
    try:
        biome_type = BiomeType(callback_data.biome)
    except ValueError:
        await callback.answer("❌ Невірний біом", show_alert=True)
        return

    await state.update_data(biome=biome_type.value, biome_type=biome_type)

    await callback.message.edit_text(
        f"✅ Біом обрано: **{biome_type.value}**\n\nВведіть опис для генерації зображення:",
        parse_mode="Markdown",
    )
    await callback.answer()
    await state.set_state(CardCreationStates.waiting_for_art_prompt)


async def generate_card_image(user_prompt: str, biome_style: str) -> Optional[str]:
    """
    Generate card image using Nano Banana Pro (Gemini 3 Pro Image).

    Args:
        user_prompt: User's art description prompt.
        biome_style: Biome style for the card.

    Returns:
        Relative filepath to saved image if generation successful, None otherwise.
    """
    if not settings.gemini_api_key:
        logger.warning("Gemini API key not configured, skipping image generation")
        return None

    try:
        # Parse biome from string
        biome = BiomeType(biome_style)

        # Use NanoBananaService for manual image generation
        nano_banana = NanoBananaService()
        image_path = await nano_banana.generate_from_prompt(user_prompt, biome)

        logger.info(
            "Card image generated successfully",
            image_path=image_path,
            biome=biome_style,
        )
        return image_path

    except ValueError as e:
        logger.error(
            "Invalid biome type",
            biome=biome_style,
            error=str(e),
            exc_info=True,
        )
        return None
    except Exception as e:
        logger.error("Error in image generation", error=str(e), exc_info=True)
        return None


@router.message(CardCreationStates.waiting_for_art_prompt)
async def process_art_prompt(message: Message, state: FSMContext) -> None:
    """Process art prompt and generate image using Google GenAI."""
    art_prompt = message.text.strip()
    if not art_prompt:
        await message.answer("❌ Опис не може бути порожнім. Будь ласка, введіть опис:")
        return

    data = await state.get_data()
    biome_style = data.get("biome", "Звичайний")

    await message.answer("🎨 Генерую зображення... Це може зайняти кілька секунд.")

    # Generate image using Google GenAI
    image_url = await generate_card_image(art_prompt, biome_style)

    # Store the prompt and image URL in state
    await state.update_data(art_prompt=art_prompt, image_url=image_url)

    if image_url:
        await message.answer(
            f"✅ Зображення згенеровано!\n\n"
            f"Введіть характеристики картки у форматі:\n"
            f"`АТАКА ЗАХИСТ РІДКІСТЬ`\n\n"
            f"Приклад: `50 30 Common`\n\n"
            f"Доступні рівні рідкості: Common, Rare, Epic, Legendary, Mythic",
            parse_mode="Markdown",
        )
    else:
        await message.answer(
            "⚠️ Генерація зображення тимчасово недоступна.\n\n"
            "Введіть характеристики картки у форматі:\n"
            "`АТАКА ЗАХИСТ РІДКІСТЬ`\n\n"
            "Приклад: `50 30 Common`\n\n"
            "Доступні рівні рідкості: Common, Rare, Epic, Legendary, Mythic",
            parse_mode="Markdown",
        )

    await state.set_state(CardCreationStates.waiting_for_stats)


@router.message(CardCreationStates.waiting_for_stats)
async def process_stats(message: Message, state: FSMContext) -> None:
    """Process card stats input and save card to database."""
    stats_text = message.text.strip()

    # Parse stats: "АТАКА ЗАХИСТ РІДКІСТЬ" or "ATK DEF RARITY"
    # Example: "50 30 Common" or "50 30 Rare"
    stats_pattern = r"(\d+)\s+(\d+)\s+(\w+)"
    match = re.match(stats_pattern, stats_text, re.IGNORECASE)

    if not match:
        await message.answer(
            "❌ Невірний формат характеристик.\n\n"
            "Введіть у форматі: `АТАКА ЗАХИСТ РІДКІСТЬ`\n"
            "Приклад: `50 30 Common`\n\n"
            "Доступні рівні рідкості: Common, Rare, Epic, Legendary, Mythic",
            parse_mode="Markdown",
        )
        return

    atk = int(match.group(1))
    defense = int(match.group(2))
    rarity_str = match.group(3).capitalize()

    # Validate rarity
    try:
        rarity = Rarity(rarity_str)
    except ValueError:
        await message.answer(
            f"❌ Невірна рідкість: {rarity_str}\n\n"
            "Доступні рівні рідкості: Common, Rare, Epic, Legendary, Mythic",
        )
        return

    # Get data from state
    data = await state.get_data()
    card_name = data.get("card_name")
    biome_type = data.get("biome_type")
    image_url = data.get("image_url")

    if not card_name or not biome_type:
        await message.answer("❌ Помилка: дані про картку втрачено. Почніть спочатку з /newcard")
        await state.clear()
        return

    # Save card to database
    async for session in get_session():
        try:
            card_template = CardTemplate(
                name=card_name,
                image_url=image_url,
                rarity=rarity,
                biome_affinity=biome_type,
                stats={"atk": atk, "def": defense},
            )
            session.add(card_template)
            await session.flush()

            await message.answer(
                f"✅ **Картка успішно створена!**\n\n"
                f"📛 Назва: {card_name}\n"
                f"🌍 Біом: {biome_type.value}\n"
                f"⚔️ Атака: {atk}\n"
                f"🛡️ Захист: {defense}\n"
                f"💎 Рідкість: {rarity.value}\n"
                f"🆔 ID: `{card_template.id}`",
                parse_mode="Markdown",
            )

            logger.info(
                "Card template created",
                card_id=str(card_template.id),
                card_name=card_name,
                admin_id=message.from_user.id,
            )

            await state.clear()
            break

        except Exception as e:
            logger.error(
                "Error saving card template",
                error=str(e),
                admin_id=message.from_user.id,
                exc_info=True,
            )
            await message.answer(
                f"❌ Помилка при збереженні картки: {str(e)}",
            )
            break


@router.message(Command("import_chat"))
async def cmd_import_chat(message: Message) -> None:
    """Import chat history from Telegram JSON export."""
    if not await check_admin(message):
        return

    # Parse filename from command
    command_args = message.text.split(maxsplit=1)
    if len(command_args) < 2:
        await message.answer(
            "❌ Вкажіть назву файлу.\n\n"
            "Використання: `/import_chat result.json`\n\n"
            "Файл має бути в директорії `data/chat_exports/`",
            parse_mode="Markdown",
        )
        return

    filename = command_args[1].strip()

    # Validate filename (prevent path traversal)
    if "/" in filename or "\\" in filename or ".." in filename:
        await message.answer("❌ Невірна назва файлу.")
        return

    status_msg = await message.answer(f"📥 Імпортую чат з файлу `{filename}`...")

    async def update_progress(text: str) -> None:
        """Update progress message."""
        try:
            await status_msg.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            logger.warning("Error updating progress message", error=str(e))

    try:
        import_service = ChatImportService()
        stats = await import_service.import_telegram_json(filename, progress_callback=update_progress)

        result_text = (
            f"✅ **Імпорт завершено!**\n\n"
            f"📨 Повідомлень імпортовано: {stats['messages_imported']}\n"
            f"👤 Користувачів створено: {stats['users_created']}\n"
            f"💬 Чатів створено: {stats['chats_created']}\n"
        )

        if stats["errors"] > 0:
            result_text += f"⚠️ Помилок: {stats['errors']}"

        await status_msg.edit_text(result_text, parse_mode="Markdown")

        logger.info(
            "Chat import completed by admin",
            admin_id=message.from_user.id,
            filename=filename,
            **stats,
        )

    except FileNotFoundError:
        await status_msg.edit_text(
            f"❌ Файл `{filename}` не знайдено в `data/chat_exports/`",
            parse_mode="Markdown",
        )
    except ValueError as e:
        await status_msg.edit_text(f"❌ Помилка формату файлу: {str(e)}")
    except Exception as e:
        logger.error(
            "Error importing chat",
            filename=filename,
            admin_id=message.from_user.id,
            error=str(e),
            exc_info=True,
        )
        await status_msg.edit_text(f"❌ Помилка при імпорті: {str(e)}")


@router.message(Command("createcommoncard"))
async def cmd_createcommoncard(message: Message) -> None:
    """
    Create a reusable card template using AI generation from a detailed prompt.
    
    Usage: /createcommoncard <detailed prompt>
    Example: /createcommoncard Шлюхобот - вульгарний мемний робот з техно біому, низька рідкість
    """
    if not await check_admin(message):
        return

    # Parse command arguments
    command_args = message.text.split(maxsplit=1)
    if len(command_args) < 2:
        await message.answer(
            "❌ Вкажіть опис картки.\n\n"
            "Використання: `/createcommoncard <опис>`\n\n"
            "Приклад: `/createcommoncard Шлюхобот - вульгарний мемний робот з техно біому, низька рідкість`\n\n"
            "AI автоматично визначить назву, біом, рідкість, стати та згенерує зображення.",
            parse_mode="Markdown",
        )
        return

    detailed_prompt = command_args[1].strip()
    if not detailed_prompt:
        await message.answer("❌ Опис не може бути порожнім.")
        return

    status_msg = await message.answer("🧠 Генерую архітектуру картки з AI...")

    try:
        # Step 1: Generate blueprint from prompt
        architect = CardArchitectService()
        blueprint = await architect.generate_blueprint_from_prompt(detailed_prompt)

        if not blueprint:
            await status_msg.edit_text("❌ Помилка при генерації архітектури картки.")
            return

        # Step 2: Generate image
        await status_msg.edit_text("🎨 Генерую зображення...")
        art_forge = ArtForgeService()
        image_path = await art_forge.forge_card_image(
            blueprint.raw_image_prompt_en, blueprint.biome
        )

        if not image_path:
            await status_msg.edit_text("❌ Помилка при генерації зображення.")
            return

        # Step 3: Create CardTemplate in database
        await status_msg.edit_text("💾 Зберігаю шаблон картки...")

        async for session in get_session():
            try:
                card_template = CardTemplate(
                    name=blueprint.name,
                    image_url=image_path,
                    rarity=blueprint.rarity,
                    biome_affinity=blueprint.biome,
                    stats={"atk": blueprint.stats["atk"], "def": blueprint.stats["def"]},
                )
                session.add(card_template)
                await session.flush()

                # Format success message
                from utils.text import escape_markdown
                escaped_name = escape_markdown(blueprint.name)
                escaped_lore = escape_markdown(blueprint.lore)

                success_text = (
                    f"✅ **Шаблон картки успішно створено!**\n\n"
                    f"📛 **Назва:** {escaped_name}\n"
                    f"🌍 **Біом:** {blueprint.biome.value}\n"
                    f"⚔️ **Атака:** {blueprint.stats['atk']}\n"
                    f"🛡️ **Захист:** {blueprint.stats['def']}\n"
                    f"💎 **Рідкість:** {blueprint.rarity.value}\n\n"
                    f"📖 **Лоре:** {escaped_lore}\n\n"
                    f"🆔 **ID шаблону:** `{card_template.id}`\n\n"
                    f"🎴 Цей шаблон тепер доступний для розподілу через дропи!"
                )

                await status_msg.edit_text(success_text, parse_mode="Markdown")

                logger.info(
                    "Common card template created via AI",
                    card_id=str(card_template.id),
                    card_name=blueprint.name,
                    rarity=blueprint.rarity.value,
                    biome=blueprint.biome.value,
                    admin_id=message.from_user.id,
                )

                await session.commit()
                break

            except Exception as e:
                logger.error(
                    "Error saving common card template",
                    error=str(e),
                    admin_id=message.from_user.id,
                    exc_info=True,
                )
                await status_msg.edit_text(f"❌ Помилка при збереженні шаблону: {str(e)}")
                await session.rollback()
                break

    except Exception as e:
        logger.error(
            "Error in createcommoncard command",
            error=str(e),
            admin_id=message.from_user.id,
            exc_info=True,
        )
        await status_msg.edit_text(f"❌ Помилка при створенні картки: {str(e)}")