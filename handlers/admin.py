"""Admin handlers for card creation and management."""

import asyncio
import re
from pathlib import Path
from typing import Optional
from uuid import UUID

from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import settings
from database.enums import BiomeType, Rarity
from database.models import CardTemplate, User, UserCard
from database.session import get_session
from utils.animations import send_card_animation
from logging_config import get_logger
from sqlalchemy import func, select
from utils.card_ids import generate_unique_display_id
from utils.emojis import get_biome_emoji, get_rarity_emoji
from utils.keyboards import NavigationCallback
from utils.text import escape_markdown
from aiogram import F
from utils.telegram_utils import safe_callback_answer
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


class AdminCardBrowseCallback(CallbackData, prefix="admin_cards"):
    """Callback data for admin card browsing."""

    action: str  # "list", "view", "give"
    page: int = 0  # Page number for listing
    template_id: str = ""  # Card template ID for view/give actions
    user_id: int = 0  # User ID for give action


class RegenerateImageCallback(CallbackData, prefix="regen_img"):
    """Callback data for image regeneration."""

    action: str = "regenerate"


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
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    # Validate biome
    try:
        biome_type = BiomeType(callback_data.biome)
    except ValueError:
        await safe_callback_answer(callback,"❌ Невірний біом", show_alert=True)
        return

    await state.update_data(biome=biome_type.value, biome_type=biome_type)

    await callback.message.edit_text(
        f"✅ Біом обрано: **{biome_type.value}**\n\nВведіть опис для генерації зображення:",
        parse_mode="Markdown",
    )
    await safe_callback_answer(callback)
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

    status_msg = await message.answer("🎨 Генерую зображення... Це може зайняти кілька секунд.")

    # Generate image using Google GenAI
    image_url = await generate_card_image(art_prompt, biome_style)

    # Store the prompt and image URL in state
    await state.update_data(art_prompt=art_prompt, image_url=image_url)

    # Delete status message
    try:
        await status_msg.delete()
    except Exception:
        pass

    if image_url:
        # Send image with regenerate button
        try:
            image_path = Path(image_url)
            if image_path.exists():
                photo_file = FSInputFile(str(image_path))
                caption = (
                    "✅ **Зображення згенеровано!**\n\n"
                    "Введіть характеристики картки у форматі:\n"
                    "`АТАКА ЗАХИСТ РІДКІСТЬ`\n\n"
                    "Приклад: `50 30 Common`\n\n"
                    "Доступні рівні рідкості: Common, Rare, Epic, Legendary, Mythic"
                )
                
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🔄 Згенерувати знову",
                                callback_data=RegenerateImageCallback().pack(),
                            )
                        ]
                    ]
                )
                
                await message.answer_photo(
                    photo=photo_file,
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
            else:
                # Fallback if file doesn't exist
                await message.answer(
                    f"✅ Зображення згенеровано!\n\n"
                    f"Введіть характеристики картки у форматі:\n"
                    f"`АТАКА ЗАХИСТ РІДКІСТЬ`\n\n"
                    f"Приклад: `50 30 Common`\n\n"
                    f"Доступні рівні рідкості: Common, Rare, Epic, Legendary, Mythic",
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.warning(
                "Failed to send image preview",
                error=str(e),
                image_url=image_url,
            )
            # Fallback to text message
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


@router.callback_query(RegenerateImageCallback.filter(), CardCreationStates.waiting_for_stats)
async def handle_regenerate_image(
    callback: CallbackQuery,
    callback_data: RegenerateImageCallback,
    state: FSMContext,
) -> None:
    """Handle image regeneration request."""
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return

    data = await state.get_data()
    art_prompt = data.get("art_prompt")
    biome_style = data.get("biome", "Звичайний")

    if not art_prompt:
        await safe_callback_answer(callback,"❌ Помилка: опис для генерації не знайдено", show_alert=True)
        return

    # Show loading state
    try:
        if callback.message.photo:
            await callback.message.edit_caption("🔄 Генерую нове зображення...")
        else:
            await callback.message.edit_text("🔄 Генерую нове зображення...")
    except Exception:
        pass

    await safe_callback_answer(callback,"🔄 Генерую нове зображення...")

    # Generate new image
    image_url = await generate_card_image(art_prompt, biome_style)

    # Update state with new image URL
    await state.update_data(image_url=image_url)

    if image_url:
        try:
            image_path = Path(image_url)
            if image_path.exists():
                photo_file = FSInputFile(str(image_path))
                caption = (
                    "✅ **Зображення згенеровано!**\n\n"
                    "Введіть характеристики картки у форматі:\n"
                    "`АТАКА ЗАХИСТ РІДКІСТЬ`\n\n"
                    "Приклад: `50 30 Common`\n\n"
                    "Доступні рівні рідкості: Common, Rare, Epic, Legendary, Mythic"
                )
                
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🔄 Згенерувати знову",
                                callback_data=RegenerateImageCallback().pack(),
                            )
                        ]
                    ]
                )
                
                # Delete old message and send new one
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                
                await callback.message.answer_photo(
                    photo=photo_file,
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
            else:
                # Fallback if file doesn't exist
                await callback.message.edit_text(
                    f"✅ Зображення згенеровано!\n\n"
                    f"Введіть характеристики картки у форматі:\n"
                    f"`АТАКА ЗАХИСТ РІДКІСТЬ`\n\n"
                    f"Приклад: `50 30 Common`\n\n"
                    f"Доступні рівні рідкості: Common, Rare, Epic, Legendary, Mythic",
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.warning(
                "Failed to send regenerated image",
                error=str(e),
                image_url=image_url,
            )
            # Fallback to text message
            await callback.message.edit_text(
                f"✅ Зображення згенеровано!\n\n"
                f"Введіть характеристики картки у форматі:\n"
                f"`АТАКА ЗАХИСТ РІДКІСТЬ`\n\n"
                f"Приклад: `50 30 Common`\n\n"
                f"Доступні рівні рідкості: Common, Rare, Epic, Legendary, Mythic",
                parse_mode="Markdown",
            )
    else:
        await callback.message.edit_text(
            "⚠️ Генерація зображення тимчасово недоступна.\n\n"
            "Введіть характеристики картки у форматі:\n"
            "`АТАКА ЗАХИСТ РІДКІСТЬ`\n\n"
            "Приклад: `50 30 Common`\n\n"
            "Доступні рівні рідкості: Common, Rare, Epic, Legendary, Mythic",
            parse_mode="Markdown",
        )


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
            # Get current month/year for print_date
            from datetime import datetime
            current_print_date = datetime.now().strftime("%m/%Y")
            
            card_template = CardTemplate(
                name=card_name,
                image_url=image_url,
                rarity=rarity,
                biome_affinity=biome_type,
                stats={"atk": atk, "def": defense},
                attacks=None,  # Manual cards don't have attacks yet
                weakness=None,
                resistance=None,
                print_date=current_print_date,
            )
            session.add(card_template)
            await session.flush()
            await session.commit()

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
                    attacks=blueprint.attacks,
                    weakness=blueprint.weakness,
                    resistance=blueprint.resistance,
                    print_date=blueprint.print_date,
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
                    f"📖 **Лор:** {escaped_lore}\n\n"
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


@router.message(Command("regenerate_animations"))
async def cmd_regenerate_animations(message: Message) -> None:
    """Regenerate placeholder card animations with new effects (admin only)."""
    if not await check_admin(message):
        return
    
    from services.card_animator import CardAnimator
    from database.enums import Rarity
    
    placeholders_dir = Path("assets/placeholders")
    animator = CardAnimator()
    
    cards_to_animate = {
        'NORMAL_EPIC.webp': Rarity.EPIC,
        'NORMAL_LEGENDARY.webp': Rarity.LEGENDARY,
        'NORMAL_MYTHIC.webp': Rarity.MYTHIC,
    }
    
    await message.answer("⏳ Regenerating animations with new beautiful effects (20 fps)...")
    
    regenerated = 0
    for card_name, rarity in cards_to_animate.items():
        card_path = placeholders_dir / card_name
        if not card_path.exists():
            continue
        
        try:
            mp4_path = await asyncio.to_thread(
                animator.generate_card_animation,
                card_path,
                rarity,
                total_frames=40,
                duration=50,
            )
            if mp4_path:
                regenerated += 1
                await message.answer(f"✅ Regenerated: {card_name} ({rarity.value})")
        except Exception as e:
            logger.error(f"Failed to regenerate {card_name}: {e}", exc_info=True)
            await message.answer(f"❌ Error regenerating {card_name}: {str(e)}")
    
    await message.answer(f"✅ Done! Regenerated {regenerated} animations with new beautiful effects at 20 fps.")


@router.message(Command("test_normals"))
async def cmd_test_normals(message: Message) -> None:
    """Send all NORMAL card templates as a test (admin only)."""
    if not await check_admin(message):
        return
    
    placeholders_dir = Path("assets/placeholders")
    
    # Find all NORMAL card files
    normal_cards = []
    rarities = ["COMMON", "RARE", "EPIC", "LEGENDARY", "MYTHIC"]
    
    for rarity in rarities:
        is_rare = rarity in ["EPIC", "LEGENDARY", "MYTHIC"]
        
        if is_rare:
            # For rare cards, try animated MP4 first, then GIF fallback
            animated_mp4_path = placeholders_dir / f"NORMAL_{rarity}_animated.mp4"
            if animated_mp4_path.exists():
                normal_cards.append(("NORMAL", rarity, animated_mp4_path, True, "animation"))
                continue
            
            animated_gif_path = placeholders_dir / f"NORMAL_{rarity}_animated.gif"
            if animated_gif_path.exists():
                normal_cards.append(("NORMAL", rarity, animated_gif_path, True, "animation"))
                continue
        
        # Fallback to regular version
        regular_path = placeholders_dir / f"NORMAL_{rarity}.webp"
        if regular_path.exists():
            normal_cards.append(("NORMAL", rarity, regular_path, False, "photo"))
    
    if not normal_cards:
        await message.answer("❌ Не знайдено жодних NORMAL карток в assets/placeholders/")
        return
    
    await message.answer(f"📤 Відправляю {len(normal_cards)} NORMAL карток для тестування...")
    
    sent_count = 0
    for biome, rarity, card_path, is_animated, file_type in normal_cards:
        try:
            file_input = FSInputFile(str(card_path))
            caption = f"🎴 **{biome} {rarity}**"
            if is_animated:
                caption += " ✨ (Animated)"
            
            if file_type == "animation":
                # Use helper function for proper animation parameters
                await send_card_animation(
                    message,
                    card_path,
                    caption,
                    parse_mode="Markdown",
                )
            else:
                await message.answer_photo(
                    photo=file_input,
                    caption=caption,
                    parse_mode="Markdown",
                )
            
            sent_count += 1
            
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.warning(
                "Failed to send test card",
                card_path=str(card_path),
                error=str(e),
            )
    
    await message.answer(f"✅ Відправлено {sent_count} з {len(normal_cards)} карток!")


@router.message(Command("givecard"))
async def cmd_givecard(message: Message) -> None:
    """Hidden admin command to manually add a card to a user's collection.
    
    Usage: /givecard <user_id> <card_template_id>
    Or: /givecard <user_id> <card_name> (searches by name)
    """
    if not await check_admin(message):
        return
    
    args = message.text.split()[1:] if message.text else []
    
    if len(args) < 2:
        await message.answer(
            "❌ **Невірний формат команди**\n\n"
            "**Використання:**\n"
            "`/givecard <user_id> <card_template_id>`\n"
            "або\n"
            "`/givecard <user_id> <card_name>`\n\n"
            "**Приклади:**\n"
            "`/givecard 392817811 aea9f1d3-9ff4-4079-94a9-5ef3841eda5c`\n"
            "`/givecard 392817811 Test card`",
            parse_mode="Markdown",
        )
        return
    
    try:
        user_id = int(args[0])
    except ValueError:
        await message.answer(f"❌ Невірний user_id: {args[0]}")
        return
    
    card_identifier = " ".join(args[1:])  # In case card name has spaces
    
    async for session in get_session():
        try:
            # Get or create user
            user_stmt = select(User).where(User.telegram_id == user_id)
            result = await session.execute(user_stmt)
            db_user = result.scalar_one_or_none()
            
            if not db_user:
                # Try to get user info from Telegram API
                try:
                    bot = message.bot
                    chat = await bot.get_chat(user_id)
                    db_user = User(
                        telegram_id=user_id,
                        username=chat.username,
                        balance=0,
                    )
                    session.add(db_user)
                    await session.flush()
                except Exception as e:
                    logger.warning(f"Could not create user from Telegram API: {e}")
                    await message.answer(f"❌ Користувача з ID {user_id} не знайдено.")
                    break
            
            # Try to find card template by ID first, then by name
            try:
                card_template_id = UUID(card_identifier)
                template_stmt = select(CardTemplate).where(CardTemplate.id == card_template_id)
            except ValueError:
                # Not a UUID, search by name
                template_stmt = select(CardTemplate).where(CardTemplate.name.ilike(f"%{card_identifier}%"))
            
            template_result = await session.execute(template_stmt)
            card_template = template_result.scalar_one_or_none()
            
            if not card_template:
                await message.answer(
                    f"❌ Картку не знайдено: `{card_identifier}`\n\n"
                    "Перевірте ID або назву картки.",
                    parse_mode="Markdown",
                )
                break
            
            # Generate unique display ID
            display_id = await generate_unique_display_id(session)
            
            # Create user card
            user_card = UserCard(
                user_id=db_user.telegram_id,
                template_id=card_template.id,
                display_id=display_id,
            )
            session.add(user_card)
            await session.commit()
            
            # Format success message
            user_display = f"@{db_user.username}" if db_user.username else f"ID: {db_user.telegram_id}"
            
            await message.answer(
                f"✅ **Картку додано до колекції!**\n\n"
                f"👤 **Користувач:** {user_display}\n"
                f"📛 **Картка:** {card_template.name}\n"
                f"🆔 **Display ID:** {display_id}\n"
                f"💎 **Рідкість:** {card_template.rarity.value}",
                parse_mode="Markdown",
            )
            
            logger.info(
                "Card manually added to user collection",
                admin_id=message.from_user.id,
                user_id=user_id,
                card_template_id=str(card_template.id),
                card_name=card_template.name,
                display_id=display_id,
            )
            break
            
        except Exception as e:
            logger.error(
                "Error in givecard command",
                admin_id=message.from_user.id,
                user_id=user_id,
                card_identifier=card_identifier,
                error=str(e),
                exc_info=True,
            )
            await message.answer(f"❌ Помилка при додаванні картки: {str(e)}")
            await session.rollback()
            break


@router.message(Command("browsecards"))
async def cmd_browse_cards(message: Message) -> None:
    """Admin command to browse all available card templates."""
    if not await check_admin(message):
        return
    
    await _show_card_list(message, page=0)


async def _show_card_list(message: Message, page: int = 0) -> None:
    """Show paginated list of all card templates."""
    CARDS_PER_PAGE = 10
    
    async for session in get_session():
        try:
            # Get total count
            count_stmt = select(func.count(CardTemplate.id))
            total_result = await session.execute(count_stmt)
            total_cards = total_result.scalar_one_or_none() or 0
            
            if total_cards == 0:
                await message.answer("❌ Немає доступних карток в базі даних.")
                break
            
            # Calculate pagination
            total_pages = (total_cards + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE
            if page < 0:
                page = 0
            if page >= total_pages:
                page = total_pages - 1
            
            # Get cards for current page
            cards_stmt = (
                select(CardTemplate)
                .order_by(CardTemplate.name)
                .offset(page * CARDS_PER_PAGE)
                .limit(CARDS_PER_PAGE)
            )
            cards_result = await session.execute(cards_stmt)
            cards = list(cards_result.scalars().all())
            
            # Build list text
            list_text = f"📋 **Всі картки**\n\n"
            list_text += f"Сторінка {page + 1} з {total_pages} ({total_cards} карток)\n\n"
            
            for i, card in enumerate(cards, start=page * CARDS_PER_PAGE + 1):
                biome_emoji = get_biome_emoji(card.biome_affinity)
                rarity_emoji = get_rarity_emoji(card.rarity)
                stats = card.stats
                
                list_text += (
                    f"{i}. {biome_emoji} **{escape_markdown(card.name)}** {rarity_emoji}\n"
                    f"   ⚔️ {stats.get('atk', 0)} / 🛡️ {stats.get('def', 0)} | "
                    f"🆔 `{card.id}`\n\n"
                )
            
            # Build keyboard
            buttons = []
            
            # Card buttons (2 per row)
            for i in range(0, len(cards), 2):
                row = []
                for card in cards[i : i + 2]:
                    card_name = card.name
                    if len(card_name) > 20:
                        card_name = card_name[:17] + "..."
                    row.append(
                        InlineKeyboardButton(
                            text=f"📛 {card_name}",
                            callback_data=AdminCardBrowseCallback(
                                action="view",
                                template_id=str(card.id),
                                page=page
                            ).pack(),
                        )
                    )
                if row:
                    buttons.append(row)
            
            # Pagination controls
            nav_buttons = []
            if page > 0:
                nav_buttons.append(
                    InlineKeyboardButton(
                        text="◀️ Попередня",
                        callback_data=AdminCardBrowseCallback(action="list", page=page - 1).pack(),
                    )
                )
            if page < total_pages - 1:
                nav_buttons.append(
                    InlineKeyboardButton(
                        text="▶️ Наступна",
                        callback_data=AdminCardBrowseCallback(action="list", page=page + 1).pack(),
                    )
                )
            
            if nav_buttons:
                buttons.append(nav_buttons)
            
            # Back button
            buttons.append([
                InlineKeyboardButton(
                    text="🏠 Головне меню",
                    callback_data=NavigationCallback(action="menu").pack(),
                ),
            ])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            
            await message.answer(
                list_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            break
            
        except Exception as e:
            logger.error(
                "Error in browse cards",
                admin_id=message.from_user.id,
                error=str(e),
                exc_info=True,
            )
            await message.answer(f"❌ Помилка при завантаженні карток: {str(e)}")
            break


async def _show_card_list_edit(message: Message, page: int = 0) -> None:
    """Show paginated list of all card templates (for editing existing message)."""
    CARDS_PER_PAGE = 10
    
    async for session in get_session():
        try:
            # Get total count
            count_stmt = select(func.count(CardTemplate.id))
            total_result = await session.execute(count_stmt)
            total_cards = total_result.scalar_one_or_none() or 0
            
            if total_cards == 0:
                await message.edit_text("❌ Немає доступних карток в базі даних.")
                break
            
            # Calculate pagination
            total_pages = (total_cards + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE
            if page < 0:
                page = 0
            if page >= total_pages:
                page = total_pages - 1
            
            # Get cards for current page
            cards_stmt = (
                select(CardTemplate)
                .order_by(CardTemplate.name)
                .offset(page * CARDS_PER_PAGE)
                .limit(CARDS_PER_PAGE)
            )
            cards_result = await session.execute(cards_stmt)
            cards = list(cards_result.scalars().all())
            
            # Build list text
            list_text = f"📋 **Всі картки**\n\n"
            list_text += f"Сторінка {page + 1} з {total_pages} ({total_cards} карток)\n\n"
            
            for i, card in enumerate(cards, start=page * CARDS_PER_PAGE + 1):
                biome_emoji = get_biome_emoji(card.biome_affinity)
                rarity_emoji = get_rarity_emoji(card.rarity)
                stats = card.stats
                
                list_text += (
                    f"{i}. {biome_emoji} **{escape_markdown(card.name)}** {rarity_emoji}\n"
                    f"   ⚔️ {stats.get('atk', 0)} / 🛡️ {stats.get('def', 0)} | "
                    f"🆔 `{card.id}`\n\n"
                )
            
            # Build keyboard
            buttons = []
            
            # Card buttons (2 per row)
            for i in range(0, len(cards), 2):
                row = []
                for card in cards[i : i + 2]:
                    card_name = card.name
                    if len(card_name) > 20:
                        card_name = card_name[:17] + "..."
                    row.append(
                        InlineKeyboardButton(
                            text=f"📛 {card_name}",
                            callback_data=AdminCardBrowseCallback(
                                action="view",
                                template_id=str(card.id),
                                page=page
                            ).pack(),
                        )
                    )
                if row:
                    buttons.append(row)
            
            # Pagination controls
            nav_buttons = []
            if page > 0:
                nav_buttons.append(
                    InlineKeyboardButton(
                        text="◀️ Попередня",
                        callback_data=AdminCardBrowseCallback(action="list", page=page - 1).pack(),
                    )
                )
            if page < total_pages - 1:
                nav_buttons.append(
                    InlineKeyboardButton(
                        text="▶️ Наступна",
                        callback_data=AdminCardBrowseCallback(action="list", page=page + 1).pack(),
                    )
                )
            
            if nav_buttons:
                buttons.append(nav_buttons)
            
            # Back button
            buttons.append([
                InlineKeyboardButton(
                    text="🏠 Головне меню",
                    callback_data=NavigationCallback(action="menu").pack(),
                ),
            ])
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            
            await message.edit_text(
                list_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            break
            
        except Exception as e:
            logger.error(
                "Error in browse cards edit",
                error=str(e),
                exc_info=True,
            )
            await message.edit_text(f"❌ Помилка: {str(e)}")
            break


@router.callback_query(AdminCardBrowseCallback.filter(F.action == "list"))
async def handle_card_list_pagination(
    callback: CallbackQuery, callback_data: AdminCardBrowseCallback
) -> None:
    """Handle card list pagination."""
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return
    
    if not await check_admin(callback.message):
        await safe_callback_answer(callback,"❌ У вас немає прав доступу", show_alert=True)
        return
    
    await _show_card_list_edit(callback.message, page=callback_data.page)
    await safe_callback_answer(callback)


@router.callback_query(AdminCardBrowseCallback.filter(F.action == "view"))
async def handle_card_template_view(
    callback: CallbackQuery, callback_data: AdminCardBrowseCallback
) -> None:
    """Handle viewing a card template."""
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return
    
    if not await check_admin(callback.message):
        await safe_callback_answer(callback,"❌ У вас немає прав доступу", show_alert=True)
        return
    
    try:
        template_id = UUID(callback_data.template_id)
    except ValueError:
        await safe_callback_answer(callback,"❌ Невірний ID картки", show_alert=True)
        return
    
    async for session in get_session():
        try:
            template_stmt = select(CardTemplate).where(CardTemplate.id == template_id)
            result = await session.execute(template_stmt)
            card_template = result.scalar_one_or_none()
            
            if not card_template:
                await safe_callback_answer(callback,"❌ Картку не знайдено", show_alert=True)
                break
            
            stats = card_template.stats
            biome_emoji = get_biome_emoji(card_template.biome_affinity)
            rarity_emoji = get_rarity_emoji(card_template.rarity)
            
            card_text = f"{biome_emoji} **{escape_markdown(card_template.name)}**\n\n"
            card_text += f"🆔 **ID:** `{card_template.id}`\n"
            card_text += f"{biome_emoji} **Біом:** {escape_markdown(card_template.biome_affinity.value)}\n"
            card_text += f"⚔️ **АТАКА:** {stats.get('atk', 0)}\n"
            card_text += f"🛡️ **ЗАХИСТ:** {stats.get('def', 0)}\n"
            if 'meme' in stats:
                card_text += f"🎭 **МЕМНІСТЬ:** {stats.get('meme', 0)}\n"
            card_text += f"{rarity_emoji} **Рідкість:** {escape_markdown(card_template.rarity.value)}\n"
            
            if card_template.print_date:
                card_text += f"\n📅 {card_template.print_date}"
            
            # Build keyboard
            buttons = [
                [
                    InlineKeyboardButton(
                        text="🎁 Видати картку",
                        callback_data=AdminCardBrowseCallback(
                            action="give",
                            template_id=str(card_template.id),
                            page=callback_data.page
                        ).pack(),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="◀️ Назад до списку",
                        callback_data=AdminCardBrowseCallback(
                            action="list",
                            page=callback_data.page
                        ).pack(),
                    )
                ],
            ]
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            
            await callback.message.edit_text(
                card_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            await safe_callback_answer(callback)
            break
            
        except Exception as e:
            logger.error(
                "Error viewing card template",
                template_id=str(template_id),
                error=str(e),
                exc_info=True,
            )
            await safe_callback_answer(callback,"❌ Помилка при завантаженні картки", show_alert=True)
            break


@router.callback_query(AdminCardBrowseCallback.filter(F.action == "give"))
async def handle_card_template_give(
    callback: CallbackQuery, callback_data: AdminCardBrowseCallback
) -> None:
    """Handle giving a card template to a user (prompts for user ID)."""
    if not callback.message:
        await safe_callback_answer(callback,"Помилка: повідомлення не знайдено", show_alert=True)
        return
    
    if not await check_admin(callback.message):
        await safe_callback_answer(callback,"❌ У вас немає прав доступу", show_alert=True)
        return
    
    await safe_callback_answer(callback)
    await callback.message.answer(
        f"📤 **Видача картки**\n\n"
        f"Картка: `{callback_data.template_id}`\n\n"
        f"Введіть user_id користувача для видачі картки:\n"
        f"`/givecard <user_id> {callback_data.template_id}`\n\n"
        f"Або використайте команду `/givecard` з повним ID.",
        parse_mode="Markdown",
    )