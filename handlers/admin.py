"""Admin handlers for card creation and management."""

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

from aiogram import Bot, Router
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
from sqlalchemy.orm import selectinload
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
from utils.images import save_uploaded_image_to_webp

logger = get_logger(__name__)

router = Router(name="admin")


class CardCreationStates(StatesGroup):
    """FSM states for card creation flow."""

    waiting_for_name = State()
    waiting_for_biome = State()
    waiting_for_rarity = State()
    waiting_for_image_source = State()
    waiting_for_art_prompt = State()
    waiting_for_image_preview = State()
    waiting_for_upload_photo = State()
    waiting_for_atk = State()
    waiting_for_def = State()


class BiomeCallback(CallbackData, prefix="biome"):
    """Callback data for biome selection."""

    biome: str


class AdminCardBrowseCallback(CallbackData, prefix="admin_cards"):
    """Callback data for admin card browsing."""

    action: str  # "list", "view", "give"
    page: int = 0  # Page number for listing
    template_id: str = ""  # Card template ID for view/give actions
    user_id: int = 0  # User ID for give action


class AdminTemplateModerationCallback(CallbackData, prefix="admin_tplmod"):
    """Callback data for moderating card templates (soft-delete/restore)."""

    action: str  # "remove_prompt" | "remove_confirm" | "remove_cancel" | "restore_now"
    template_id: str
    page: int = 0


class AdminUserCardsCallback(CallbackData, prefix="admin_ucards"):
    """Callback data for admin browsing/removing user-owned cards."""

    action: str  # "list" | "view" | "remove_prompt" | "remove_confirm" | "remove_cancel"
    user_id: int
    page: int = 0
    card_id: str = ""  # UUID of UserCard


class ImageSourceCallback(CallbackData, prefix="newcard_img"):
    """Callback data for manual card image source selection."""

    source: str  # "generate" | "upload"


class NewCardRarityCallback(CallbackData, prefix="newcard_rarity"):
    """Callback data for rarity selection in manual flow."""

    rarity: str


class NewCardControlCallback(CallbackData, prefix="newcard_ctl"):
    """Callback data for controlling the manual /addcard flow."""

    action: str  # "cancel" | "continue" | "regenerate"


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


async def check_admin_callback(callback: CallbackQuery) -> bool:
    """Check if callback sender is admin and respond if not."""
    user = callback.from_user
    if not user or not is_admin(user.id):
        await safe_callback_answer(callback, "❌ У вас немає прав доступу", show_alert=True)
        return False
    return True


