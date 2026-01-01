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
        self, message_logs: list[str], target_user_id: Optional[int] = None
    ) -> Optional[CardBlueprint]:
        """
        Generate a card blueprint from user message logs.

        Args:
            message_logs: List of message content strings from the user.
            target_user_id: Optional target user ID to include in context.

        Returns:
            CardBlueprint if generation successful, None otherwise.
        """
        if not self._ai_service:
            logger.warning("Gemini API key not configured, cannot generate blueprint")
            return None

        try:
            # Add target_user_id to context if provided
            enhanced_logs = message_logs
            if target_user_id is not None:
                enhanced_logs = [
                    f"[Target User ID: {target_user_id}]",
                    *message_logs,
                ]

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
