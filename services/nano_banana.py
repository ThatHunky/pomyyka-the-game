"""Nano Banana Pro service for manual card image generation.

This service shares the same underlying logic as ArtForgeService to maintain
style consistency between automatic and manual card generation.
"""

from config import settings
from database.enums import BiomeType
from logging_config import get_logger
from services.art_forge import ArtForgeService, UNIFORM_STYLE_GUIDE

logger = get_logger(__name__)


class NanoBananaService(ArtForgeService):
    """
    Service for manual card image generation using Gemini 3 Pro Image (Nano Banana Pro).

    Inherits from ArtForgeService to maintain style consistency.
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
        logger.info("NanoBananaService initialized (manual image generation)")

    async def generate_from_prompt(
        self, user_prompt: str, biome: BiomeType
    ) -> str:
        """
        Generate card image from user-provided prompt and biome.

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