@router.message(Command("newcard", "addcard"))
async def cmd_newcard(message: Message, state: FSMContext) -> None:
    """Start card creation flow."""
    if not await check_admin(message):
        return

    await state.set_state(CardCreationStates.waiting_for_name)
    await message.answer(
        "🎴 **Створення нової картки**\n\nВведіть назву картки:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ Скасувати",
                        callback_data=NewCardControlCallback(action="cancel").pack(),
                    )
                ]
            ]
        ),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Cancel any in-progress FSM flow (admin only)."""
    if not await check_admin(message):
        return

    if await state.get_state():
        await state.clear()
        await message.answer("❌ Дію скасовано.")


@router.message(CardCreationStates.waiting_for_name)
async def process_card_name(message: Message, state: FSMContext) -> None:
    """Process card name input and show biome selection."""
    card_name = message.text.strip()
    if not card_name:
        await message.answer(
            "❌ Назва не може бути порожньою. Будь ласка, введіть назву:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❌ Скасувати",
                            callback_data=NewCardControlCallback(action="cancel").pack(),
                        )
                    ]
                ]
            ),
        )
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

    keyboard_buttons.append(
        [
            InlineKeyboardButton(
                text="❌ Скасувати",
                callback_data=NewCardControlCallback(action="cancel").pack(),
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
    """Process biome selection and ask for rarity (templates are rarity-based)."""
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
        f"✅ Біом обрано: **{biome_type.value}**\n\nОберіть 💎 **рідкість**:",
        parse_mode="Markdown",
        reply_markup=_build_rarity_keyboard(),
    )
    await safe_callback_answer(callback)
    await state.set_state(CardCreationStates.waiting_for_rarity)


def _build_rarity_keyboard() -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for rarity in Rarity:
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{get_rarity_emoji(rarity)} {rarity.value}",
                    callback_data=NewCardRarityCallback(rarity=rarity.value).pack(),
                )
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(
                text="❌ Скасувати",
                callback_data=NewCardControlCallback(action="cancel").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_image_source_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎨 Згенерувати зображення",
                    callback_data=ImageSourceCallback(source="generate").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="📤 Завантажити фото",
                    callback_data=ImageSourceCallback(source="upload").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Скасувати",
                    callback_data=NewCardControlCallback(action="cancel").pack(),
                )
            ],
        ]
    )


async def _send_image_preview(message: Message, image_url: str | None) -> None:
    """Send a best-effort image preview (non-fatal if fails)."""
    if not image_url:
        return

    try:
        image_path = Path(image_url)
        if image_path.exists():
            await message.answer_photo(photo=FSInputFile(str(image_path)))
    except Exception as e:
        logger.warning("Failed to send image preview", error=str(e), image_url=image_url)


@router.callback_query(ImageSourceCallback.filter(), CardCreationStates.waiting_for_image_source)
async def handle_image_source_choice(
    callback: CallbackQuery,
    callback_data: ImageSourceCallback,
    state: FSMContext,
) -> None:
    """Handle Generate vs Upload selection for manual card creation."""
    if not callback.message:
        await safe_callback_answer(callback, "Помилка: повідомлення не знайдено", show_alert=True)
        return

    if callback_data.source == "generate":
        if not settings.gemini_api_key:
            await safe_callback_answer(
                callback,
                "⚠️ GEMINI_API_KEY не налаштований — генерація зображень недоступна. Оберіть завантаження фото.",
                show_alert=True,
            )
            return

        await callback.message.edit_text(
            "Введіть опис для генерації зображення:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❌ Скасувати",
                            callback_data=NewCardControlCallback(action="cancel").pack(),
                        )
                    ]
                ]
            ),
        )
        await safe_callback_answer(callback)
        await state.set_state(CardCreationStates.waiting_for_art_prompt)
        return

    if callback_data.source == "upload":
        await callback.message.edit_text(
            "📤 Надішліть фото для картки одним повідомленням (без документу).",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❌ Скасувати",
                            callback_data=NewCardControlCallback(action="cancel").pack(),
                        )
                    ]
                ]
            ),
        )
        await safe_callback_answer(callback)
        await state.set_state(CardCreationStates.waiting_for_upload_photo)
        return

    await safe_callback_answer(callback, "❌ Невідомий вибір", show_alert=True)


async def generate_card_image(user_prompt: str, biome_style: str, rarity_value: str) -> Optional[str]:
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
        rarity = Rarity(rarity_value)

        # Use NanoBananaService for manual image generation
        nano_banana = NanoBananaService()
        image_path = await nano_banana.generate_from_prompt(user_prompt, biome, rarity=rarity)

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
        await message.answer(
            "❌ Опис не може бути порожнім. Будь ласка, введіть опис:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❌ Скасувати",
                            callback_data=NewCardControlCallback(action="cancel").pack(),
                        )
                    ]
                ]
            ),
        )
        return

    data = await state.get_data()
    biome_style = data.get("biome", "Звичайний")
    rarity_value = data.get("rarity")
    if not rarity_value:
        await message.answer("❌ Помилка: рідкість не обрано. Почніть спочатку з /addcard")
        await state.clear()
        return

    status_msg = await message.answer("🎨 Генерую зображення... Це може зайняти кілька секунд.")

    # Generate image using Google GenAI
    image_url = await generate_card_image(art_prompt, biome_style, rarity_value)

    # Store the prompt and image URL in state
    await state.update_data(art_prompt=art_prompt, image_url=image_url)

    # Delete status message
    try:
        await status_msg.delete()
    except Exception:
        pass

    preview_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Перегенерувати",
                    callback_data=NewCardControlCallback(action="regenerate").pack(),
                ),
                InlineKeyboardButton(
                    text="➡️ Продовжити",
                    callback_data=NewCardControlCallback(action="continue").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Скасувати",
                    callback_data=NewCardControlCallback(action="cancel").pack(),
                )
            ],
        ]
    )

    preview_msg: Message
    if image_url:
        try:
            image_path = Path(image_url)
            if image_path.exists():
                preview_msg = await message.answer_photo(
                    photo=FSInputFile(str(image_path)),
                    caption="✅ Зображення згенеровано. Оберіть дію:",
                    reply_markup=preview_keyboard,
                )
            else:
                preview_msg = await message.answer(
                    "✅ Зображення згенеровано. Оберіть дію:",
                    reply_markup=preview_keyboard,
                )
        except Exception:
            preview_msg = await message.answer(
                "✅ Зображення згенеровано. Оберіть дію:",
                reply_markup=preview_keyboard,
            )
    else:
        preview_msg = await message.answer(
            "⚠️ Генерація зображення тимчасово недоступна. Можете перегенерувати або продовжити без зображення.",
            reply_markup=preview_keyboard,
        )

    await state.update_data(
        preview_chat_id=preview_msg.chat.id if preview_msg.chat else None,
        preview_message_id=preview_msg.message_id,
    )
    await state.set_state(CardCreationStates.waiting_for_image_preview)


@router.message(CardCreationStates.waiting_for_upload_photo)
async def process_uploaded_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    """Process a custom uploaded photo for the manual card."""
    if not message.photo:
        await message.answer(
            "❌ Це не схоже на фото. Надішліть саме фото (не документ).",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❌ Скасувати",
                            callback_data=NewCardControlCallback(action="cancel").pack(),
                        )
                    ]
                ]
            ),
        )
        return

    try:
        largest_photo = message.photo[-1]
        file = await bot.get_file(largest_photo.file_id)
        downloaded = await bot.download_file(file.file_path)
        photo_bytes = downloaded.read()
    except Exception as e:
        logger.warning("Failed to download uploaded photo", error=str(e))
        await message.answer(
            "❌ Не вдалося завантажити фото. Спробуйте ще раз.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❌ Скасувати",
                            callback_data=NewCardControlCallback(action="cancel").pack(),
                        )
                    ]
                ]
            ),
        )
        return

    try:
        image_url = save_uploaded_image_to_webp(photo_bytes, directory="media/cards")
    except Exception as e:
        logger.warning("Failed to save uploaded photo", error=str(e))
        await message.answer(
            "❌ Не вдалося зберегти фото. Спробуйте інше зображення.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❌ Скасувати",
                            callback_data=NewCardControlCallback(action="cancel").pack(),
                        )
                    ]
                ]
            ),
        )
        return

    await state.update_data(image_url=image_url)
    await _send_image_preview(message, image_url)

    await message.answer(
        "Введіть ⚔️ **ATK** (число):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ Скасувати",
                        callback_data=NewCardControlCallback(action="cancel").pack(),
                    )
                ]
            ]
        ),
    )
    await state.set_state(CardCreationStates.waiting_for_atk)


@router.message(CardCreationStates.waiting_for_atk)
async def process_atk(message: Message, state: FSMContext) -> None:
    """Process ATK input."""
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer(
            "❌ ATK має бути числом. Введіть ⚔️ **ATK** ще раз:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❌ Скасувати",
                            callback_data=NewCardControlCallback(action="cancel").pack(),
                        )
                    ]
                ]
            ),
        )
        return

    atk = int(raw)
    await state.update_data(atk=atk)
    await message.answer(
        "Введіть 🛡️ **DEF** (число):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ Скасувати",
                        callback_data=NewCardControlCallback(action="cancel").pack(),
                    )
                ]
            ]
        ),
    )
    await state.set_state(CardCreationStates.waiting_for_def)


@router.message(CardCreationStates.waiting_for_def)
async def process_def(message: Message, state: FSMContext) -> None:
    """Process DEF input."""
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer(
            "❌ DEF має бути числом. Введіть 🛡️ **DEF** ще раз:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="❌ Скасувати",
                            callback_data=NewCardControlCallback(action="cancel").pack(),
                        )
                    ]
                ]
            ),
        )
        return

    defense = int(raw)
    await state.update_data(defense=defense)
    # Finalize and save (rarity is chosen earlier now)
    data = await state.get_data()
    card_name = data.get("card_name")
    biome_type = data.get("biome_type")
    image_url = data.get("image_url")
    atk = data.get("atk")
    rarity_value = data.get("rarity")

    if not card_name or not biome_type or atk is None or rarity_value is None:
        await message.answer("❌ Помилка: дані про картку втрачено. Почніть спочатку з /addcard")
        await state.clear()
        return

    try:
        rarity = Rarity(rarity_value)
    except ValueError:
        await message.answer("❌ Помилка: невірна рідкість. Почніть спочатку з /addcard")
        await state.clear()
        return

    current_print_date = datetime.now().strftime("%m/%Y")

    async for session in get_session():
        try:
            card_template = CardTemplate(
                name=card_name,
                image_url=image_url,
                rarity=rarity,
                biome_affinity=biome_type,
                stats={"atk": int(atk), "def": int(defense)},
                attacks=None,
                weakness=None,
                resistance=None,
                print_date=current_print_date,
            )
            session.add(card_template)
            await session.flush()
            await session.commit()

            escaped_name = escape_markdown(card_name)
            await message.answer(
                f"✅ **Картка успішно створена!**\n\n"
                f"📛 Назва: {escaped_name}\n"
                f"🌍 Біом: {biome_type.value}\n"
                f"⚔️ Атака: {atk}\n"
                f"🛡️ Захист: {defense}\n"
                f"💎 Рідкість: {rarity.value}\n"
                f"🆔 ID: `{card_template.id}`",
                parse_mode="Markdown",
            )

            logger.info(
                "Card template created (manual flow)",
                card_id=str(card_template.id),
                card_name=card_name,
                admin_id=message.from_user.id if message.from_user else None,
            )

            await state.clear()
            break
        except Exception as e:
            logger.error(
                "Error saving card template (manual flow)",
                error=str(e),
                admin_id=message.from_user.id if message.from_user else None,
                exc_info=True,
            )
            await message.answer(f"❌ Помилка при збереженні картки: {str(e)}")
            break


@router.callback_query(NewCardRarityCallback.filter(), CardCreationStates.waiting_for_rarity)
async def process_rarity_selection(
    callback: CallbackQuery,
    callback_data: NewCardRarityCallback,
    state: FSMContext,
) -> None:
    """Process rarity selection and ask how to provide an image."""
    if not callback.message:
        await safe_callback_answer(callback, "Помилка: повідомлення не знайдено", show_alert=True)
        return

    # Validate rarity
    try:
        rarity = Rarity(callback_data.rarity)
    except ValueError:
        await safe_callback_answer(callback, "❌ Невірна рідкість", show_alert=True)
        return

    await state.update_data(rarity=rarity.value)

    await callback.message.edit_text(
        f"✅ Рідкість обрано: **{rarity.value}**\n\nОберіть, як додати зображення:",
        parse_mode="Markdown",
        reply_markup=_build_image_source_keyboard(),
    )
    await safe_callback_answer(callback)
    await state.set_state(CardCreationStates.waiting_for_image_source)


@router.callback_query(NewCardControlCallback.filter(F.action == "cancel"))
async def handle_newcard_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel manual card creation flow from any stage."""
    if not callback.message:
        await safe_callback_answer(callback, "Помилка: повідомлення не знайдено", show_alert=True)
        return
    if not callback.from_user or callback.from_user.id not in settings.admin_user_ids:
        await safe_callback_answer(callback, "❌ У вас немає прав доступу.", show_alert=True)
        return

    await state.clear()
    try:
        await callback.message.edit_text("❌ Створення картки скасовано.")
    except Exception:
        try:
            await callback.message.edit_caption("❌ Створення картки скасовано.")
        except Exception:
            await callback.message.answer("❌ Створення картки скасовано.")
    await safe_callback_answer(callback)


