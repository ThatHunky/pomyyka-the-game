"""Nano Banana Pro service for AI-driven card image generation.

This service orchestrates the complete card generation pipeline:
- Fetches user messages and photos
- Generates card blueprint via CardArchitectService
- Generates final card image via ArtForgeService with multimodal inputs
"""

import random
from pathlib import Path
from typing import Optional

from aiogram import Bot
from sqlalchemy import func, select

from config import settings
from database.enums import BiomeType, Rarity
from database.models import MessageLog
from database.session import get_session
from logging_config import get_logger
from services.art_forge import ArtForgeService, UNIFORM_STYLE_GUIDE
from services.card_architect import CardArchitectService, CardBlueprint

logger = get_logger(__name__)


class NanoBananaService(ArtForgeService):
    """
    Service for AI-driven card image generation using Gemini 3 Pro Image (Nano Banana Pro).

    Orchestrates the complete pipeline: data gathering, blueprint generation, and image creation.
    """

    def __init__(self, gemini_api_key: str | None = None, cards_dir: str = "media/cards/"):
        """
        Initialize NanoBananaService.

        Args:
            gemini_api_key: Google Gemini API key for image generation.
                           If None, uses settings.gemini_api_key.
            cards_dir: Directory path for storing generated card images.
        """
        super().__init__(gemini_api_key, cards_dir)
        self._card_architect = CardArchitectService()
        self._placeholders_dir = Path("assets/placeholders")
        logger.info("NanoBananaService initialized (AI-driven card generation)")

    async def _fetch_user_messages(
        self, user_id: int, limit: int = 200, min_length: int = 20
    ) -> list[str]:
        """
        Fetch random messages from MessageLog for a user.

        Args:
            user_id: Telegram user ID.
            limit: Maximum number of messages to fetch.
            min_length: Minimum message length in characters.

        Returns:
            List of message content strings.
        """
        async for session in get_session():
            try:
                # Get all messages for user that meet length requirement
                stmt = (
                    select(MessageLog.content)
                    .where(MessageLog.user_id == user_id)
                    .where(func.length(MessageLog.content) >= min_length)
                )
                result = await session.execute(stmt)
                all_messages = [row[0] for row in result.all()]

                # Randomly sample up to limit
                if len(all_messages) > limit:
                    messages = random.sample(all_messages, limit)
                else:
                    messages = all_messages

                logger.debug(
                    "Fetched user messages",
                    user_id=user_id,
                    total_available=len(all_messages),
                    sampled_count=len(messages),
                )
                return messages
            except Exception as e:
                logger.error(
                    "Error fetching user messages",
                    user_id=user_id,
                    error=str(e),
                    exc_info=True,
                )
                return []
            # Exit the async for loop after first iteration
            break

    async def _fetch_user_profile_photo(self, bot: Bot, user_id: int) -> Optional[bytes]:
        """
        Fetch user profile photo via Telegram Bot API.

        Args:
            bot: Bot instance.
            user_id: Telegram user ID.

        Returns:
            Photo bytes if available, None otherwise.
        """
        try:
            profile_photos = await bot.get_user_profile_photos(user_id=user_id, limit=1)
            
            if not profile_photos.photos:
                logger.debug("No profile photos found for user", user_id=user_id)
                return None

            # Get largest photo from most recent set
            photo_sizes = profile_photos.photos[0]
            largest_photo = photo_sizes[-1]

            # Download the file
            photo_file = await bot.get_file(largest_photo.file_id)
            photo_bytes = await bot.download_file(photo_file.file_path)

            logger.debug("Fetched user profile photo", user_id=user_id)
            return photo_bytes.read()
        except Exception as e:
            logger.warning(
                "Could not retrieve user profile photo",
                user_id=user_id,
                error=str(e),
            )
            return None

    async def _fetch_group_chat_photo(self, bot: Bot, chat_id: int) -> Optional[bytes]:
        """
        Fetch group chat photo via Telegram Bot API.

        Args:
            bot: Bot instance.
            chat_id: Telegram chat ID.

        Returns:
            Photo bytes if available, None otherwise.
        """
        try:
            chat = await bot.get_chat(chat_id)
            
            if not chat.photo:
                logger.debug("No photo found for group chat", chat_id=chat_id)
                return None

            # Get largest photo
            photo_file = await bot.get_file(chat.photo.big_file_id)
            photo_bytes = await bot.download_file(photo_file.file_path)

            logger.debug("Fetched group chat photo", chat_id=chat_id)
            return photo_bytes.read()
        except Exception as e:
            logger.warning(
                "Could not retrieve group chat photo",
                chat_id=chat_id,
                error=str(e),
            )
            return None

    def _get_placeholder_path(self, biome: BiomeType, rarity: Rarity) -> Optional[str]:
        """
        Get path to placeholder image for biome/rarity combination.

        Args:
            biome: Biome type.
            rarity: Rarity level.

        Returns:
            Path to placeholder file if exists, None otherwise.
        """
        placeholder_path = self._placeholders_dir / f"{biome.name}_{rarity.name}.png"
        
        if placeholder_path.exists():
            return str(placeholder_path)
        
        logger.warning(
            "Placeholder not found",
            biome=biome.name,
            rarity=rarity.name,
            path=str(placeholder_path),
        )
        return None

    async def generate_card_for_user(
        self,
        user_id: int,
        chat_id: int,
        bot: Bot,
        user_name: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[CardBlueprint]]:
        """
        Generate a complete card for a user using AI-driven pipeline.

        Args:
            user_id: Telegram user ID.
            chat_id: Telegram chat ID (for group photo).
            bot: Bot instance for API calls.
            user_name: Optional user name/username for persona-based generation.

        Returns:
            Tuple of (image_path, blueprint) if successful, (None, None) otherwise.
        """
        try:
            logger.info("Starting card generation pipeline", user_id=user_id, chat_id=chat_id)

            # Step 1: Data Gathering
            logger.debug("Step 1: Gathering user data")
            messages = await self._fetch_user_messages(user_id, limit=200, min_length=20)
            user_photo = await self._fetch_user_profile_photo(bot, user_id)
            group_photo = await self._fetch_group_chat_photo(bot, chat_id)

            if not messages:
                logger.warning("No messages found for user", user_id=user_id)
                return None, None

            logger.info(
                "Data gathering complete",
                user_id=user_id,
                message_count=len(messages),
                has_user_photo=user_photo is not None,
                has_group_photo=group_photo is not None,
            )

            # Step 2: Architect - Generate Blueprint
            logger.debug("Step 2: Generating card blueprint")
            blueprint = await self._card_architect.generate_blueprint(
                messages, target_user_id=user_id, user_name=user_name
            )

            if not blueprint:
                logger.error("Failed to generate blueprint", user_id=user_id)
                return None, None

            logger.info(
                "Blueprint generated",
                user_id=user_id,
                card_name=blueprint.name,
                biome=blueprint.biome.value,
                rarity=blueprint.rarity.value,
            )

            # Step 3: Art Forge - Generate Image with Multimodal Inputs
            logger.debug("Step 3: Generating card image")
            placeholder_path = self._get_placeholder_path(blueprint.biome, blueprint.rarity)

            image_path = await self.forge_card_image(
                blueprint_prompt=blueprint.raw_image_prompt_en,
                biome=blueprint.biome,
                rarity=blueprint.rarity,
                placeholder_path=placeholder_path,
                user_photo_bytes=user_photo,
                group_photo_bytes=group_photo,
            )

            if not image_path:
                logger.error("Failed to generate card image", user_id=user_id)
                return None, None

            logger.info(
                "Card generation complete",
                user_id=user_id,
                image_path=image_path,
                card_name=blueprint.name,
            )

            return image_path, blueprint

        except Exception as e:
            logger.error(
                "Error in card generation pipeline",
                user_id=user_id,
                error=str(e),
                exc_info=True,
            )
            return None, None

    async def generate_from_prompt(
        self, user_prompt: str, biome: BiomeType
    ) -> str:
        """
        Generate card image from user-provided prompt and biome (legacy method).

        Args:
            user_prompt: User's art description prompt.
            biome: Biome type for theme styling.

        Returns:
            Relative filepath to the saved image (e.g., "media/cards/{uuid}.png").

        Raises:
            RuntimeError: If image generation fails after all retries.
        """
        # Use the same style guide as ArtForgeService for consistency
        full_prompt = (
            f"{UNIFORM_STYLE_GUIDE} Subject: {user_prompt}. "
            f"Biome theme: {biome.value}."
        )

        logger.debug(
            "Generating manual card image",
            prompt_length=len(full_prompt),
            biome=biome.value,
        )

        # Use parent's forge_card_image method which handles retries and saving
        return await self.forge_card_image(user_prompt, biome)
