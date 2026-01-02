"""Utility functions for handling animations in Telegram."""

from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardMarkup, Message
from PIL import Image

from logging_config import get_logger

logger = get_logger(__name__)


async def send_card_animation(
    message: Message,
    animation_path: Path,
    caption: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = "Markdown",
) -> None:
    """
    Send card animation with proper parameters for Telegram compatibility.
    
    Args:
        message: Message to reply to
        animation_path: Path to animation file (MP4 or GIF)
        caption: Caption text
        reply_markup: Optional inline keyboard
        parse_mode: Parse mode for caption
    """
    try:
        animation_file = FSInputFile(str(animation_path))
        
        # Get video dimensions and duration
        width, height = None, None
        duration = 5  # Default 5 seconds (100 frames at 20fps)
        
        # Try to get dimensions from the file
        try:
            # For MP4, we need to infer from the base image (WebP format)
            # Look for the static image (same name without _animated suffix)
            base_image_path = animation_path.parent / animation_path.name.replace("_animated.mp4", ".webp")
            if not base_image_path.exists():
                base_image_path = animation_path.parent / animation_path.name.replace("_animated.gif", ".webp")
            
            if base_image_path.exists():
                with Image.open(base_image_path) as img:
                    width, height = img.size
            else:
                # Default to 1080p portrait dimensions if file not found
                width, height = 1080, 1920
                logger.debug(
                    "Using default 1080p portrait dimensions",
                    animation_path=str(animation_path),
                )
        except Exception as e:
            # Default to 1080p portrait dimensions on error
            width, height = 1080, 1920
            logger.warning(
                "Could not determine animation dimensions, using default 1080p",
                animation_path=str(animation_path),
                error=str(e),
            )
        
        # Send animation with proper parameters
        await message.answer_animation(
            animation=animation_file,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            duration=duration,
            width=width,
            height=height,
            # Explicitly mark as animation (not video)
            # Telegram should autoplay this
        )
        
        logger.debug(
            "Animation sent successfully",
            animation_path=str(animation_path),
            width=width,
            height=height,
            duration=duration,
        )
        
    except Exception as e:
        logger.error(
            "Error sending animation",
            animation_path=str(animation_path),
            error=str(e),
            exc_info=True,
        )
        raise


async def send_card_animation_to_callback(
    callback_message: Message,
    animation_path: Path,
    caption: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = "Markdown",
) -> None:
    """
    Send card animation in response to a callback query.
    
    Similar to send_card_animation but for callback queries.
    
    Args:
        callback_message: Callback message object
        animation_path: Path to animation file (MP4 or GIF)
        caption: Caption text
        reply_markup: Optional inline keyboard
        parse_mode: Parse mode for caption
    """
    await send_card_animation(
        callback_message,
        animation_path,
        caption,
        reply_markup,
        parse_mode,
    )