@router.callback_query(NewCardControlCallback.filter(F.action == "continue"), CardCreationStates.waiting_for_image_preview)
async def handle_newcard_continue(callback: CallbackQuery, state: FSMContext) -> None:
    """Continue from generated image preview to stats input."""
    if not callback.message:
        await safe_callback_answer(callback, "Помилка: повідомлення не знайдено", show_alert=True)
        return
    if not callback.from_user or callback.from_user.id not in settings.admin_user_ids:
        await safe_callback_answer(callback, "❌ У вас немає прав доступу.", show_alert=True)
        return

    # Remove buttons from preview to avoid double-submission
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.message.answer(
        "Введіть ⚔️ **ATK** (число):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ Скасувати",
                        callback_data=NewCardControlCallback(action="cancel").pack(),
                    )
                ]
            ]
        ),
    )
    await state.set_state(CardCreationStates.waiting_for_atk)
    await safe_callback_answer(callback)


@router.callback_query(NewCardControlCallback.filter(F.action == "regenerate"), CardCreationStates.waiting_for_image_preview)
async def handle_newcard_regenerate(callback: CallbackQuery, state: FSMContext) -> None:
    """Regenerate the generated image (same prompt/biome/rarity)."""
    if not callback.message:
        await safe_callback_answer(callback, "Помилка: повідомлення не знайдено", show_alert=True)
        return
    if not callback.from_user or callback.from_user.id not in settings.admin_user_ids:
        await safe_callback_answer(callback, "❌ У вас немає прав доступу.", show_alert=True)
        return

    data = await state.get_data()
    art_prompt = (data.get("art_prompt") or "").strip()
    biome_style = data.get("biome", "Звичайний")
    rarity_value = data.get("rarity")
    if not art_prompt or not rarity_value:
        await safe_callback_answer(callback, "❌ Немає даних для перегенерації. Почніть спочатку з /addcard", show_alert=True)
        await state.clear()
        return

    await safe_callback_answer(callback, "🔄 Генерую нове зображення...")

    image_url = await generate_card_image(art_prompt, biome_style, rarity_value)
    await state.update_data(image_url=image_url)

    preview_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Перегенерувати",
                    callback_data=NewCardControlCallback(action="regenerate").pack(),
                ),
                InlineKeyboardButton(
                    text="➡️ Продовжити",
                    callback_data=NewCardControlCallback(action="continue").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Скасувати",
                    callback_data=NewCardControlCallback(action="cancel").pack(),
                )
            ],
        ]
    )

    # Replace the preview message (simpler than editing media across types)
    try:
        await callback.message.delete()
    except Exception:
        pass

    preview_msg: Message
    if image_url:
        try:
            image_path = Path(image_url)
            if image_path.exists():
                preview_msg = await callback.message.answer_photo(
                    photo=FSInputFile(str(image_path)),
                    caption="✅ Зображення згенеровано. Оберіть дію:",
                    reply_markup=preview_keyboard,
                )
            else:
                preview_msg = await callback.message.answer(
                    "✅ Зображення згенеровано. Оберіть дію:",
                    reply_markup=preview_keyboard,
                )
        except Exception:
            preview_msg = await callback.message.answer(
                "✅ Зображення згенеровано. Оберіть дію:",
                reply_markup=preview_keyboard,
            )
    else:
        preview_msg = await callback.message.answer(
            "⚠️ Генерація зображення тимчасово недоступна. Можете перегенерувати або продовжити без зображення.",
            reply_markup=preview_keyboard,
        )

    await state.update_data(
        preview_chat_id=preview_msg.chat.id if preview_msg.chat else None,
        preview_message_id=preview_msg.message_id,
    )


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


async def _resolve_card_template(
    session, identifier: str, *, include_deleted: bool = True
) -> list[CardTemplate]:
    """Resolve a CardTemplate by UUID or name fragment."""
    identifier = identifier.strip()
    if not identifier:
        return []

    stmt = None
    try:
        template_id = UUID(identifier)
        stmt = select(CardTemplate).where(CardTemplate.id == template_id)
    except ValueError:
        stmt = select(CardTemplate).where(CardTemplate.name.ilike(f"%{identifier}%"))

    if not include_deleted:
        stmt = stmt.where(CardTemplate.is_deleted == False)  # noqa: E712

    stmt = stmt.order_by(CardTemplate.name)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.message(Command("removecard"))
