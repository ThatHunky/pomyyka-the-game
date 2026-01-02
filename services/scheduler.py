"""Scheduler service for triggering random drops in active groups."""

import random
from typing import Optional
from uuid import UUID

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from database.enums import BiomeType
from database.models import CardTemplate, GroupChat
from database.session import get_session
from handlers.drops import ClaimDropCallback
from logging_config import get_logger
from utils.biomes import get_chat_biome

logger = get_logger(__name__)


class DropScheduler:
    """Scheduler for triggering random card drops in active groups."""

    def __init__(
        self,
        bot: Bot,
        interval_minutes: int = 10,
        drop_chance: float = 0.05,
        max_groups_per_run: Optional[int] = None,
    ):
        """
        Initialize DropScheduler.

        Args:
            bot: Aiogram Bot instance for sending messages.
            interval_minutes: Interval in minutes between scheduler runs (default: 10).
            drop_chance: Probability of triggering a drop per group (default: 0.05 = 5%).
            max_groups_per_run: Maximum number of groups to process per run. If None, process all active groups.
        """
        self._bot = bot
        self._interval_minutes = interval_minutes
        self._drop_chance = drop_chance
        self._max_groups_per_run = max_groups_per_run
        self._scheduler: Optional[AsyncIOScheduler] = None

    async def start(self) -> None:
        """Start the scheduler."""
        if self._scheduler is not None:
            logger.warning("Scheduler already started")
            return

        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self._trigger_random_drops,
            "interval",
            minutes=self._interval_minutes,
            id="trigger_random_drops",
            replace_existing=True,
        )
        self._scheduler.start()

        logger.info(
            "Drop scheduler started",
            interval_minutes=self._interval_minutes,
            drop_chance=self._drop_chance,
        )

    async def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler is None:
            return

        self._scheduler.shutdown(wait=True)
        self._scheduler = None
        logger.info("Drop scheduler stopped")

    async def _trigger_random_drops(self) -> None:
        """
        Main job function: fetch active groups and trigger random drops.

        This function:
        1. Fetches active groups from DB
        2. For each group (or random subset), rolls RNG
        3. If successful, calculates biome and selects matching card template
        4. Sends drop message with inline button
        """
        logger.debug("Starting random drops trigger job")

        try:
            # Fetch active groups
            async for session in get_session():
                stmt = select(GroupChat).where(GroupChat.is_active == True)
                result = await session.execute(stmt)
                active_groups = result.scalars().all()

                if not active_groups:
                    logger.debug("No active groups found")
                    return

                # Optionally limit to random subset
                groups_to_process = active_groups
                if self._max_groups_per_run and len(active_groups) > self._max_groups_per_run:
                    groups_to_process = random.sample(
                        active_groups, self._max_groups_per_run
                    )

                logger.debug(
                    "Processing groups for drops",
                    total_groups=len(active_groups),
                    processing=len(groups_to_process),
                )

                # Process each group
                for group in groups_to_process:
                    await self._process_group_drop(session, group)

        except Exception as e:
            logger.error(
                "Error in trigger_random_drops job",
                error=str(e),
                exc_info=True,
            )

    async def _process_group_drop(self, session, group: GroupChat) -> None:
        """
        Process a single group for potential drop.

        Args:
            session: Database session.
            group: GroupChat instance to process.
        """
        # Roll RNG
        if random.random() >= self._drop_chance:
            logger.debug("Drop roll failed", chat_id=group.chat_id)
            return

        logger.info("Drop roll successful", chat_id=group.chat_id)

        try:
            # Calculate biome
            biome = get_chat_biome(group.chat_id)

            # Select random CardTemplate matching biome
            stmt = select(CardTemplate).where(
                CardTemplate.biome_affinity == biome,
                CardTemplate.is_deleted == False,  # noqa: E712
            )
            result = await session.execute(stmt)
            templates = result.scalars().all()

            if not templates:
                logger.warning(
                    "No card templates found for biome",
                    chat_id=group.chat_id,
                    biome=biome.value,
                )
                return

            # Select random template
            selected_template = random.choice(templates)

            # Send drop message
            await self._send_drop_message(group.chat_id, biome, selected_template)

            logger.info(
                "Drop message sent",
                chat_id=group.chat_id,
                biome=biome.value,
                template_id=selected_template.id,
                template_name=selected_template.name,
            )

        except Exception as e:
            logger.error(
                "Error processing group drop",
                chat_id=group.chat_id,
                error=str(e),
                exc_info=True,
            )

    async def _send_drop_message(
        self, chat_id: int, biome: BiomeType, template: CardTemplate
    ) -> None:
        """
        Send drop message to chat with inline button.

        Args:
            chat_id: Telegram chat ID.
            biome: Biome type for the message.
            template: Selected card template.
        """
        try:
            # Create callback data with template ID
            callback_data = ClaimDropCallback(template_id=str(template.id))

            # Create inline keyboard with claim button
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✋ Хапнути",
                            callback_data=callback_data.pack(),
                        )
                    ]
                ]
            )

            # Send message
            message_text = (
                f"⚡️ **Аномалія біому {biome.value} detected!**\n"
                "Тисни кнопку, щоб забрати!"
            )

            await self._bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )

        except Exception as e:
            logger.error(
                "Error sending drop message",
                chat_id=chat_id,
                template_id=template.id,
                error=str(e),
                exc_info=True,
            )
