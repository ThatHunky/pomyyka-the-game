"""Regenerate all card animations with improved encoding."""

import asyncio
from pathlib import Path

from database.enums import Rarity
from database.models import CardTemplate
from database.session import get_session
from logging_config import get_logger
from services.card_animator import CardAnimator
from sqlalchemy import select

logger = get_logger(__name__)


async def regenerate_all_animations():
    """Regenerate all card animations with improved MP4 encoding."""
    
    animator = CardAnimator()
    
    # Find all card images in media/cards directory
    media_dir = Path("media/cards")
    if not media_dir.exists():
        logger.error("Media directory not found", path=str(media_dir))
        return
    
    # Find all PNG files (base card images)
    card_images = list(media_dir.glob("*.png"))
    
    logger.info(f"Found {len(card_images)} card images to process")
    
    regenerated = 0
    skipped = 0
    errors = 0
    
    for image_path in card_images:
        # Skip if it's already an animated file
        if "_animated" in image_path.stem:
            continue
        
        try:
            # Try to determine rarity from database or filename
            # For now, we'll check if an animated version already exists
            animated_mp4_path = image_path.parent / f"{image_path.stem}_animated.mp4"
            animated_gif_path = image_path.parent / f"{image_path.stem}_animated.gif"
            
            # If neither animated version exists, skip (not a rare card)
            if not animated_mp4_path.exists() and not animated_gif_path.exists():
                logger.debug(f"No animation for {image_path.name}, skipping")
                skipped += 1
                continue
            
            # Delete old MP4 if it exists
            if animated_mp4_path.exists():
                logger.info(f"Deleting old animation: {animated_mp4_path.name}")
                animated_mp4_path.unlink()
            
            # Assume Epic rarity for regeneration (will work for all rare cards)
            # The animation effects are the same, just different intensities
            logger.info(f"Regenerating animation for {image_path.name}")
            
            # Try each rarity level to see which one works
            for rarity in [Rarity.MYTHIC, Rarity.LEGENDARY, Rarity.EPIC]:
                try:
                    new_animation = animator.generate_card_animation(
                        image_path=image_path,
                        rarity=rarity,
                        total_frames=100,
                        duration=50,
                    )
                    
                    if new_animation:
                        logger.info(
                            f"Successfully regenerated animation",
                            image=image_path.name,
                            rarity=rarity.value,
                            output=new_animation.name,
                        )
                        regenerated += 1
                        break
                except Exception as e:
                    logger.warning(
                        f"Failed to regenerate with rarity {rarity.value}",
                        image=image_path.name,
                        error=str(e),
                    )
                    continue
            else:
                # If all rarities failed
                logger.error(f"Failed to regenerate animation for {image_path.name}")
                errors += 1
                
        except Exception as e:
            logger.error(
                f"Error processing {image_path.name}",
                error=str(e),
                exc_info=True,
            )
            errors += 1
    
    logger.info(
        "Animation regeneration complete",
        regenerated=regenerated,
        skipped=skipped,
        errors=errors,
        total=len(card_images),
    )


if __name__ == "__main__":
    asyncio.run(regenerate_all_animations())