async def cmd_removecard(message: Message) -> None:
    """
    Soft-delete a card template (removes from drops, keeps inventories intact).

    Usage: /removecard <template_id | name_fragment>
    """
    if not await check_admin(message):
        return

    args = message.text.split(maxsplit=1) if message.text else []
    if len(args) < 2 or not args[1].strip():
        await message.answer(
            "❌ **Невірний формат команди**\n\n"
            "**Використання:**\n"
            "`/removecard <template_id | name_fragment>`\n\n"
            "**Приклад:**\n"
            "`/removecard aea9f1d3-9ff4-4079-94a9-5ef3841eda5c`",
            parse_mode="Markdown",
        )
        return

    identifier = args[1].strip()

    async for session in get_session():
        try:
            matches = await _resolve_card_template(session, identifier, include_deleted=True)
            if not matches:
                await message.answer(
                    f"❌ Картку не знайдено: `{escape_markdown(identifier)}`",
                    parse_mode="Markdown",
                )
                break

            if len(matches) > 1:
                lines = [
                    "⚠️ **Знайдено декілька карток. Уточніть, використавши точний ID:**\n"
                ]
                for tpl in matches[:10]:
                    status = "🗑️ DELETED" if getattr(tpl, "is_deleted", False) else "✅ ACTIVE"
                    lines.append(f"- {escape_markdown(tpl.name)} ({status}) — `{tpl.id}`")
                if len(matches) > 10:
                    lines.append(f"\n... та ще {len(matches) - 10}")
                await message.answer("\n".join(lines), parse_mode="Markdown")
                break

            template = matches[0]
            if getattr(template, "is_deleted", False):
                await message.answer(
                    f"ℹ️ Шаблон вже видалений: **{escape_markdown(template.name)}**\n"
                    f"🆔 `{template.id}`",
                    parse_mode="Markdown",
                )
                break

            rarity_emoji = get_rarity_emoji(template.rarity)
            biome_emoji = get_biome_emoji(template.biome_affinity)
            stats = template.stats or {}

            confirm_text = (
                "⚠️ **Підтвердження видалення шаблону**\n\n"
                f"{biome_emoji} {rarity_emoji} **{escape_markdown(template.name)}**\n"
                f"🆔 `{template.id}`\n"
                f"⚔️ {stats.get('atk', 0)} / 🛡️ {stats.get('def', 0)}\n\n"
                "Це **прибере картку з дропів**, але **не видалить** вже зібрані картки у гравців.\n\n"
                "Продовжити?"
            )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🗑️ Так, видалити",
                            callback_data=AdminTemplateModerationCallback(
                                action="remove_confirm",
                                # Use compact UUID (32 hex chars) to stay within Telegram's 64-byte callback limit.
                                template_id=template.id.hex,
                            ).pack(),
                        ),
                        InlineKeyboardButton(
                            text="❌ Скасувати",
                            callback_data=AdminTemplateModerationCallback(
                                action="remove_cancel",
                                # Use compact UUID (32 hex chars) to stay within Telegram's 64-byte callback limit.
                                template_id=template.id.hex,
                            ).pack(),
                        ),
                    ]
                ]
            )

            await message.answer(confirm_text, parse_mode="Markdown", reply_markup=keyboard)
            break

        except Exception as e:
            logger.error(
                "Error in removecard command",
                admin_id=message.from_user.id if message.from_user else None,
                identifier=identifier,
                error=str(e),
                exc_info=True,
            )
            await message.answer(f"❌ Помилка: {str(e)}")
            break


@router.callback_query(AdminTemplateModerationCallback.filter(F.action == "remove_cancel"))
async def handle_template_remove_cancel(
    callback: CallbackQuery, callback_data: AdminTemplateModerationCallback
) -> None:
    if not callback.message:
        await safe_callback_answer(callback, "Помилка: повідомлення не знайдено", show_alert=True)
        return
    if not await check_admin_callback(callback):
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔍 Переглянути шаблон",
                    callback_data=AdminCardBrowseCallback(
                        action="view",
                        template_id=callback_data.template_id,
                        page=callback_data.page,
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="◀️ Назад до списку",
                    callback_data=AdminCardBrowseCallback(action="list", page=callback_data.page).pack(),
                )
            ],
        ]
    )
    await callback.message.edit_text("❌ Видалення скасовано.", reply_markup=keyboard)
    await safe_callback_answer(callback)


@router.callback_query(AdminTemplateModerationCallback.filter(F.action == "remove_prompt"))
async def handle_template_remove_prompt(
    callback: CallbackQuery, callback_data: AdminTemplateModerationCallback
) -> None:
    if not callback.message:
        await safe_callback_answer(callback, "Помилка: повідомлення не знайдено", show_alert=True)
        return
    if not await check_admin_callback(callback):
        return

    try:
        template_id = UUID(callback_data.template_id)
    except ValueError:
        await safe_callback_answer(callback, "❌ Невірний ID шаблону", show_alert=True)
        return

    async for session in get_session():
        try:
            stmt = select(CardTemplate).where(CardTemplate.id == template_id)
            result = await session.execute(stmt)
            template = result.scalar_one_or_none()

            if not template:
                await callback.message.edit_text("❌ Шаблон не знайдено.")
                await safe_callback_answer(callback)
                break

            if getattr(template, "is_deleted", False):
                await callback.message.edit_text("ℹ️ Шаблон вже видалений.")
                await safe_callback_answer(callback)
                break

            rarity_emoji = get_rarity_emoji(template.rarity)
            biome_emoji = get_biome_emoji(template.biome_affinity)
            stats = template.stats or {}

            confirm_text = (
                "⚠️ **Підтвердження видалення шаблону**\n\n"
                f"{biome_emoji} {rarity_emoji} **{escape_markdown(template.name)}**\n"
                f"🆔 `{template.id}`\n"
                f"⚔️ {stats.get('atk', 0)} / 🛡️ {stats.get('def', 0)}\n\n"
                "Це **прибере картку з дропів**, але **не видалить** вже зібрані картки у гравців.\n\n"
                "Продовжити?"
            )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🗑️ Так, видалити",
                            callback_data=AdminTemplateModerationCallback(
                                action="remove_confirm",
                                # Use compact UUID (32 hex chars) to stay within Telegram's 64-byte callback limit.
                                template_id=template.id.hex,
                                page=callback_data.page,
                            ).pack(),
                        ),
                        InlineKeyboardButton(
                            text="❌ Скасувати",
                            callback_data=AdminTemplateModerationCallback(
                                action="remove_cancel",
                                # Use compact UUID (32 hex chars) to stay within Telegram's 64-byte callback limit.
                                template_id=template.id.hex,
                                page=callback_data.page,
                            ).pack(),
                        ),
                    ]
                ]
            )

            await callback.message.edit_text(confirm_text, parse_mode="Markdown", reply_markup=keyboard)
            await safe_callback_answer(callback)
            break

        except Exception as e:
            logger.error(
                "Error prompting template removal",
                template_id=str(template_id),
                admin_id=callback.from_user.id if callback.from_user else None,
                error=str(e),
                exc_info=True,
            )
            await safe_callback_answer(callback, "❌ Помилка", show_alert=True)
            break


