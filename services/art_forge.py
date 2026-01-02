"""Art Forge service for generating card images using Google Generative AI."""

import asyncio
from pathlib import Path

from google import genai
from google.genai import types

from config import settings
from database.enums import BiomeType, Rarity
from logging_config import get_logger
from services.card_animator import CardAnimator
from utils.images import save_generated_image

logger = get_logger(__name__)

UNIFORM_STYLE_GUIDE = (
    "Pokemon Trading Card Game style illustration, vibrant and colorful art style, "
    "clean trading card aesthetic, digital painting, masterpiece, highly detailed, "
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
        self._animator = CardAnimator()

        logger.info(
            "ArtForgeService initialized",
            cards_dir=str(self._cards_dir),
            model=self._model_id,
        )

    async def forge_card_image(
        self,
        blueprint_prompt: str,
        biome: BiomeType,
        rarity: Rarity | None = None,
        placeholder_path: str | None = None,
        user_photo_bytes: bytes | None = None,
        group_photo_bytes: bytes | None = None,
    ) -> str:
        """
        Generate a card image from a blueprint prompt and biome.

        Args:
            blueprint_prompt: User's description of the card subject.
            biome: Biome type for theme styling.
            placeholder_path: Optional path to placeholder frame image.
            user_photo_bytes: Optional user profile photo bytes.
            group_photo_bytes: Optional group chat photo bytes.

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
            has_placeholder=placeholder_path is not None,
            has_user_photo=user_photo_bytes is not None,
            has_group_photo=group_photo_bytes is not None,
        )

        # Exponential backoff retry logic
        max_retries = 5
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                # Generate image using Google Generative AI
                response = await asyncio.to_thread(
                    self._generate_image_sync,
                    full_prompt,
                    placeholder_path,
                    user_photo_bytes,
                    group_photo_bytes,
                )

                if not response:
                    raise ValueError("No image data received from API")

                # Save image using utility function
                relative_path = save_generated_image(response, str(self._cards_dir))
                
                # Get absolute path for animation generation
                if Path(relative_path).is_absolute():
                    image_path = Path(relative_path)
                else:
                    image_path = self._cards_dir / Path(relative_path).name

                logger.info(
                    "Card image generated successfully",
                    filepath=relative_path,
                    biome=biome.value,
                )

                # Auto-generate animation for rare cards
                if rarity and rarity in (Rarity.EPIC, Rarity.LEGENDARY, Rarity.MYTHIC):
                    try:
                        # Generate animation in background (non-blocking)
                        animated_path = await asyncio.to_thread(
                            self._animator.generate_card_animation,
                            image_path,
                            rarity,
                        )

                        if animated_path:
                            logger.info(
                                "Card animation generated",
                                animated_path=str(animated_path),
                                rarity=rarity.value,
                            )
                    except Exception as e:
                        # Don't fail card generation if animation fails
                        logger.warning(
                            "Failed to generate animation (non-critical)",
                            image_path=str(image_path),
                            rarity=rarity.value,
                            error=str(e),
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

    def _generate_image_sync(
        self,
        prompt: str,
        placeholder_path: str | None = None,
        user_photo_bytes: bytes | None = None,
        group_photo_bytes: bytes | None = None,
    ) -> bytes:
        """
        Synchronous wrapper for image generation using Gemini 3 Pro Image.

        Args:
            prompt: Full prompt for image generation.
            placeholder_path: Optional path to placeholder frame image.
            user_photo_bytes: Optional user profile photo bytes.
            group_photo_bytes: Optional group chat photo bytes.

        Returns:
            Image binary data.

        Raises:
            RuntimeError: If image generation fails.
        """
        try:
            # Build multimodal content array
            contents = []
            
            # Add text prompt
            contents.append(prompt)
            
            # Add placeholder image if provided
            if placeholder_path:
                try:
                    from pathlib import Path
                    import base64
                    
                    placeholder_file = Path(placeholder_path)
                    if placeholder_file.exists():
                        placeholder_data = placeholder_file.read_bytes()
                        # Convert to base64 for inline data
                        placeholder_b64 = base64.b64encode(placeholder_data).decode('utf-8')
                        contents.append(
                            types.Part(
                                inline_data=types.Blob(
                                    data=placeholder_b64,
                                    mime_type="image/png"
                                )
                            )
                        )
                        logger.debug("Added placeholder image to multimodal request")
                except Exception as e:
                    logger.warning("Failed to load placeholder image", error=str(e))
            
            # Add user photo if provided
            if user_photo_bytes:
                try:
                    import base64
                    user_photo_b64 = base64.b64encode(user_photo_bytes).decode('utf-8')
                    contents.append(
                        types.Part(
                            inline_data=types.Blob(
                                data=user_photo_b64,
                                mime_type="image/jpeg"  # Telegram profile photos are typically JPEG
                            )
                        )
                    )
                    logger.debug("Added user photo to multimodal request")
                except Exception as e:
                    logger.warning("Failed to add user photo", error=str(e))
            
            # Add group photo if provided
            if group_photo_bytes:
                try:
                    import base64
                    group_photo_b64 = base64.b64encode(group_photo_bytes).decode('utf-8')
                    contents.append(
                        types.Part(
                            inline_data=types.Blob(
                                data=group_photo_b64,
                                mime_type="image/jpeg"
                            )
                        )
                    )
                    logger.debug("Added group photo to multimodal request")
                except Exception as e:
                    logger.warning("Failed to add group photo", error=str(e))
            
            # Enhance prompt if images are provided
            if placeholder_path or user_photo_bytes or group_photo_bytes:
                enhanced_prompt = (
                    f"{prompt}\n\n"
                    "IMPORTANT INSTRUCTIONS FOR IMAGE GENERATION:\n"
                )
                if placeholder_path:
                    enhanced_prompt += (
                        "- Use the provided placeholder frame as the base structure for the card. "
                        "Generate the card illustration to fit within this frame.\n"
                    )
                if user_photo_bytes:
                    enhanced_prompt += (
                        "- Integrate the user's profile photo style and colors into the card design. "
                        "Use the photo as inspiration for the character/illustration, adapting it to match the card's theme.\n"
                    )
                if group_photo_bytes:
                    enhanced_prompt += (
                        "- Incorporate elements from the group chat photo to add context and atmosphere to the card design.\n"
                    )
                enhanced_prompt += (
                    "- Generate a complete trading card image with the illustration, text, and all card elements "
                    "integrated into a cohesive design. The final output should be a ready-to-use card image."
                )
                # Replace first element (text prompt) with enhanced version
                contents[0] = enhanced_prompt
            
            response = self._client.models.generate_content(
                model=self._model_id,
                contents=contents,
                config=types.GenerateContentConfig(
                    # Image configuration for gemini-3-pro-image-preview
                    # See: https://ai.google.dev/gemini-api/docs/image-generation
                    imageConfig=types.ImageConfig(
                        aspectRatio="3:4",  # Portrait orientation for trading cards
                        imageSize="2K",     # 1792x2400 resolution for 3:4 aspect ratio
                    ),
                    # Safety settings: Allow mild vulgar/meme content but block extreme NSFW
                    # BLOCK_ONLY_HIGH allows suggestive/meme content while blocking explicit material
                    safety_settings=[
                        types.SafetySetting(
                            category="HARM_CATEGORY_HATE_SPEECH",
                            threshold="BLOCK_ONLY_HIGH"
                        ),
                        types.SafetySetting(
                            category="HARM_CATEGORY_HARASSMENT",
                            threshold="BLOCK_ONLY_HIGH"
                        ),
                        types.SafetySetting(
                            category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                            threshold="BLOCK_ONLY_HIGH"
                        ),
                        types.SafetySetting(
                            category="HARM_CATEGORY_DANGEROUS_CONTENT",
                            threshold="BLOCK_ONLY_HIGH"
                        )
                    ]
                )
            )

            # In SDK 1.56, image data is consistently here:
            if not response.candidates:
                raise ValueError("No candidates in API response")

            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    data = part.inline_data.data
                    # Handle base64 encoded data if needed
                    if isinstance(data, str):
                        import base64
                        return base64.b64decode(data)
                    return data

            raise ValueError("No image data in response")

        except Exception as e:
            logger.error(f"Art Forge failed: {e}")
            raise
