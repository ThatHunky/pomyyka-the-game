"""Handler for drop claim callbacks."""

from uuid import UUID

from aiogram import F, Router
from aiogram.filters import CallbackData
from aiogram.types import CallbackQuery, User as TelegramUser
from sqlalchemy import select

from database.models import CardTemplate, User, UserCard
from database.session import get_session
from logging_config import get_logger
from services import DropManager

logger = get_logger(__name__)

router = Router(name="drops")


class ClaimDropCallback(CallbackData, prefix="claim_drop"):
    """Callback data for drop claims."""

    template_id: str  # UUID as string


@router.callback_query(F.data == "claim_drop")
async def handle_claim_drop_simple(
    callback: CallbackQuery,
    drop_manager: DropManager,
) -> None:
    """
    Handle simple drop claim callback (data = "claim_drop").

    This handler expects the card template ID to be stored elsewhere
    (e.g., in message entities, reply markup, or Redis).

    Args:
        callback: Callback query event.
        drop_manager: DropManager instance.
    """
    if not callback.message:
        await callback.answer("Помилка: повідомлення не знайдено", show_alert=True)
        return

    user = callback.from_user
    message_id = callback.message.message_id

    # Try to claim the drop
    claimed = await drop_manager.try_claim_drop(message_id, user.id)

    if not claimed:
        # Drop already claimed by someone else
        await callback.answer("❌ Хтось виявився спритнішим!", show_alert=True)
        return

    # Try to extract template_id from message entities or reply markup
    # For now, we'll need to get it from the drop system or message context
    # This is a placeholder - adjust based on how drops store card info
    template_id = None

    # Check if template_id is in reply markup data
    if callback.message.reply_markup:
        for row in callback.message.reply_markup.inline_keyboard:
            for button in row:
                if button.callback_data and button.callback_data != "claim_drop":
                    # Try to parse as structured callback
                    try:
                        parsed = ClaimDropCallback.unpack(button.callback_data)
                        template_id = UUID(parsed.template_id)
                        break
                    except (ValueError, TypeError):
                        continue
            if template_id:
                break

    if not template_id:
        logger.error(
            "Could not extract template_id from drop message",
            message_id=message_id,
            user_id=user.id,
        )
        await callback.answer("Помилка: не вдалося знайти картку", show_alert=True)
        await drop_manager.release_drop(message_id)
        return

    await _award_card_and_update_message(
        callback=callback,
        user=user,
        message_id=message_id,
        template_id=template_id,
        drop_manager=drop_manager,
    )


@router.callback_query(ClaimDropCallback.filter())
async def handle_claim_drop_structured(
    callback: CallbackQuery,
    callback_data: ClaimDropCallback,
    drop_manager: DropManager,
) -> None:
    """
    Handle structured drop claim callback with template_id.

    Args:
        callback: Callback query event.
        callback_data: Parsed callback data with template_id.
        drop_manager: DropManager instance.
    """
    if not callback.message:
        await callback.answer("Помилка: повідомлення не знайдено", show_alert=True)
        return

    user = callback.from_user
    message_id = callback.message.message_id

    # Try to claim the drop
    claimed = await drop_manager.try_claim_drop(message_id, user.id)

    if not claimed:
        # Drop already claimed by someone else
        await callback.answer("❌ Хтось виявився спритнішим!", show_alert=True)
        return

    # Parse template ID
    try:
        template_id = UUID(callback_data.template_id)
    except ValueError:
        logger.error(
            "Invalid template ID in callback",
            template_id=callback_data.template_id,
            user_id=user.id,
        )
        await callback.answer("Помилка: невалідний ID картки", show_alert=True)
        await drop_manager.release_drop(message_id)
        return

    await _award_card_and_update_message(
        callback=callback,
        user=user,
        message_id=message_id,
        template_id=template_id,
        drop_manager=drop_manager,
    )


async def _award_card_and_update_message(
    callback: CallbackQuery,
    user: TelegramUser,
    message_id: int,
    template_id: UUID,
    drop_manager: DropManager,
) -> None:
    """
    Award card to user and update message.

    Args:
        callback: Callback query event.
        user: Telegram user object.
        message_id: Message ID of the drop.
        template_id: Card template UUID.
        drop_manager: DropManager instance.
    """

    # Award card to user
    async for session in get_session():
        try:
            # Get or create user
            user_stmt = select(User).where(User.telegram_id == user.id)
            result = await session.execute(user_stmt)
            db_user = result.scalar_one_or_none()

            if not db_user:
                db_user = User(
                    telegram_id=user.id,
                    username=user.username,
                    balance=0,
                )
                session.add(db_user)
                await session.flush()

            # Get card template
            template_stmt = select(CardTemplate).where(CardTemplate.id == template_id)
            template_result = await session.execute(template_stmt)
            card_template = template_result.scalar_one_or_none()

            if not card_template:
                logger.error(
                    "Card template not found",
                    template_id=template_id,
                    user_id=user.id,
                )
                await callback.answer("Помилка: картка не знайдена", show_alert=True)
                # Release the claim since we can't award the card
                await drop_manager.release_drop(message_id)
                return

            # Create user card
            user_card = UserCard(
                user_id=db_user.telegram_id,
                template_id=card_template.id,
            )
            session.add(user_card)
            await session.commit()

            # Format user name for display
            user_display = user.first_name
            if user.last_name:
                user_display += f" {user.last_name}"
            elif user.username:
                user_display = f"@{user.username}"

            # Edit message with success text
            success_text = f"✅ **{user_display}** блискавично схопив {card_template.name}!"

            await callback.message.edit_text(
                success_text,
                parse_mode="Markdown",
            )
            await callback.answer()

            logger.info(
                "Drop claimed and card awarded",
                user_id=user.id,
                message_id=message_id,
                template_id=template_id,
                card_name=card_template.name,
            )

        except Exception as e:
            logger.error(
                "Error awarding card",
                user_id=user.id,
                message_id=message_id,
                template_id=template_id,
                error=str(e),
                exc_info=True,
            )
            await callback.answer("Помилка при нагородженні карткою", show_alert=True)
            # Release the claim on error
            await drop_manager.release_drop(message_id)
        finally:
            break