@router.callback_query(AdminTemplateModerationCallback.filter(F.action == "remove_confirm"))
async def handle_template_remove_confirm(
    callback: CallbackQuery, callback_data: AdminTemplateModerationCallback
) -> None:
    if not callback.message:
        await safe_callback_answer(callback, "Помилка: повідомлення не знайдено", show_alert=True)
        return
    if not await check_admin_callback(callback):
        return

    try:
        template_id = UUID(callback_data.template_id)
    except ValueError:
        await safe_callback_answer(callback, "❌ Невірний ID шаблону", show_alert=True)
        return

    async for session in get_session():
        try:
            stmt = select(CardTemplate).where(CardTemplate.id == template_id)
            result = await session.execute(stmt)
            template = result.scalar_one_or_none()

            if not template:
                await callback.message.edit_text("❌ Шаблон не знайдено.")
                await safe_callback_answer(callback)
                break

            if getattr(template, "is_deleted", False):
                await callback.message.edit_text("ℹ️ Шаблон вже видалений.")
                await safe_callback_answer(callback)
                break

            template.is_deleted = True
            template.deleted_at = datetime.now(timezone.utc)
            template.deleted_by = callback.from_user.id if callback.from_user else None
            session.add(template)
            await session.commit()

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="♻️ Відновити",
                            callback_data=AdminTemplateModerationCallback(
                                action="restore_now",
                                # Use compact UUID (32 hex chars) to stay within Telegram's 64-byte callback limit.
                                template_id=template.id.hex,
                                page=callback_data.page,
                            ).pack(),
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="◀️ Назад до списку",
                            callback_data=AdminCardBrowseCallback(action="list", page=callback_data.page).pack(),
                        )
                    ],
                ]
            )
            await callback.message.edit_text(
                "✅ **Шаблон видалено (soft-delete).**\n\n"
                f"📛 {escape_markdown(template.name)}\n"
                f"🆔 `{template.id}`\n\n"
                "Він більше **не випадає** у дропах. Відновити: `/restorecard <id>`",
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            await safe_callback_answer(callback, "✅ Видалено")
            break

        except Exception as e:
            logger.error(
                "Error confirming template removal",
                template_id=str(template_id),
                admin_id=callback.from_user.id if callback.from_user else None,
                error=str(e),
                exc_info=True,
            )
            await session.rollback()
            await safe_callback_answer(callback, "❌ Помилка при видаленні", show_alert=True)
            break


@router.callback_query(AdminTemplateModerationCallback.filter(F.action == "restore_now"))
async def handle_template_restore_now(
    callback: CallbackQuery, callback_data: AdminTemplateModerationCallback
) -> None:
    if not callback.message:
        await safe_callback_answer(callback, "Помилка: повідомлення не знайдено", show_alert=True)
        return
    if not await check_admin_callback(callback):
        return

    try:
        template_id = UUID(callback_data.template_id)
    except ValueError:
        await safe_callback_answer(callback, "❌ Невірний ID шаблону", show_alert=True)
        return

    async for session in get_session():
        try:
            stmt = select(CardTemplate).where(CardTemplate.id == template_id)
            result = await session.execute(stmt)
            template = result.scalar_one_or_none()

            if not template:
                await callback.message.edit_text("❌ Шаблон не знайдено.")
                await safe_callback_answer(callback)
                break

            if not getattr(template, "is_deleted", False):
                await safe_callback_answer(callback, "ℹ️ Шаблон вже активний", show_alert=True)
                break

            template.is_deleted = False
            template.deleted_at = None
            template.deleted_by = None
            session.add(template)
            await session.commit()

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🔍 Переглянути шаблон",
                            callback_data=AdminCardBrowseCallback(
                                action="view",
                                template_id=str(template.id),
                                page=callback_data.page,
                            ).pack(),
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="◀️ Назад до списку",
                            callback_data=AdminCardBrowseCallback(action="list", page=callback_data.page).pack(),
                        )
                    ],
                ]
            )

            await callback.message.edit_text(
                "✅ **Шаблон відновлено.**\n\n"
                f"📛 {escape_markdown(template.name)}\n"
                f"🆔 `{template.id}`\n\n"
                "Він знову може випадати у дропах.",
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            await safe_callback_answer(callback, "✅ Відновлено")
            break

        except Exception as e:
            logger.error(
                "Error restoring template (inline)",
                template_id=str(template_id),
                admin_id=callback.from_user.id if callback.from_user else None,
                error=str(e),
                exc_info=True,
            )
            await session.rollback()
            await safe_callback_answer(callback, "❌ Помилка при відновленні", show_alert=True)
            break


@router.message(Command("restorecard"))
async def cmd_restorecard(message: Message) -> None:
    """
    Restore a previously removed card template (re-enables drops).

    Usage: /restorecard <template_id | name_fragment>
    """
    if not await check_admin(message):
        return

    args = message.text.split(maxsplit=1) if message.text else []
    if len(args) < 2 or not args[1].strip():
        await message.answer(
            "❌ **Невірний формат команди**\n\n"
            "**Використання:**\n"
            "`/restorecard <template_id | name_fragment>`",
            parse_mode="Markdown",
        )
        return

    identifier = args[1].strip()

    async for session in get_session():
        try:
            matches = await _resolve_card_template(session, identifier, include_deleted=True)
            if not matches:
                await message.answer(
                    f"❌ Картку не знайдено: `{escape_markdown(identifier)}`",
                    parse_mode="Markdown",
                )
                break

            if len(matches) > 1:
                lines = [
                    "⚠️ **Знайдено декілька карток. Уточніть, використавши точний ID:**\n"
                ]
                for tpl in matches[:10]:
                    status = "🗑️ DELETED" if getattr(tpl, "is_deleted", False) else "✅ ACTIVE"
                    lines.append(f"- {escape_markdown(tpl.name)} ({status}) — `{tpl.id}`")
                if len(matches) > 10:
                    lines.append(f"\n... та ще {len(matches) - 10}")
                await message.answer("\n".join(lines), parse_mode="Markdown")
                break

            template = matches[0]
            if not getattr(template, "is_deleted", False):
                await message.answer(
                    f"ℹ️ Шаблон вже активний: **{escape_markdown(template.name)}**\n"
                    f"🆔 `{template.id}`",
                    parse_mode="Markdown",
                )
                break

            template.is_deleted = False
            template.deleted_at = None
            template.deleted_by = None
            session.add(template)
            await session.commit()

            await message.answer(
                "✅ **Шаблон відновлено.**\n\n"
                f"📛 {escape_markdown(template.name)}\n"
                f"🆔 `{template.id}`\n\n"
                "Він знову може випадати у дропах.",
                parse_mode="Markdown",
            )
            break

        except Exception as e:
            logger.error(
                "Error in restorecard command",
                admin_id=message.from_user.id if message.from_user else None,
                identifier=identifier,
                error=str(e),
                exc_info=True,
            )
            await session.rollback()
            await message.answer(f"❌ Помилка: {str(e)}")
            break


async def _resolve_user_card_by_identifier(session, identifier: str) -> UserCard | None:
    """Resolve a UserCard by UUID or display_id (case-insensitive)."""
    identifier = (identifier or "").strip()
    if not identifier:
        return None

    stmt = None
    try:
        card_id = UUID(identifier)
        stmt = (
            select(UserCard)
            .where(UserCard.id == card_id)
            .options(selectinload(UserCard.template), selectinload(UserCard.user))
        )
    except ValueError:
        stmt = (
            select(UserCard)
            .where(func.lower(UserCard.display_id) == identifier.lower())
            .options(selectinload(UserCard.template), selectinload(UserCard.user))
        )

    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _show_admin_user_cards(message: Message, target_user_id: int, page: int = 0) -> None:
    """Show another user's card collection for admins (paginated)."""
    CARDS_PER_PAGE = 10

    async for session in get_session():
        try:
            # Ensure user exists (or at least show a helpful message)
            user_stmt = select(User).where(User.telegram_id == target_user_id)
            user_result = await session.execute(user_stmt)
            db_user = user_result.scalar_one_or_none()

            count_stmt = select(func.count(UserCard.id)).where(UserCard.user_id == target_user_id)
            total_result = await session.execute(count_stmt)
            total_cards = total_result.scalar_one_or_none() or 0

            user_display = f"@{db_user.username}" if db_user and db_user.username else f"ID: {target_user_id}"

            if total_cards == 0:
                await message.answer(
                    f"📦 **Колекція користувача порожня**\n\n"
                    f"👤 **Користувач:** {escape_markdown(user_display)}\n"
                    f"🆔 `{target_user_id}`",
                    parse_mode="Markdown",
                )
                break

            total_pages = (total_cards + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE
            if page < 0:
                page = 0
            if page >= total_pages:
                page = total_pages - 1

            cards_stmt = (
                select(UserCard)
                .where(UserCard.user_id == target_user_id)
                .options(selectinload(UserCard.template))
                .order_by(UserCard.acquired_at.desc())
                .offset(page * CARDS_PER_PAGE)
                .limit(CARDS_PER_PAGE)
            )
            cards_result = await session.execute(cards_stmt)
            cards = list(cards_result.scalars().all())

            text = (
                f"🎴 **Колекція користувача**\n\n"
                f"👤 **Користувач:** {escape_markdown(user_display)}\n"
                f"🆔 `{target_user_id}`\n\n"
                f"Сторінка {page + 1} з {total_pages} ({total_cards} карток)\n\n"
            )

            for i, user_card in enumerate(cards, start=page * CARDS_PER_PAGE + 1):
                template = user_card.template
                rarity_emoji = get_rarity_emoji(template.rarity)
                biome_emoji = get_biome_emoji(template.biome_affinity)
                stats = template.stats or {}
                text += (
                    f"{i}. {biome_emoji} **{escape_markdown(template.name)}** {rarity_emoji}\n"
                    f"   🆔 {user_card.display_id} | ⚔️ {stats.get('atk', 0)} / 🛡️ {stats.get('def', 0)}\n\n"
                )

            # Build keyboard
            buttons: list[list[InlineKeyboardButton]] = []

            # Card buttons (2 per row)
            for i in range(0, len(cards), 2):
                row: list[InlineKeyboardButton] = []
                for uc in cards[i : i + 2]:
                    row.append(
                        InlineKeyboardButton(
                            text=f"🆔 {uc.display_id}",
                            callback_data=AdminUserCardsCallback(
                                action="view",
                                user_id=target_user_id,
                                page=page,
                                card_id=str(uc.id),
                            ).pack(),
                        )
                    )
                if row:
                    buttons.append(row)

            # Pagination controls
            nav: list[InlineKeyboardButton] = []
            if page > 0:
                nav.append(
                    InlineKeyboardButton(
                        text="◀️ Попередня",
                        callback_data=AdminUserCardsCallback(
                            action="list",
                            user_id=target_user_id,
                            page=page - 1,
                        ).pack(),
                    )
                )
            if page < total_pages - 1:
                nav.append(
                    InlineKeyboardButton(
                        text="▶️ Наступна",
                        callback_data=AdminUserCardsCallback(
                            action="list",
                            user_id=target_user_id,
                            page=page + 1,
                        ).pack(),
                    )
                )
            if nav:
                buttons.append(nav)

            buttons.append(
                [
                    InlineKeyboardButton(
                        text="🏠 Головне меню",
                        callback_data=NavigationCallback(action="menu").pack(),
                    )
                ]
            )

            await message.answer(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            )
            break

        except Exception as e:
            logger.error(
                "Error showing admin user cards",
                target_user_id=target_user_id,
                error=str(e),
                exc_info=True,
            )
            await message.answer(f"❌ Помилка: {str(e)}")
            break


async def _show_admin_user_cards_edit(message: Message, target_user_id: int, page: int = 0) -> None:
    """Edit an existing message with another user's card collection page."""
    # Reuse the same rendering logic by rebuilding and editing in-place.
    # (We re-query to keep results current after deletions.)
    CARDS_PER_PAGE = 10

    async for session in get_session():
        try:
            user_stmt = select(User).where(User.telegram_id == target_user_id)
            user_result = await session.execute(user_stmt)
            db_user = user_result.scalar_one_or_none()

            count_stmt = select(func.count(UserCard.id)).where(UserCard.user_id == target_user_id)
            total_result = await session.execute(count_stmt)
            total_cards = total_result.scalar_one_or_none() or 0

            user_display = f"@{db_user.username}" if db_user and db_user.username else f"ID: {target_user_id}"

            if total_cards == 0:
                await message.edit_text(
                    f"📦 **Колекція користувача порожня**\n\n"
                    f"👤 **Користувач:** {escape_markdown(user_display)}\n"
                    f"🆔 `{target_user_id}`",
                    parse_mode="Markdown",
                )
                break

            total_pages = (total_cards + CARDS_PER_PAGE - 1) // CARDS_PER_PAGE
            if page < 0:
                page = 0
            if page >= total_pages:
                page = total_pages - 1

            cards_stmt = (
                select(UserCard)
                .where(UserCard.user_id == target_user_id)
                .options(selectinload(UserCard.template))
                .order_by(UserCard.acquired_at.desc())
                .offset(page * CARDS_PER_PAGE)
                .limit(CARDS_PER_PAGE)
            )
            cards_result = await session.execute(cards_stmt)
            cards = list(cards_result.scalars().all())

            text = (
                f"🎴 **Колекція користувача**\n\n"
                f"👤 **Користувач:** {escape_markdown(user_display)}\n"
                f"🆔 `{target_user_id}`\n\n"
                f"Сторінка {page + 1} з {total_pages} ({total_cards} карток)\n\n"
            )

            for i, user_card in enumerate(cards, start=page * CARDS_PER_PAGE + 1):
                template = user_card.template
                rarity_emoji = get_rarity_emoji(template.rarity)
                biome_emoji = get_biome_emoji(template.biome_affinity)
                stats = template.stats or {}
                text += (
                    f"{i}. {biome_emoji} **{escape_markdown(template.name)}** {rarity_emoji}\n"
                    f"   🆔 {user_card.display_id} | ⚔️ {stats.get('atk', 0)} / 🛡️ {stats.get('def', 0)}\n\n"
                )

            buttons: list[list[InlineKeyboardButton]] = []
            for i in range(0, len(cards), 2):
                row: list[InlineKeyboardButton] = []
                for uc in cards[i : i + 2]:
                    row.append(
                        InlineKeyboardButton(
                            text=f"🆔 {uc.display_id}",
                            callback_data=AdminUserCardsCallback(
                                action="view",
                                user_id=target_user_id,
                                page=page,
                                card_id=str(uc.id),
                            ).pack(),
                        )
                    )
                if row:
                    buttons.append(row)

            nav: list[InlineKeyboardButton] = []
            if page > 0:
                nav.append(
                    InlineKeyboardButton(
                        text="◀️ Попередня",
                        callback_data=AdminUserCardsCallback(
                            action="list",
                            user_id=target_user_id,
                            page=page - 1,
                        ).pack(),
                    )
                )
            if page < total_pages - 1:
                nav.append(
                    InlineKeyboardButton(
                        text="▶️ Наступна",
                        callback_data=AdminUserCardsCallback(
                            action="list",
                            user_id=target_user_id,
                            page=page + 1,
                        ).pack(),
                    )
                )
            if nav:
                buttons.append(nav)

            buttons.append(
                [
                    InlineKeyboardButton(
                        text="🏠 Головне меню",
                        callback_data=NavigationCallback(action="menu").pack(),
                    )
                ]
            )

            await message.edit_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            )
            break

        except Exception as e:
            logger.error(
                "Error editing admin user cards list",
                target_user_id=target_user_id,
                error=str(e),
                exc_info=True,
            )
            await message.edit_text(f"❌ Помилка: {str(e)}")
            break


@router.message(Command("usercards"))
async def cmd_usercards(message: Message) -> None:
    """Admin command to view another user's collection."""
    if not await check_admin(message):
        return

    args = message.text.split()[1:] if message.text else []
    if len(args) < 1:
        await message.answer(
            "❌ **Невірний формат команди**\n\n"
            "**Використання:**\n"
            "`/usercards <user_id>`\n\n"
            "**Приклад:**\n"
            "`/usercards 392817811`",
            parse_mode="Markdown",
        )
        return

    try:
        target_user_id = int(args[0])
    except ValueError:
        await message.answer(f"❌ Невірний user_id: {escape_markdown(args[0])}", parse_mode="Markdown")
        return

    await _show_admin_user_cards(message, target_user_id, page=0)


@router.callback_query(AdminUserCardsCallback.filter(F.action == "list"))
async def handle_admin_usercards_pagination(
    callback: CallbackQuery, callback_data: AdminUserCardsCallback
) -> None:
    if not callback.message:
        await safe_callback_answer(callback, "Помилка: повідомлення не знайдено", show_alert=True)
        return
    if not await check_admin_callback(callback):
        return

    await _show_admin_user_cards_edit(callback.message, callback_data.user_id, page=callback_data.page)
    await safe_callback_answer(callback)


@router.callback_query(AdminUserCardsCallback.filter(F.action == "view"))
async def handle_admin_usercards_view(
    callback: CallbackQuery, callback_data: AdminUserCardsCallback
) -> None:
    if not callback.message:
        await safe_callback_answer(callback, "Помилка: повідомлення не знайдено", show_alert=True)
        return
    if not await check_admin_callback(callback):
        return

    try:
        card_id = UUID(callback_data.card_id)
    except ValueError:
        await safe_callback_answer(callback, "❌ Невірний ID картки", show_alert=True)
        return

    async for session in get_session():
        try:
            stmt = (
                select(UserCard)
                .where(UserCard.id == card_id, UserCard.user_id == callback_data.user_id)
                .options(selectinload(UserCard.template))
            )
            result = await session.execute(stmt)
            user_card = result.scalar_one_or_none()

            if not user_card:
                await safe_callback_answer(callback, "❌ Картка не знайдена", show_alert=True)
                break

            template = user_card.template
            stats = template.stats or {}
            biome_emoji = get_biome_emoji(template.biome_affinity)
            rarity_emoji = get_rarity_emoji(template.rarity)

            text = (
                f"{biome_emoji} {rarity_emoji} **{escape_markdown(template.name)}**\n\n"
                f"👤 **User ID:** `{callback_data.user_id}`\n"
                f"🆔 **Display ID:** `{user_card.display_id}`\n"
                f"🔎 **UUID:** `{user_card.id}`\n"
                f"⚔️ **ATK:** {stats.get('atk', 0)}\n"
                f"🛡️ **DEF:** {stats.get('def', 0)}\n"
            )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🗑️ Видалити цю картку",
                            callback_data=AdminUserCardsCallback(
                                action="remove_prompt",
                                user_id=callback_data.user_id,
                                page=callback_data.page,
                                card_id=str(user_card.id),
                            ).pack(),
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="◀️ Назад до списку",
                            callback_data=AdminUserCardsCallback(
                                action="list",
                                user_id=callback_data.user_id,
                                page=callback_data.page,
                            ).pack(),
                        )
                    ],
                ]
            )

            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
            await safe_callback_answer(callback)
            break

        except Exception as e:
            logger.error(
                "Error viewing admin usercard",
                card_id=str(card_id),
                user_id=callback_data.user_id,
                error=str(e),
                exc_info=True,
            )
            await safe_callback_answer(callback, "❌ Помилка", show_alert=True)
            break


