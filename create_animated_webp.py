#!/usr/bin/env python3
"""Create animated WebP files for rarer cards with holographic/glowing effects."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter
import math

def create_holographic_frame(base_image: Image.Image, frame_num: int, total_frames: int = 8) -> Image.Image:
    """
    Create a single frame with holographic shimmer effect.
    
    Args:
        base_image: Base card image
        frame_num: Current frame number (0 to total_frames-1)
        total_frames: Total number of frames in animation
        
    Returns:
        Animated frame with holographic effect
    """
    # Create a copy to work with
    frame = base_image.copy()
    
    if frame.mode != 'RGBA':
        frame = frame.convert('RGBA')
    
    width, height = frame.size
    
    # Create a gradient overlay for holographic effect
    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    # Calculate shimmer position (moves across the card)
    progress = (frame_num / total_frames) * 2 * math.pi  # 0 to 2π
    shimmer_x = int((width * 0.3) * math.sin(progress) + width * 0.5)
    
    # Create gradient bands for holographic rainbow effect
    for i in range(5):
        offset = (i - 2) * 100 + shimmer_x
        # Rainbow colors: red, orange, yellow, green, blue, purple
        colors = [
            (255, 0, 0, 30),    # Red
            (255, 165, 0, 40),  # Orange
            (255, 255, 0, 30),  # Yellow
            (0, 255, 0, 30),    # Green
            (0, 0, 255, 40),    # Blue
            (128, 0, 128, 30),   # Purple
        ]
        
        color = colors[i % len(colors)]
        # Draw semi-transparent gradient band
        for x in range(max(0, offset - 50), min(width, offset + 50)):
            alpha = int(color[3] * (1 - abs(x - offset) / 50))
            if alpha > 0:
                draw.rectangle([(x, 0), (x, height)], fill=(color[0], color[1], color[2], alpha))
    
    # Blend overlay with base image
    frame = Image.alpha_composite(frame, overlay)
    
    return frame

def create_glow_frame(base_image: Image.Image, frame_num: int, total_frames: int = 8, glow_intensity: float = 0.3) -> Image.Image:
    """
    Create a frame with pulsing glow effect.
    
    Args:
        base_image: Base card image
        frame_num: Current frame number
        total_frames: Total number of frames
        glow_intensity: Intensity of glow (0.0 to 1.0)
        
    Returns:
        Frame with glow effect
    """
    frame = base_image.copy()
    
    if frame.mode != 'RGBA':
        frame = frame.convert('RGBA')
    
    # Calculate pulse (0.0 to 1.0)
    pulse = (math.sin(frame_num / total_frames * 2 * math.pi) + 1) / 2
    
    # Apply subtle glow by slightly brightening the image
    # This is a simple approach - for more advanced glow, we'd need edge detection
    brightness_factor = 1.0 + (pulse * glow_intensity * 0.1)
    
    # Split channels
    r, g, b, a = frame.split()
    
    # Brighten RGB channels slightly
    r = r.point(lambda x: min(255, int(x * brightness_factor)))
    g = g.point(lambda x: min(255, int(x * brightness_factor)))
    b = b.point(lambda x: min(255, int(x * brightness_factor)))
    
    # Recombine
    frame = Image.merge('RGBA', (r, g, b, a))
    
    return frame

def create_animated_webp(card_path: Path, rarity: str, total_frames: int = 8, duration: int = 100, create_sticker: bool = False) -> None:
    """
    Create an animated WebP from a static card image.
    
    Args:
        card_path: Path to static WebP file
        rarity: Card rarity (Epic, Legendary, Mythic)
        total_frames: Number of frames in animation
        duration: Duration per frame in milliseconds
        create_sticker: If True, also create Telegram sticker-sized version (512px, <256KB)
    """
    print(f'Creating animated WebP for {card_path.name} ({rarity})...')
    
    try:
        # Open base image
        base_img = Image.open(card_path)
        original_size = card_path.stat().st_size / 1024  # KB
        
        # Create frames based on rarity
        frames = []
        
        if rarity == 'MYTHIC':
            # Mythic: Full holographic shimmer + glow
            for i in range(total_frames):
                frame = create_holographic_frame(base_img, i, total_frames)
                frame = create_glow_frame(frame, i, total_frames, glow_intensity=0.4)
                frames.append(frame)
        elif rarity == 'LEGENDARY':
            # Legendary: Holographic shimmer + subtle glow
            for i in range(total_frames):
                frame = create_holographic_frame(base_img, i, total_frames)
                frame = create_glow_frame(frame, i, total_frames, glow_intensity=0.25)
                frames.append(frame)
        elif rarity == 'EPIC':
            # Epic: Subtle holographic shimmer only
            for i in range(total_frames):
                frame = create_holographic_frame(base_img, i, total_frames)
                frames.append(frame)
        else:
            print(f'  Skipping {rarity} - animation only for Epic, Legendary, Mythic')
            return
        
        # Create full-size animated WebP
        output_path = card_path.parent / f'{card_path.stem}_animated.webp'
        
        frames[0].save(
            output_path,
            'WEBP',
            save_all=True,
            append_images=frames[1:],
            duration=duration,
            loop=0,  # Loop infinitely
            quality=90,
            method=6
        )
        
        new_size = output_path.stat().st_size / 1024  # KB
        
        print(f'  Original: {original_size:.1f} KB')
        print(f'  Animated (full): {new_size:.1f} KB')
        print(f'  Frames: {total_frames}')
        print(f'  SUCCESS: {output_path.name}')
        
        # Create sticker-sized version if requested
        if create_sticker:
            # Resize to 512px height (maintains aspect ratio)
            sticker_frames = []
            for frame in frames:
                # Calculate width to maintain aspect ratio with 512px height
                width, height = frame.size
                new_height = 512
                new_width = int((width / height) * new_height)
                
                # Resize frame
                sticker_frame = frame.resize((new_width, new_height), Image.Resampling.LANCZOS)
                sticker_frames.append(sticker_frame)
            
            # Try different quality settings to get under 256KB
            sticker_path = card_path.parent / f'{card_path.stem}_sticker.webp'
            
            for quality in [85, 80, 75, 70, 65]:
                sticker_frames[0].save(
                    sticker_path,
                    'WEBP',
                    save_all=True,
                    append_images=sticker_frames[1:],
                    duration=duration,
                    loop=0,
                    quality=quality,
                    method=6
                )
                
                sticker_size = sticker_path.stat().st_size / 1024  # KB
                if sticker_size <= 256:
                    print(f'  Sticker version: {sticker_size:.1f} KB (quality={quality})')
                    print(f'  SUCCESS: {sticker_path.name}')
                    break
            else:
                print(f'  WARNING: Sticker version is {sticker_size:.1f} KB (exceeds 256KB limit)')
                print(f'  Created anyway: {sticker_path.name}')
        
    except Exception as e:
        print(f'  ERROR: {e}')
        import traceback
        traceback.print_exc()

def main():
    """Create animated WebP files for rarer cards."""
    placeholders_dir = Path('assets/placeholders')
    
    # Cards to animate (only rarer ones)
    cards_to_animate = {
        'NORMAL_EPIC': 'EPIC',
        'NORMAL_LEGENDARY': 'LEGENDARY',
        'NORMAL_MYTHIC': 'MYTHIC',
    }
    
    print('Creating animated WebP files for rarer cards\n')
    print('=' * 60)
    
    for card_name, rarity in cards_to_animate.items():
        webp_path = placeholders_dir / f'{card_name}.webp'
        
        if not webp_path.exists():
            print(f'WARNING: {webp_path} not found, skipping...\n')
            continue
        
        create_animated_webp(webp_path, rarity, total_frames=8, duration=100)
        print()
    
    print('=' * 60)
    print('\nDone! Animated WebP files created.')
    print('Note: Telegram supports animated WebP stickers and will display them animated in chats!')

if __name__ == '__main__':
    main()
