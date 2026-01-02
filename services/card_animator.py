"""Card animation generation service with beautiful holographic and particle effects."""

import colorsys
import math
import random
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

from database.enums import Rarity
from logging_config import get_logger

logger = get_logger(__name__)


class CardAnimator:
    """Service for generating animated MP4 videos from static card images."""

    def __init__(self):
        """Initialize CardAnimator."""
        logger.info("CardAnimator initialized")

    def generate_card_animation(
        self, image_path: Path, rarity: Rarity, total_frames: int = 100, duration: int = 50
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

            # Apply color grading first (base enhancement)
            base_img = self._apply_color_grading(base_img, rarity)
            
            # Initialize particle system for rarer cards
            particles = None
            if rarity in (Rarity.LEGENDARY, Rarity.MYTHIC):
                particles = self._init_particle_system(base_img.size, rarity, total_frames)

            # Generate frames based on rarity
            frames = []
            for i in range(total_frames):
                frame = base_img.copy()

                # Apply rarity-specific effects
                if rarity == Rarity.MYTHIC:
                    # Mythic: Full holographic foil + particles + lens flare + bloom
                    frame = self._create_advanced_foil_effect(frame, i, total_frames, intensity=0.7)
                    if particles:
                        frame = self._update_particle_system(frame, particles, i, total_frames)
                    frame = self._create_lens_flare(frame, i, total_frames, intensity=0.6)
                    frame = self._create_bloom_effect(frame, intensity=0.4)
                    frame = self._create_border_glow(frame, i, total_frames, intensity=0.5)
                elif rarity == Rarity.LEGENDARY:
                    # Legendary: Holographic foil + particles + bloom
                    frame = self._create_advanced_foil_effect(frame, i, total_frames, intensity=0.5)
                    if particles:
                        frame = self._update_particle_system(frame, particles, i, total_frames)
                    frame = self._create_bloom_effect(frame, intensity=0.3)
                elif rarity == Rarity.EPIC:
                    # Epic: Subtle holographic foil + light bloom
                    frame = self._create_advanced_foil_effect(frame, i, total_frames, intensity=0.3)
                    frame = self._create_bloom_effect(frame, intensity=0.2)

                frames.append(frame)

            # Generate MP4 directly from frames using ffmpeg (no intermediate GIF)
            mp4_path = image_path.parent / f"{image_path.stem}_animated.mp4"
            
            # Use system temp directory for frame storage (writable by appuser)
            import tempfile
            temp_dir = Path(tempfile.mkdtemp(prefix=f"{image_path.stem}_frames_"))
            
            try:
                # Save frames as temporary WebP files (smaller, faster)
                frame_paths = []
                for i, frame in enumerate(frames):
                    frame_path = temp_dir / f"frame_{i:04d}.webp"
                    frame.save(frame_path, 'WEBP', quality=95, method=4)
                    frame_paths.append(frame_path)
                
                # Fixed 20 fps for smooth, beautiful animations
                fps = 20.0
                
                # Use ffmpeg to create MP4 directly from WebP sequence
                # -framerate: Input frame rate
                # -i: Input pattern for frame sequence (WebP)
                # -c:v libx264: H.264 codec
                # -profile:v baseline: Use baseline profile for maximum compatibility
                # -level 3.0: H.264 level for compatibility
                # -pix_fmt yuv420p: Ensure compatibility
                # -movflags +faststart: Optimize for streaming
                # -an: No audio track
                # -vf: Scale to 1080p width (portrait) + ensure even dimensions
                # -preset fast: Faster encoding
                cmd = [
                    'ffmpeg',
                    '-framerate', str(fps),
                    '-i', str(temp_dir / 'frame_%04d.webp'),
                    '-c:v', 'libx264',
                    '-profile:v', 'baseline',  # Maximum compatibility
                    '-level', '3.0',  # H.264 level
                    '-pix_fmt', 'yuv420p',
                    '-movflags', '+faststart',
                    '-vf', 'scale=1080:1920:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2',  # 1080p portrait
                    '-preset', 'fast',  # Faster encoding
                    '-an',  # No audio
                    '-y',  # Overwrite
                    str(mp4_path)
                ]
                
                subprocess.run(cmd, capture_output=True, check=True)
                
                logger.info(
                    "Card animation generated successfully",
                    mp4_path=str(mp4_path),
                    rarity=rarity.value,
                    file_size_kb=mp4_path.stat().st_size / 1024,
                    fps=fps,
                )

                return mp4_path
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                logger.error(
                    "Failed to generate MP4 animation",
                    image_path=str(image_path),
                    rarity=rarity.value,
                    error=str(e),
                    exc_info=True,
                )
                return None
            finally:
                # Always clean up temporary frame directory
                shutil.rmtree(temp_dir, ignore_errors=True)

        except Exception as e:
            logger.error(
                "Failed to generate card animation",
                image_path=str(image_path),
                rarity=rarity.value,
                error=str(e),
                exc_info=True,
            )
            return None

    def _create_advanced_foil_effect(
        self, base_image: Image.Image, frame_num: int, total_frames: int, intensity: float = 0.5
    ) -> Image.Image:
        """
        Create advanced holographic foil effect with chromatic aberration and iridescence.

        Args:
            base_image: Base card image
            frame_num: Current frame number
            total_frames: Total number of frames
            intensity: Effect intensity (0.0 to 1.0)

        Returns:
            Frame with advanced holographic foil effect
        """
        frame = base_image.copy()
        width, height = frame.size

        # Apply chromatic aberration (RGB channel separation)
        if frame.mode == 'RGBA':
            r, g, b, a = frame.split()
        else:
            r, g, b = frame.split()
            a = None

        # Slow, smooth movement for beautiful effect
        progress = (frame_num / total_frames) * 2 * math.pi
        offset = int(2 * intensity * math.sin(progress))
        
        # Shift red and blue channels (chromatic aberration)
        if offset != 0:
            r = r.transform(r.size, Image.AFFINE, (1, 0, offset, 0, 1, 0), fillcolor=0)
            b = b.transform(b.size, Image.AFFINE, (1, 0, -offset, 0, 1, 0), fillcolor=0)
        
        if a:
            frame = Image.merge('RGBA', (r, g, b, a))
        else:
            frame = Image.merge('RGB', (r, g, b))

        # Create iridescent overlay with smooth gradient
        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Calculate shimmer position (slow, smooth wave)
        # Use integer multiplier for seamless looping (value and velocity match at 0 and 2pi)
        shimmer_x = int((width * 0.5) * math.sin(progress) + width * 0.5)
        shimmer_y = int((height * 0.3) * math.cos(progress) + height * 0.5)

        # Create multiple iridescent bands with smooth gradients (optimized)
        num_bands = 6
        for i in range(num_bands):
            # Slow-moving bands
            # Use integer multipliers for seamless looping
            band_progress = (progress + i * (2 * math.pi / num_bands)) % (2 * math.pi)
            offset_x = int((width * 0.5) * math.sin(band_progress) + shimmer_x)
            offset_y = int((height * 0.3) * math.cos(band_progress) + shimmer_y)

            # Iridescent colors (smooth rainbow transition)
            hue_shift = (i / num_bands + frame_num / total_frames) % 1.0
            colors = self._hsv_to_rgb(hue_shift, 0.85, 1.0)
            alpha = int(70 * intensity * (0.7 + 0.3 * math.sin(band_progress)))

            # Draw smooth gradient band using rectangles (faster than point-by-point)
            band_width = 100
            for x in range(max(0, offset_x - band_width), min(width, offset_x + band_width), 2):
                distance = abs(x - offset_x) / band_width
                fade = (1 - distance) * (0.6 + 0.4 * math.sin(band_progress))
                pixel_alpha = int(alpha * fade)
                if pixel_alpha > 5:
                    # Draw vertical gradient line
                    y_start = max(0, offset_y - 25)
                    y_end = min(height, offset_y + 25)
                    for y in range(y_start, y_end, 2):
                        y_dist = abs(y - offset_y) / 25
                        final_alpha = int(pixel_alpha * (1 - y_dist))
                        if final_alpha > 5:
                            draw.rectangle(
                                [(x, y), (x + 1, y + 1)],
                                fill=(*colors, final_alpha)
                            )

        # Blend overlay with screen mode for bright, vibrant effect
        frame = Image.alpha_composite(frame, overlay)
        return frame

    def _hsv_to_rgb(self, h: float, s: float, v: float) -> tuple[int, int, int]:
        """Convert HSV to RGB."""
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return (int(r * 255), int(g * 255), int(b * 255))

    def _init_particle_system(
        self, size: tuple[int, int], rarity: Rarity, total_frames: int
    ) -> list:
        """
        Initialize particle system for beautiful effects.

        Args:
            size: Image size (width, height)
            rarity: Card rarity
            total_frames: Total frames in animation

        Returns:
            List of particle objects
        """
        width, height = size
        particles = []
        
        # Particle count based on rarity
        count_map = {
            Rarity.EPIC: 10,
            Rarity.LEGENDARY: 20,
            Rarity.MYTHIC: 35,
        }
        count = count_map.get(rarity, 10)

        random.seed(42)  # Consistent particle positions
        for _ in range(count):
            particles.append({
                # Center of motion (can be outside screen to allow drifting in)
                'cx': random.uniform(width * 0.1, width * 0.9),
                'cy': random.uniform(height * 0.1, height * 0.9),
                # Movement radius for looping "floating" effect
                'rx': random.uniform(10, 30),
                'ry': random.uniform(10, 30),
                # Phase offset
                'phase_x': random.uniform(0, 2 * math.pi),
                'phase_y': random.uniform(0, 2 * math.pi),
                # Pulsing
                'alpha_base': random.randint(150, 200),
                'alpha_var': random.randint(30, 50),
                'alpha_phase': random.uniform(0, 2 * math.pi),
                
                'size': random.uniform(2, 5),
                'color': random.choice([
                    (255, 255, 255),  # White
                    (255, 255, 200),  # Warm white
                    (200, 255, 255),  # Cool white
                    (255, 200, 255),  # Pink
                ]),
            })
        
        return particles

    def _update_particle_system(
        self, base_image: Image.Image, particles: list, frame_num: int, total_frames: int
    ) -> Image.Image:
        """
        Update and render particle system.

        Args:
            base_image: Base card image
            particles: List of particle objects
            frame_num: Current frame number
            total_frames: Total number of frames

        Returns:
            Frame with particle effects
        """
        frame = base_image.copy()
        width, height = frame.size

        overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Progress 0 to 2pi
        progress = (frame_num / total_frames) * 2 * math.pi

        for p in particles:
            # Calculate position based on periodic function for seamless looping
            # x = cx + rx * sin(progress + phase)
            x = p['cx'] + p['rx'] * math.sin(progress + p['phase_x'])
            y = p['cy'] + p['ry'] * math.cos(progress + p['phase_y'])

            # Calculate alpha based on periodic pulsing
            # alpha = base + var * sin(progress + phase)
            alpha = int(p['alpha_base'] + p['alpha_var'] * math.sin(progress + p['alpha_phase']))
            size = p['size']

            if alpha > 0 and -size < x < width + size and -size < y < height + size:
                # Draw particle with glow
                color = (*p['color'], alpha)
                px, py = int(x), int(y)
                
                # Main particle
                draw.ellipse(
                    [(px - size, py - size), (px + size, py + size)],
                    fill=color
                )
                # Glow effect
                if size > 2:
                    glow_alpha = alpha // 3
                    draw.ellipse(
                        [(px - size * 2, py - size * 2), (px + size * 2, py + size * 2)],
                        fill=(*p['color'], glow_alpha)
                    )

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

    def _apply_color_grading(self, image: Image.Image, rarity: Rarity) -> Image.Image:
        """
        Apply cinematic color grading based on rarity.

        Args:
            image: Base card image
            rarity: Card rarity

        Returns:
            Color-graded image
        """
        # Rarity-specific color grading
        grading = {
            Rarity.COMMON: {'saturation': 0.95, 'contrast': 1.0, 'brightness': 1.0},
            Rarity.RARE: {'saturation': 1.05, 'contrast': 1.05, 'brightness': 1.02},
            Rarity.EPIC: {'saturation': 1.15, 'contrast': 1.1, 'brightness': 1.05},
            Rarity.LEGENDARY: {'saturation': 1.25, 'contrast': 1.15, 'brightness': 1.08},
            Rarity.MYTHIC: {'saturation': 1.35, 'contrast': 1.2, 'brightness': 1.1},
        }
        
        config = grading.get(rarity, grading[Rarity.COMMON])
        
        # Apply enhancements
        enhancer = ImageEnhance.Color(image)
        image = enhancer.enhance(config['saturation'])
        
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(config['contrast'])
        
        enhancer = ImageEnhance.Brightness(image)
        image = enhancer.enhance(config['brightness'])
        
        return image

    def _create_lens_flare(
        self, base_image: Image.Image, frame_num: int, total_frames: int, intensity: float = 0.5
    ) -> Image.Image:
        """
        Create realistic lens flare effect with moving light source.

        Args:
            base_image: Base card image
            frame_num: Current frame number
            total_frames: Total number of frames
            intensity: Effect intensity (0.0 to 1.0)

        Returns:
            Frame with lens flare effect
        """
        frame = base_image.copy()
        width, height = frame.size

        # Calculate light source position (slow, smooth movement)
        progress = (frame_num / total_frames) * 2 * math.pi
        # Use integer multipliers (1.0) to ensure start(0) and end(2pi) match in value and slope
        light_x = int(width * 0.5 + width * 0.25 * math.sin(progress))
        light_y = int(height * 0.5 + height * 0.2 * math.cos(progress))

        # Create flare overlay
        flare = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(flare)

        # Main flare circle (bright center)
        main_alpha = int(180 * intensity)
        draw.ellipse(
            [(light_x - 25, light_y - 25), (light_x + 25, light_y + 25)],
            fill=(255, 255, 220, main_alpha)
        )

        # Secondary flare circles
        for i in range(3):
            offset = (i + 1) * 40
            angle = progress + i * math.pi / 3
            x = int(light_x + offset * math.cos(angle))
            y = int(light_y + offset * math.sin(angle))
            alpha = int(100 * intensity / (i + 2))
            size = 15 - i * 3
            draw.ellipse(
                [(x - size, y - size), (x + size, y + size)],
                fill=(255, 255, 200, alpha)
            )

        # Anamorphic streaks (horizontal)
        streak_alpha = int(80 * intensity)
        for i in range(5):
            offset_y = (i - 2) * 8
            streak_width = 200 - abs(i - 2) * 20
            draw.ellipse(
                [(light_x - streak_width, light_y + offset_y - 2),
                 (light_x + streak_width, light_y + offset_y + 2)],
                fill=(255, 255, 200, streak_alpha)
            )

        frame = Image.alpha_composite(frame, flare)
        return frame

    def _create_bloom_effect(self, image: Image.Image, intensity: float = 0.3) -> Image.Image:
        """
        Create bloom/glow effect around bright areas.

        Args:
            image: Base card image
            intensity: Bloom intensity (0.0 to 1.0)

        Returns:
            Frame with bloom effect
        """
        if intensity <= 0:
            return image

        # Extract bright areas (threshold)
        threshold = 200
        bright = image.point(lambda p: p if p > threshold else 0)

        # Apply Gaussian blur for glow
        blurred = bright.filter(ImageFilter.GaussianBlur(radius=8))

        # Blend back with original (additive blend for glow)
        # Create a copy for blending
        result = image.copy()
        
        # Blend the blurred bright areas with the original
        # Using screen blend mode approximation
        if result.mode == 'RGBA':
            # Manual blend for RGBA
            img_array = np.array(result, dtype=np.float32)
            blur_array = np.array(blurred, dtype=np.float32)
            
            # Screen blend: 1 - (1 - a) * (1 - b)
            blended = 255 - (255 - img_array) * (255 - blur_array * intensity) / 255
            blended = np.clip(blended, 0, 255).astype(np.uint8)
            
            result = Image.fromarray(blended, 'RGBA')
        else:
            # For RGB, use simpler blend
            result = Image.blend(result, blurred, intensity * 0.3)

        return result
