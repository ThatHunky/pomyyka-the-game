"""Card Architect Service for generating card blueprints from user messages."""

from dataclasses import dataclass
from typing import Optional

from config import settings
from database.enums import BiomeType, Rarity
from logging_config import get_logger

logger = get_logger(__name__)

# Try to use the existing AI architect service if available
try:
    from services.ai_architect import CardArchitectService as AICardArchitectService

    _HAS_AI_SERVICE = True
except ImportError:
    _HAS_AI_SERVICE = False


@dataclass
class CardBlueprint:
    """Blueprint for a card generated from user messages."""

    name: str
    raw_image_prompt_en: str
    biome: BiomeType
    rarity: Rarity
    stats: dict[str, int]  # {"atk": int, "def": int}
    lore: str


class CardArchitectService:
    """Service for generating card blueprints from user message logs."""

    def __init__(self):
        """Initialize the Card Architect Service."""
        self._ai_service: Optional[AICardArchitectService] = None
        if _HAS_AI_SERVICE and settings.gemini_api_key:
            try:
                self._ai_service = AICardArchitectService(settings.gemini_api_key)
            except Exception as e:
                logger.warning("Failed to initialize AI architect service", error=str(e))

    async def generate_blueprint(
        self, 
        message_logs: list[str], 
        target_user_id: Optional[int] = None,
        user_name: Optional[str] = None
    ) -> Optional[CardBlueprint]:
        """
        Generate a card blueprint from user message logs.

        Args:
            message_logs: List of message content strings from the user.
            target_user_id: Optional target user ID to include in context.
            user_name: Optional user name/username to include in context for persona-based naming.

        Returns:
            CardBlueprint if generation successful, None otherwise.
        """
        if not self._ai_service:
            logger.warning("Gemini API key not configured, cannot generate blueprint")
            return None

        try:
            # Format messages for better AI context understanding
            # Create a structured context that shows conversation flow
            if not message_logs:
                logger.warning("No message logs provided for blueprint generation")
                return None
            
            # Build enhanced context with user ID, name, and formatted messages
            enhanced_logs = []
            
            # Add user identity prominently at the top
            if user_name:
                # Remove @ prefix if present
                clean_name = user_name.lstrip("@")
                enhanced_logs.append(f"User Identity: {clean_name}")
                enhanced_logs.append("")
            
            if target_user_id is not None:
                enhanced_logs.append(f"Target User ID: {target_user_id}")
                enhanced_logs.append("")
            
            enhanced_logs.append("User Message History (chronological order):")
            enhanced_logs.append("=" * 50)
            
            # Add messages with numbering for better context
            for i, msg in enumerate(message_logs, 1):
                if msg and msg.strip():
                    enhanced_logs.append(f"{i}. {msg.strip()}")
            
            enhanced_logs.append("=" * 50)
            enhanced_logs.append("")
            
            # Add instruction emphasizing user name usage
            if user_name:
                clean_name = user_name.lstrip("@")
                enhanced_logs.append(
                    f"CRITICAL: The card name MUST be based on or incorporate the user's name/persona '{clean_name}'. "
                    f"The card should represent this specific user and reflect their identity. "
                    f"Generate a unique card blueprint that reflects this user's personality, interests, and communication style, "
                    f"with a card name that creatively incorporates or is inspired by their name '{clean_name}'."
                )
            else:
                enhanced_logs.append("Based on this conversation history, generate a unique card blueprint that reflects this user's personality, interests, and communication style.")
            
            # Log the context being sent (first 500 chars for debugging)
            context_preview = "\n".join(enhanced_logs)
            logger.debug(
                "Sending context to AI architect",
                target_user_id=target_user_id,
                user_name=user_name,
                message_count=len(message_logs),
                context_length=len(context_preview),
                context_preview=context_preview[:500],
            )

            # Use the existing AI architect service (synchronous, but we're in async context)
            # Run in executor to avoid blocking
            import asyncio

            loop = asyncio.get_event_loop()
            ai_blueprint = await loop.run_in_executor(
                None, self._ai_service.generate_blueprint, enhanced_logs
            )

            # Convert to our simpler CardBlueprint format
            blueprint = CardBlueprint(
                name=ai_blueprint.card_name_ua,
                raw_image_prompt_en=ai_blueprint.raw_image_prompt_en,
                biome=ai_blueprint.biome,
                rarity=ai_blueprint.rarity,
                stats={"atk": ai_blueprint.stats_atk, "def": ai_blueprint.stats_def},
                lore=ai_blueprint.lore_ua,
            )

            logger.info(
                "Card blueprint generated",
                name=blueprint.name,
                biome=blueprint.biome.value,
                rarity=blueprint.rarity.value,
            )

            return blueprint

        except Exception as e:
            logger.error("Error generating card blueprint", error=str(e), exc_info=True)
            return None

    async def generate_blueprint_from_prompt(
        self, detailed_prompt: str
    ) -> Optional[CardBlueprint]:
        """
        Generate a card blueprint from a detailed prompt (for common/reusable cards).

        Args:
            detailed_prompt: Detailed description of the card to create (e.g., "Шлюхобот - вульгарний мемний робот з техно біому, низька рідкість").

        Returns:
            CardBlueprint if generation successful, None otherwise.
        """
        if not self._ai_service:
            logger.warning("Gemini API key not configured, cannot generate blueprint")
            return None

        try:
            # Build context for AI - this is a reusable template card, not user-specific
            enhanced_prompt = [
                "Card Creation Request (Reusable Template):",
                "=" * 50,
                detailed_prompt,
                "=" * 50,
                "",
                "Generate a reusable card template blueprint based on this description.",
                "This card will be distributed to multiple users, so it should be a common/meme card or themed card.",
                "Choose appropriate rarity based on the description (Common for simple/meme cards, higher rarities for powerful/legendary concepts).",
                "The card name should be in Ukrainian, and the image prompt should be in English.",
                "",
                "IMPORTANT: Since this is a reusable template (not user-specific), set target_user_id to 0.",
            ]

            # Log the prompt being sent
            prompt_preview = "\n".join(enhanced_prompt)
            logger.debug(
                "Sending prompt to AI architect for common card",
                prompt_length=len(detailed_prompt),
                context_length=len(prompt_preview),
                prompt_preview=prompt_preview[:500],
            )

            # Use the existing AI architect service (synchronous, but we're in async context)
            # Run in executor to avoid blocking
            import asyncio

            loop = asyncio.get_event_loop()
            ai_blueprint = await loop.run_in_executor(
                None, self._ai_service.generate_blueprint, enhanced_prompt
            )

            # Convert to our simpler CardBlueprint format
            blueprint = CardBlueprint(
                name=ai_blueprint.card_name_ua,
                raw_image_prompt_en=ai_blueprint.raw_image_prompt_en,
                biome=ai_blueprint.biome,
                rarity=ai_blueprint.rarity,
                stats={"atk": ai_blueprint.stats_atk, "def": ai_blueprint.stats_def},
                lore=ai_blueprint.lore_ua,
            )

            logger.info(
                "Card blueprint generated from prompt",
                name=blueprint.name,
                biome=blueprint.biome.value,
                rarity=blueprint.rarity.value,
            )

            return blueprint

        except Exception as e:
            logger.error("Error generating card blueprint from prompt", error=str(e), exc_info=True)
            return None
