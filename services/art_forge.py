"""Art Forge service for generating card images using Google Generative AI."""

import asyncio
from pathlib import Path

from google import genai
from google.genai import types

from config import settings
from database.enums import BiomeType
from logging_config import get_logger
from utils.images import save_generated_image

logger = get_logger(__name__)

UNIFORM_STYLE_GUIDE = (
    "Trading card illustration, cohesive high fantasy cyberpunk fusion art style, "
    "ornate border design elements, digital painting, masterpiece, highly detailed, "
    "8k resolution, cinematic lighting, rich textures."
)


class ArtForgeService:
    """Service for generating card images using Google Generative AI (Gemini 3 Pro Image)."""

    def __init__(self, gemini_api_key: str | None = None, cards_dir: str = "media/cards/"):
        """
        Initialize ArtForgeService.

        Args:
            gemini_api_key: Google Gemini API key for image generation.
                           If None, uses settings.gemini_api_key.
            cards_dir: Directory path for storing generated card images.
        """
        api_key = gemini_api_key or settings.gemini_api_key
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required")

        self._api_key = api_key
        self._cards_dir = Path(cards_dir)
        self._cards_dir.mkdir(parents=True, exist_ok=True)
        self._client = genai.Client(api_key=self._api_key)
        self._model_id = settings.image_model_id

        logger.info(
            "ArtForgeService initialized",
            cards_dir=str(self._cards_dir),
            model=self._model_id,
        )

    async def forge_card_image(
        self, blueprint_prompt: str, biome: BiomeType
    ) -> str:
        """
        Generate a card image from a blueprint prompt and biome.

        Args:
            blueprint_prompt: User's description of the card subject.
            biome: Biome type for theme styling.

        Returns:
            Relative filepath to the saved image (e.g., "media/cards/{uuid}.png").

        Raises:
            RuntimeError: If image generation fails after all retries.
        """
        # Combine prompts
        full_prompt = (
            f"{UNIFORM_STYLE_GUIDE} Subject: {blueprint_prompt}. "
            f"Biome theme: {biome.value}."
        )

        logger.debug(
            "Generating card image",
            prompt_length=len(full_prompt),
            biome=biome.value,
        )

        # Exponential backoff retry logic
        max_retries = 5
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                # Generate image using Google Generative AI
                response = await asyncio.to_thread(
                    self._generate_image_sync, full_prompt
                )

                if not response:
                    raise ValueError("No image data received from API")

                # Save image using utility function
                relative_path = save_generated_image(response, str(self._cards_dir))

                logger.info(
                    "Card image generated successfully",
                    filepath=relative_path,
                    biome=biome.value,
                )

                return relative_path

            except Exception as e:
                # Check if it's a Google API rate limit exception
                error_msg = str(e)
                is_rate_limit = any(
                    keyword in error_msg.lower()
                    for keyword in ["rate limit", "quota", "429", "too many requests", "resource exhausted"]
                )

                if attempt < max_retries - 1:
                    if is_rate_limit:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            "Rate limit detected, retrying with exponential backoff",
                            attempt=attempt + 1,
                            max_retries=max_retries,
                            delay_seconds=delay,
                            error=error_msg,
                        )
                        await asyncio.sleep(delay)
                    else:
                        # For non-rate-limit errors, use shorter delays
                        delay = base_delay * (1.5 ** attempt)
                        logger.warning(
                            "Image generation failed, retrying",
                            attempt=attempt + 1,
                            max_retries=max_retries,
                            delay_seconds=delay,
                            error=error_msg,
                        )
                        await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Image generation failed after all retries",
                        error=error_msg,
                        exc_info=True,
                    )
                    raise RuntimeError(
                        f"Failed to generate image after {max_retries} attempts: {error_msg}"
                    ) from e

    def _generate_image_sync(self, prompt: str) -> bytes:
        """
        Synchronous wrapper for image generation using Gemini 3 Pro Image.

        Args:
            prompt: Full prompt for image generation.

        Returns:
            Image binary data.

        Raises:
            RuntimeError: If image generation fails.
        """
        try:
            response = self._client.models.generate_content(
                model=self._model_id,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    safety_settings=[
                        types.SafetySetting(
                            category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                            threshold="BLOCK_ONLY_HIGH"
                        )
                    ]
                )
            )

            # Extract image from response
            # Structure: response.candidates[0].content.parts[0].inline_data.data
            if not response.candidates:
                raise ValueError("No candidates in API response")

            candidate = response.candidates[0]
            if not hasattr(candidate, "content") or not candidate.content:
                raise ValueError("No content in candidate")

            if not hasattr(candidate.content, "parts") or not candidate.content.parts:
                raise ValueError("No parts in content")

            for part in candidate.content.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    if hasattr(part.inline_data, "data"):
                        data = part.inline_data.data
                        # Handle base64 encoded data if needed
                        if isinstance(data, str):
                            import base64
                            return base64.b64decode(data)
                        return data

            raise ValueError("Could not extract image data from API response")

        except Exception as e:
            # Re-raise with context for better error handling
            raise RuntimeError(f"Image generation API call failed: {str(e)}") from e