@router.callback_query(AdminUserCardsCallback.filter(F.action == "remove_prompt"))
async def handle_admin_usercards_remove_prompt(
    callback: CallbackQuery, callback_data: AdminUserCardsCallback
) -> None:
    if not callback.message:
        await safe_callback_answer(callback, "Помилка: повідомлення не знайдено", show_alert=True)
        return
    if not await check_admin_callback(callback):
        return

    try:
        card_id = UUID(callback_data.card_id)
    except ValueError:
        await safe_callback_answer(callback, "❌ Невірний ID картки", show_alert=True)
        return

    async for session in get_session():
        try:
            stmt = (
                select(UserCard)
                .where(UserCard.id == card_id, UserCard.user_id == callback_data.user_id)
                .options(selectinload(UserCard.template))
            )
            result = await session.execute(stmt)
            user_card = result.scalar_one_or_none()
            if not user_card:
                await safe_callback_answer(callback, "❌ Картка не знайдена", show_alert=True)
                break

            template = user_card.template
            rarity_emoji = get_rarity_emoji(template.rarity)

            text = (
                "⚠️ **Підтвердження видалення картки з колекції**\n\n"
                f"{rarity_emoji} **{escape_markdown(template.name)}**\n"
                f"👤 User ID: `{callback_data.user_id}`\n"
                f"🆔 Display ID: `{user_card.display_id}`\n"
                f"🔎 UUID: `{user_card.id}`\n\n"
                "Цю дію неможливо скасувати.\n\n"
                "Продовжити?"
            )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🗑️ Так, видалити",
                            callback_data=AdminUserCardsCallback(
                                action="remove_confirm",
                                user_id=callback_data.user_id,
                                page=callback_data.page,
                                card_id=str(user_card.id),
                            ).pack(),
                        ),
                        InlineKeyboardButton(
                            text="❌ Скасувати",
                            callback_data=AdminUserCardsCallback(
                                action="remove_cancel",
                                user_id=callback_data.user_id,
                                page=callback_data.page,
                                card_id=str(user_card.id),
                            ).pack(),
                        ),
                    ]
                ]
            )

            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
            await safe_callback_answer(callback)
            break

        except Exception as e:
            logger.error(
                "Error prompting admin usercard removal",
                card_id=str(card_id),
                user_id=callback_data.user_id,
                error=str(e),
                exc_info=True,
            )
            await safe_callback_answer(callback, "❌ Помилка", show_alert=True)
            break


