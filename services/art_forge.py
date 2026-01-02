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
        card_fields: dict | None = None,
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
            Relative filepath to the saved image (e.g., "media/cards/{uuid}.webp").

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
            has_card_fields=card_fields is not None,
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
                    card_fields,
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
        card_fields: dict | None = None,
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
            # Helper function to detect image format and validate
            def detect_image_format(image_bytes: bytes) -> tuple[str | None, bool]:
                """
                Detect image format from bytes and validate.
                
                Returns:
                    Tuple of (mime_type, is_valid)
                """
                if not image_bytes or len(image_bytes) < 10:
                    return None, False
                
                # Check file signature (magic bytes)
                if image_bytes[:2] == b'\xff\xd8':
                    return "image/jpeg", True
                elif image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
                    return "image/png", True
                elif image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
                    return "image/webp", True
                elif image_bytes[:6] in (b'GIF87a', b'GIF89a'):
                    return "image/gif", True
                
                # Format not recognized
                return None, False
            
            # Build content array with multimodal inputs (text + images)
            import base64
            contents = []
            
            # Add placeholder image if provided
            if placeholder_path and Path(placeholder_path).exists():
                try:
                    with open(placeholder_path, 'rb') as f:
                        placeholder_bytes = f.read()
                        mime_type, is_valid = detect_image_format(placeholder_bytes)
                        if is_valid and mime_type:
                            contents.append({
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": base64.b64encode(placeholder_bytes).decode('utf-8')
                                }
                            })
                            logger.debug("Added placeholder image to generation context")
                except Exception as e:
                    logger.warning(
                        "Could not load placeholder image",
                        placeholder_path=placeholder_path,
                        error=str(e),
                    )
            
            # Add user photo if provided
            if user_photo_bytes:
                mime_type, is_valid = detect_image_format(user_photo_bytes)
                if is_valid and mime_type:
                    contents.append({
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(user_photo_bytes).decode('utf-8')
                        }
                    })
                    logger.debug("Added user photo to generation context")
            
            # Add group photo if provided
            if group_photo_bytes:
                mime_type, is_valid = detect_image_format(group_photo_bytes)
                if is_valid and mime_type:
                    contents.append({
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(group_photo_bytes).decode('utf-8')
                        }
                    })
                    logger.debug("Added group photo to generation context")
            
            # Enhance prompt with instructions for image generation
            enhanced_prompt = prompt
            if placeholder_path or user_photo_bytes or group_photo_bytes:
                enhanced_prompt = (
                    f"{prompt}\n\n"
                    "IMPORTANT INSTRUCTIONS FOR IMAGE GENERATION:\n"
                )
                enhanced_prompt += (
                    "- ALL visible text on the final card must be in Ukrainian. "
                    "This includes the card name, attacks, descriptions, UI labels, and rarity label. "
                    "DO NOT output English text.\n"
                    "- Use Ukrainian rarity words: "
                    "ЗВИЧАЙНА (Common), РІДКІСНА (Rare), ЕПІЧНА (Epic), ЛЕГЕНДАРНА (Legendary), МІФІЧНА (Mythic).\n"
                    "- If the template includes placeholders, replace them with Ukrainian text.\n"
                )
                if placeholder_path:
                    # Extract biome/rarity from placeholder filename for context
                    placeholder_name = Path(placeholder_path).stem
                    enhanced_prompt += (
                        f"- Use the provided placeholder/template image as the base structure for the card. "
                        f"This is a {placeholder_name} style frame. Generate the card illustration to fit within this trading card frame, "
                        "maintaining the frame's style and structure while filling it with the card's content.\n"
                    )
                if user_photo_bytes:
                    enhanced_prompt += (
                        "- Use the provided user photo as reference for the card's character/illustration. "
                        "Integrate the photo's style, colors, and visual elements into the card design, "
                        "adapting it to match the card's theme and biome while preserving key characteristics.\n"
                    )
                if group_photo_bytes:
                    enhanced_prompt += (
                        "- Incorporate elements from the provided group chat photo to add context and atmosphere to the card design.\n"
                    )

                if card_fields:
                    # Build a strict block of values for the model to render onto the template.
                    # This fixes the issue where the image model had no access to generated text fields,
                    # so placeholders like "НАЗВА КАРТКИ" remained unchanged.
                    def _get(key: str, fallback: str | None = None) -> str | None:
                        val = card_fields.get(key, fallback)
                        if val is None:
                            return None
                        return str(val)

                    # Support both internal blueprint dict shape and a more explicit one.
                    name_ua = _get("name") or _get("card_name_ua") or _get("name_ua")
                    biome_ua = _get("biome") or _get("biome_ua")
                    rarity_en = _get("rarity") or _get("rarity_en")
                    atk = _get("atk") or _get("stats_atk")
                    defense = _get("def") or _get("stats_def")
                    meme = _get("meme") or _get("stats_meme")
                    lore_ua = _get("lore") or _get("lore_ua")
                    print_date = _get("print_date")
                    attacks = card_fields.get("attacks")
                    weakness = card_fields.get("weakness")
                    resistance = card_fields.get("resistance")

                    # Emoji helpers (keep local to avoid cross-module imports).
                    biome_emoji_map = {
                        "Звичайний": "🌍",
                        "Вогняний": "🔥",
                        "Водний": "💧",
                        "Трав'яний": "🌿",
                        "Психічний": "🔮",
                        "Техно": "⚙️",
                        "Темний": "🌑",
                    }
                    rarity_emoji_map = {
                        "Common": "⚪",
                        "Rare": "🔵",
                        "Epic": "🟣",
                        "Legendary": "🟠",
                        "Mythic": "🔴",
                    }
                    biome_emoji = biome_emoji_map.get(biome_ua or "", "🌍")
                    rarity_emoji = rarity_emoji_map.get(rarity_en or "", "⚪")

                    rarity_ua_map = {
                        "Common": "Звичайна",
                        "Rare": "Рідкісна",
                        "Epic": "Епічна",
                        "Legendary": "Легендарна",
                        "Mythic": "Міфічна",
                    }
                    rarity_ua = rarity_ua_map.get(rarity_en or "", None)

                    enhanced_prompt += (
                        "\n\nCARD_FIELDS_TO_RENDER (CRITICAL):\n"
                        "- Replace ALL placeholder text on the template (e.g., 'НАЗВА КАРТКИ', example attacks, default stats, lorem text) "
                        "with the EXACT values below.\n"
                        "- Do NOT invent or translate new text. Use EXACT spelling/case/punctuation from the values.\n"
                        "- Keep the template layout; only update the text content.\n"
                        "- Ensure the rendered text is readable and fits into the designated text boxes.\n"
                    )

                    if name_ua:
                        enhanced_prompt += f"- Card name (UA): {name_ua}\n"
                    if biome_ua:
                        enhanced_prompt += f"- Biome label: {biome_emoji} {biome_ua}\n"
                    if rarity_ua:
                        enhanced_prompt += f"- Rarity badge (UA): {rarity_emoji} {rarity_ua.upper()}\n"
                    if atk is not None:
                        enhanced_prompt += f"- ⚔️ ATK: {atk}\n"
                    if meme is not None:
                        enhanced_prompt += f"- 🎭 MEME: {meme}\n"
                    if defense is not None:
                        enhanced_prompt += f"- 🛡️ DEF: {defense}\n"
                    if print_date:
                        enhanced_prompt += f"- Print date (MM/YYYY): {print_date}\n"
                    if lore_ua:
                        enhanced_prompt += f"- Lore (UA): {lore_ua}\n"

                    # Attacks
                    if isinstance(attacks, list) and attacks:
                        enhanced_prompt += "- Attacks:\n"
                        for idx, atk_obj in enumerate(attacks[:2], start=1):
                            if not isinstance(atk_obj, dict):
                                continue
                            a_name = str(atk_obj.get("name", "")).strip()
                            a_type = str(atk_obj.get("type", "")).strip()
                            a_dmg = atk_obj.get("damage")
                            a_cost = atk_obj.get("energy_cost")
                            a_effect = str(atk_obj.get("effect", "")).strip()
                            a_status = str(atk_obj.get("status_effect", "")).strip()
                            enhanced_prompt += f"  - Attack {idx} name: {a_name}\n"
                            if a_type:
                                enhanced_prompt += f"    - type: {a_type}\n"
                            if a_cost is not None:
                                enhanced_prompt += f"    - energy_cost: {a_cost}\n"
                            if a_dmg is not None:
                                enhanced_prompt += f"    - damage: {a_dmg}\n"
                            if a_effect:
                                enhanced_prompt += f"    - effect: {a_effect}\n"
                            if a_status:
                                enhanced_prompt += f"    - status_effect: {a_status}\n"

                    # Weakness / resistance
                    if isinstance(weakness, dict) and weakness:
                        w_type = weakness.get("type")
                        w_mult = weakness.get("multiplier")
                        enhanced_prompt += f"- Weakness: {w_type} x{w_mult}\n"
                    if isinstance(resistance, dict) and resistance:
                        r_type = resistance.get("type")
                        r_red = resistance.get("reduction")
                        enhanced_prompt += f"- Resistance: {r_type} -{r_red}\n"

                enhanced_prompt += (
                    "\n- Generate a complete trading card image with the illustration, text, and all card elements "
                    "integrated into a cohesive design. The final output should be a ready-to-use card image that "
                    "combines the reference images provided above with the card's design requirements."
                )
            
            # Add text prompt as the final content item
            contents.append(enhanced_prompt)
            
            # Log multimodal input usage
            if user_photo_bytes or group_photo_bytes or placeholder_path:
                logger.debug(
                    "Using multimodal input mode (sending images as input)",
                    has_placeholder=placeholder_path is not None,
                    has_user_photo=user_photo_bytes is not None,
                    has_group_photo=group_photo_bytes is not None,
                )
            
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
