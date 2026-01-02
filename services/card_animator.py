"""Card animation generation service with holographic and sparkle effects."""

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw

from database.enums import Rarity
from logging_config import get_logger

logger = get_logger(__name__)


class CardAnimator:
    """Service for generating animated GIFs from static card images."""

    def __init__(self):
        """Initialize CardAnimator."""
        logger.info("CardAnimator initialized")

    def generate_card_animation(
        self, image_path: Path, rarity: Rarity, total_frames: int = 8, duration: int = 100
    ) -> Path | None:
        """
        Generate animated MP4 from static card image.

        Args:
            image_path: Path to static card image
            rarity: Card rarity level
            total_frames: Number of frames in animation
            duration: Duration per frame in milliseconds

        Returns:
            Path to generated MP4 file, or None if generation failed
        """
        if rarity not in (Rarity.EPIC, Rarity.LEGENDARY, Rarity.MYTHIC):
            logger.debug("Skipping animation for non-rare card", rarity=rarity.value)
            return None

        try:
            # Open base image
            base_img = Image.open(image_path)
            if base_img.mode != 'RGBA':
                base_img = base_img.convert('RGBA')

            logger.debug(
                "Generating card animation",
                image_path=str(image_path),
                rarity=rarity.value,
                total_frames=total_frames,
            )

            # Generate frames based on rarity
            frames = []
            for i in range(total_frames):
                frame = base_img.copy()

                # Apply rarity-specific effects
                if rarity == Rarity.MYTHIC:
                    # Mythic: Full holographic + sparkles + border glow
                    frame = self._create_holographic_shimmer(frame, i, total_frames, intensity=0.6)
                    frame = self._create_sparkle_frame(frame, i, total_frames, count=15)
                    frame = self._create_border_glow(frame, i, total_frames, intensity=0.5)
                elif rarity == Rarity.LEGENDARY:
                    # Legendary: Holographic shimmer + sparkles
                    frame = self._create_holographic_shimmer(frame, i, total_frames, intensity=0.4)
                    frame = self._create_sparkle_frame(frame, i, total_frames, count=8)
                elif rarity == Rarity.EPIC:
                    # Epic: Subtle holographic shimmer only
                    frame = self._create_holographic_shimmer(frame, i, total_frames, intensity=0.25)

                frames.append(frame)

            # Save as temporary GIF first, then convert to MP4
            temp_gif_path = image_path.parent / f"{image_path.stem}_animated_temp.gif"
            frames[0].save(
                temp_gif_path,
                'GIF',
                save_all=True,
                append_images=frames[1:],
                duration=duration,
                loop=0,  # Loop infinitely
                optimize=False,  # Better quality
            )

            # Convert GIF to MP4 using ffmpeg
            mp4_path = image_path.parent / f"{image_path.stem}_animated.mp4"
            try:
                import subprocess
                cmd = [
                    'ffmpeg',
                    '-i', str(temp_gif_path),
                    '-movflags', 'faststart',
                    '-pix_fmt', 'yuv420p',
                    '-an',  # No audio
                    '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',  # Ensure even dimensions
                    '-y',  # Overwrite
                    str(mp4_path)
                ]
                subprocess.run(cmd, capture_output=True, check=True)
                
                # Clean up temporary GIF
                temp_gif_path.unlink()
                
                logger.info(
                    "Card animation generated successfully",
                    mp4_path=str(mp4_path),
                    rarity=rarity.value,
                    file_size_kb=mp4_path.stat().st_size / 1024,
                )

                return mp4_path
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                # If ffmpeg fails, fall back to GIF
                logger.warning(
                    "Failed to convert to MP4, using GIF instead",
                    error=str(e),
                    gif_path=str(temp_gif_path),
                )
                # Rename temp GIF to final GIF
                gif_path = image_path.parent / f"{image_path.stem}_animated.gif"
                temp_gif_path.rename(gif_path)
                return gif_path

        except Exception as e:
            logger.error(
                "Failed to generate card animation",
                image_path=str(image_path),
                rarity=rarity.value,
                error=str(e),
                exc_info=True,
            )
            return None

    def _create_holographic_shimmer(
        self, base_image: Image.Image, frame_num: int, total_frames: int, intensity: float = 0.4
    ) -> Image.Image:
        """
        Create holographic shimmer effect with rainbow gradient bands.

        Args:
            base_image: Base card image
            frame_num: Current frame number
            total_frames: Total number of frames
            intensity: Effect intensity (0.0 to 1.0)

        Returns:
            Frame with holographic shimmer effect
        """
        frame = base_image.copy()
        width, height = frame.size

        # Create overlay for holographic effect
        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Calculate shimmer position (moves across the card in a wave pattern)
        progress = (frame_num / total_frames) * 2 * math.pi
        shimmer_x = int((width * 0.4) * math.sin(progress) + width * 0.5)

        # Create multiple rainbow gradient bands
        num_bands = 6
        for i in range(num_bands):
            offset = (i - num_bands // 2) * 80 + shimmer_x

            # Rainbow colors with varying opacity
            hue = (i / num_bands) * 360
            colors = [
                (255, 0, 0, int(40 * intensity)),      # Red
                (255, 165, 0, int(50 * intensity)),   # Orange
                (255, 255, 0, int(40 * intensity)),    # Yellow
                (0, 255, 0, int(40 * intensity)),      # Green
                (0, 0, 255, int(50 * intensity)),      # Blue
                (128, 0, 128, int(40 * intensity)),    # Purple
            ]
            color = colors[i % len(colors)]

            # Draw gradient band
            for x in range(max(0, offset - 60), min(width, offset + 60)):
                distance = abs(x - offset)
                alpha = int(color[3] * (1 - distance / 60) * (0.5 + 0.5 * math.sin(progress)))
                if alpha > 0:
                    draw.rectangle([(x, 0), (x, height)], fill=(color[0], color[1], color[2], alpha))

        # Blend overlay with base image
        frame = Image.alpha_composite(frame, overlay)
        return frame

    def _create_sparkle_frame(
        self, base_image: Image.Image, frame_num: int, total_frames: int, count: int = 10
    ) -> Image.Image:
        """
        Add random sparkle particles that appear and fade.

        Args:
            base_image: Base card image
            frame_num: Current frame number
            total_frames: Total number of frames
            count: Number of sparkles per frame

        Returns:
            Frame with sparkle particles
        """
        frame = base_image.copy()
        width, height = frame.size

        # Create overlay for sparkles
        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Seed random for consistent sparkle positions across frames
        random.seed(42)  # Fixed seed for reproducibility

        # Generate sparkles
        for _ in range(count):
            # Random position
            x = random.randint(50, width - 50)
            y = random.randint(50, height - 50)

            # Sparkle lifecycle: appear, peak, fade
            sparkle_cycle = (frame_num + random.randint(0, total_frames)) % total_frames
            life_progress = sparkle_cycle / (total_frames * 0.5)  # Sparkle lasts half the animation

            if life_progress <= 1.0:
                # Calculate alpha based on lifecycle
                if life_progress < 0.3:
                    alpha = int(255 * (life_progress / 0.3))  # Fade in
                else:
                    alpha = int(255 * (1 - (life_progress - 0.3) / 0.7))  # Fade out

                # Draw sparkle (small cross pattern)
                size = random.randint(3, 6)
                sparkle_color = (255, 255, 255, alpha)  # White sparkles

                # Horizontal line
                draw.rectangle(
                    [(x - size, y - 1), (x + size, y + 1)], fill=sparkle_color
                )
                # Vertical line
                draw.rectangle(
                    [(x - 1, y - size), (x + 1, y + size)], fill=sparkle_color
                )

        # Blend overlay
        frame = Image.alpha_composite(frame, overlay)
        return frame

    def _create_border_glow(
        self, base_image: Image.Image, frame_num: int, total_frames: int, intensity: float = 0.3
    ) -> Image.Image:
        """
        Create pulsing glow effect on card borders.

        Args:
            base_image: Base card image
            frame_num: Current frame number
            total_frames: Total number of frames
            intensity: Glow intensity (0.0 to 1.0)

        Returns:
            Frame with border glow effect
        """
        frame = base_image.copy()
        width, height = frame.size

        # Calculate pulse (0.0 to 1.0)
        pulse = (math.sin(frame_num / total_frames * 2 * math.pi) + 1) / 2

        # Create glow overlay
        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Border glow width
        glow_width = int(20 * intensity * (0.5 + 0.5 * pulse))

        # Draw glow on all four borders
        glow_color = (255, 255, 255, int(60 * intensity * pulse))

        # Top border
        draw.rectangle([(0, 0), (width, glow_width)], fill=glow_color)
        # Bottom border
        draw.rectangle([(0, height - glow_width), (width, height)], fill=glow_color)
        # Left border
        draw.rectangle([(0, 0), (glow_width, height)], fill=glow_color)
        # Right border
        draw.rectangle([(width - glow_width, 0), (width, height)], fill=glow_color)

        # Blend with base image using soft light
        frame = Image.alpha_composite(frame, overlay)
        return frame