@router.callback_query(AdminUserCardsCallback.filter(F.action == "remove_cancel"))
async def handle_admin_usercards_remove_cancel(
    callback: CallbackQuery, callback_data: AdminUserCardsCallback
) -> None:
    if not callback.message:
        await safe_callback_answer(callback, "Помилка: повідомлення не знайдено", show_alert=True)
        return
    if not await check_admin_callback(callback):
        return

    await callback.message.edit_text("❌ Видалення скасовано.")
    await safe_callback_answer(callback)


@router.callback_query(AdminUserCardsCallback.filter(F.action == "remove_confirm"))
async def handle_admin_usercards_remove_confirm(
    callback: CallbackQuery, callback_data: AdminUserCardsCallback
) -> None:
    if not callback.message:
        await safe_callback_answer(callback, "Помилка: повідомлення не знайдено", show_alert=True)
        return
    if not await check_admin_callback(callback):
        return

    try:
        card_id = UUID(callback_data.card_id)
    except ValueError:
        await safe_callback_answer(callback, "❌ Невірний ID картки", show_alert=True)
        return

    async for session in get_session():
        try:
            # Load for nice messaging
            stmt = (
                select(UserCard)
                .where(UserCard.id == card_id, UserCard.user_id == callback_data.user_id)
                .options(selectinload(UserCard.template))
            )
            result = await session.execute(stmt)
            user_card = result.scalar_one_or_none()
            if not user_card:
                await safe_callback_answer(callback, "❌ Картка не знайдена", show_alert=True)
                break

            template_name = user_card.template.name
            display_id = user_card.display_id

            await session.delete(user_card)
            await session.commit()

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="◀️ Назад до списку",
                            callback_data=AdminUserCardsCallback(
                                action="list",
                                user_id=callback_data.user_id,
                                page=callback_data.page,
                            ).pack(),
                        )
                    ]
                ]
            )

            await callback.message.edit_text(
                "✅ **Картку видалено з колекції.**\n\n"
                f"📛 {escape_markdown(template_name)}\n"
                f"👤 User ID: `{callback_data.user_id}`\n"
                f"🆔 Display ID: `{display_id}`",
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            await safe_callback_answer(callback, "✅ Видалено")
            break

        except Exception as e:
            logger.error(
                "Error confirming admin usercard removal",
                card_id=str(card_id),
                user_id=callback_data.user_id,
                error=str(e),
                exc_info=True,
            )
            await session.rollback()
            await safe_callback_answer(callback, "❌ Помилка при видаленні", show_alert=True)
            break


@router.message(Command("removecollectedcard"))
async def cmd_removecollectedcard(message: Message) -> None:
    """
    Admin command to remove an individual collected card (UserCard).

    Usage: /removecollectedcard <display_id | user_card_uuid>
    """
    if not await check_admin(message):
        return

    args = message.text.split(maxsplit=1) if message.text else []
    if len(args) < 2 or not args[1].strip():
        await message.answer(
            "❌ **Невірний формат команди**\n\n"
            "**Використання:**\n"
            "`/removecollectedcard <display_id | user_card_uuid>`\n\n"
            "**Приклад:**\n"
            "`/removecollectedcard POM-A1B2`",
            parse_mode="Markdown",
        )
        return

    identifier = args[1].strip()

    async for session in get_session():
        try:
            user_card = await _resolve_user_card_by_identifier(session, identifier)
            if not user_card:
                await message.answer(
                    f"❌ Картку не знайдено: `{escape_markdown(identifier)}`",
                    parse_mode="Markdown",
                )
                break

            template = user_card.template
            rarity_emoji = get_rarity_emoji(template.rarity)

            text = (
                "⚠️ **Підтвердження видалення картки з колекції**\n\n"
                f"{rarity_emoji} **{escape_markdown(template.name)}**\n"
                f"👤 User ID: `{user_card.user_id}`\n"
                f"🆔 Display ID: `{user_card.display_id}`\n"
                f"🔎 UUID: `{user_card.id}`\n\n"
                "Цю дію неможливо скасувати.\n\n"
                "Продовжити?"
            )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🗑️ Так, видалити",
                            callback_data=AdminUserCardsCallback(
                                action="remove_confirm",
                                user_id=int(user_card.user_id),
                                page=0,
                                card_id=str(user_card.id),
                            ).pack(),
                        ),
                        InlineKeyboardButton(
                            text="❌ Скасувати",
                            callback_data=AdminUserCardsCallback(
                                action="remove_cancel",
                                user_id=int(user_card.user_id),
                                page=0,
                                card_id=str(user_card.id),
                            ).pack(),
                        ),
                    ]
                ]
            )

            await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)
            break

        except Exception as e:
            logger.error(
                "Error in removecollectedcard command",
                admin_id=message.from_user.id if message.from_user else None,
                identifier=identifier,
                error=str(e),
                exc_info=True,
            )
            await message.answer(f"❌ Помилка: {str(e)}")
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
            count_stmt = select(func.count(CardTemplate.id)).where(CardTemplate.is_deleted == False)  # noqa: E712
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
                .where(CardTemplate.is_deleted == False)  # noqa: E712
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
            count_stmt = select(func.count(CardTemplate.id)).where(CardTemplate.is_deleted == False)  # noqa: E712
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
                .where(CardTemplate.is_deleted == False)  # noqa: E712
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
    
    if not await check_admin_callback(callback):
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
    
    if not await check_admin_callback(callback):
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
            status = "🗑️ **СТАТУС:** DELETED" if getattr(card_template, "is_deleted", False) else "✅ **СТАТУС:** ACTIVE"
            card_text += f"{status}\n"
            
            if card_template.print_date:
                card_text += f"\n📅 {card_template.print_date}"
            
            # Build keyboard
            buttons: list[list[InlineKeyboardButton]] = []

            if getattr(card_template, "is_deleted", False):
                buttons.append(
                    [
                        InlineKeyboardButton(
                            text="♻️ Відновити шаблон",
                            callback_data=AdminTemplateModerationCallback(
                                action="restore_now",
                                # Use compact UUID (32 hex chars) to stay within Telegram's 64-byte callback limit.
                                template_id=card_template.id.hex,
                                page=callback_data.page,
                            ).pack(),
                        )
                    ]
                )
            else:
                buttons.append(
                    [
                        InlineKeyboardButton(
                            text="🗑️ Видалити шаблон",
                            callback_data=AdminTemplateModerationCallback(
                                action="remove_prompt",
                                # Use compact UUID (32 hex chars) to stay within Telegram's 64-byte callback limit.
                                template_id=card_template.id.hex,
                                page=callback_data.page,
                            ).pack(),
                        )
                    ]
                )

            buttons.append(
                [
                    InlineKeyboardButton(
                        text="🎁 Видати картку",
                        callback_data=AdminCardBrowseCallback(
                            action="give",
                            template_id=str(card_template.id),
                            page=callback_data.page
                        ).pack(),
                    )
                ]
            )

            buttons.append(
                [
                    InlineKeyboardButton(
                        text="◀️ Назад до списку",
                        callback_data=AdminCardBrowseCallback(
                            action="list",
                            page=callback_data.page
                        ).pack(),
                    )
                ]
            )
            
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
    
    if not await check_admin_callback(callback):
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