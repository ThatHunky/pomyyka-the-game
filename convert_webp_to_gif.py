#!/usr/bin/env python3
"""Convert animated WebP files to GIF format for Telegram."""

from pathlib import Path
from PIL import Image

def convert_webp_to_gif(webp_path: Path) -> Path | None:
    """
    Convert animated WebP to GIF format.
    
    Args:
        webp_path: Path to animated WebP file
        
    Returns:
        Path to generated GIF file, or None if conversion failed
    """
    try:
        # Open animated WebP
        webp_img = Image.open(webp_path)
        
        if not getattr(webp_img, 'is_animated', False):
            print(f'  WARNING: {webp_path.name} is not animated, skipping...')
            return None
        
        # Get all frames
        frames = []
        durations = []
        
        try:
            frame_count = 0
            while True:
                frames.append(webp_img.copy())
                # Get frame duration (default to 100ms if not available)
                duration = webp_img.info.get('duration', 100)
                durations.append(duration)
                frame_count += 1
                try:
                    webp_img.seek(frame_count)
                except EOFError:
                    break
        except Exception as e:
            print(f'  WARNING: Error extracting frames: {e}')
            return None
        
        if not frames:
            print(f'  ERROR: No frames extracted from {webp_path.name}')
            return None
        
        # Create GIF path
        gif_path = webp_path.parent / f"{webp_path.stem}.gif"
        
        # Save as GIF
        frames[0].save(
            gif_path,
            'GIF',
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,  # Loop infinitely
            optimize=False,  # Better quality
        )
        
        original_size = webp_path.stat().st_size / 1024  # KB
        new_size = gif_path.stat().st_size / 1024  # KB
        
        print(f'  Original: {original_size:.1f} KB')
        print(f'  GIF: {new_size:.1f} KB')
        print(f'  Frames: {len(frames)}')
        print(f'  SUCCESS: {gif_path.name}')
        
        return gif_path
        
    except Exception as e:
        print(f'  ERROR: {e}')
        import traceback
        traceback.print_exc()
        return None

def main():
    """Convert all animated WebP files to GIF."""
    placeholders_dir = Path('assets/placeholders')
    
    # Find all animated WebP files
    animated_webp_files = sorted(placeholders_dir.glob('*_animated.webp'))
    
    if not animated_webp_files:
        print('No animated WebP files found in assets/placeholders/')
        return
    
    print(f'Converting {len(animated_webp_files)} animated WebP files to GIF\n')
    print('=' * 60)
    
    converted_count = 0
    for webp_path in animated_webp_files:
        print(f'Converting {webp_path.name}...')
        gif_path = convert_webp_to_gif(webp_path)
        if gif_path:
            converted_count += 1
        print()
    
    print('=' * 60)
    print(f'\nDone! Converted {converted_count} of {len(animated_webp_files)} files to GIF format.')

if __name__ == '__main__':
    main()
