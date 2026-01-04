#!/usr/bin/env python3
"""Remove white borders from card images by making them transparent."""

from pathlib import Path
from PIL import Image

def remove_white_borders(image: Image.Image, threshold: int = 240, edge_tolerance: int = 10) -> Image.Image:
    """
    Remove white/light borders from an image by making them transparent.
    
    Args:
        image: PIL Image object
        threshold: RGB threshold for white detection (0-255, default 240)
        edge_tolerance: Pixels from edge to check for white (default 10)
        
    Returns:
        Image with white borders made transparent
    """
    # Ensure image has alpha channel
    if image.mode != 'RGBA':
        image = image.convert('RGBA')
    
    width, height = image.size
    pixels = image.load()
    
    # Create a mask for pixels to make transparent
    # Check edges for white pixels
    for y in range(height):
        for x in range(width):
            # Only process edge pixels (within tolerance)
            is_edge = (
                x < edge_tolerance or 
                x >= width - edge_tolerance or
                y < edge_tolerance or
                y >= height - edge_tolerance
            )
            
            if is_edge:
                r, g, b, a = pixels[x, y]
                # Check if pixel is white/light
                if r >= threshold and g >= threshold and b >= threshold:
                    # Make transparent
                    pixels[x, y] = (r, g, b, 0)
    
    return image

def process_card(card_path: Path, threshold: int = 240, edge_tolerance: int = 10) -> None:
    """Process a single card file to remove white borders."""
    print(f'Processing {card_path.name}...')
    
    try:
        # Open image
        img = Image.open(card_path)
        original_size = card_path.stat().st_size / 1024  # KB
        
        # Remove white borders
        img_processed = remove_white_borders(img, threshold=threshold, edge_tolerance=edge_tolerance)
        
        # Save (overwrite original)
        if card_path.suffix.lower() == '.webp':
            img_processed.save(card_path, 'WEBP', quality=90, method=6)
        elif card_path.suffix.lower() == '.gif':
            # For GIFs, we need to process all frames
            if getattr(img, 'is_animated', False):
                frames = []
                durations = []
                frame_count = 0
                
                while True:
                    frame = img.copy()
                    frame_processed = remove_white_borders(frame, threshold=threshold, edge_tolerance=edge_tolerance)
                    frames.append(frame_processed)
                    durations.append(img.info.get('duration', 100))
                    frame_count += 1
                    try:
                        img.seek(frame_count)
                    except EOFError:
                        break
                
                if frames:
                    frames[0].save(
                        card_path,
                        'GIF',
                        save_all=True,
                        append_images=frames[1:],
                        duration=durations,
                        loop=0,
                        optimize=False,
                    )
            else:
                img_processed.save(card_path, 'GIF')
        else:
            img_processed.save(card_path)
        
        new_size = card_path.stat().st_size / 1024  # KB
        
        print(f'  Original: {original_size:.1f} KB')
        print(f'  Updated: {new_size:.1f} KB')
        print(f'  SUCCESS: White borders removed')
        
    except Exception as e:
        print(f'  ERROR: {e}')
        import traceback
        traceback.print_exc()

def main():
    """Process all card files in placeholders directory."""
    placeholders_dir = Path('assets/placeholders')
    
    # Find all card files (WebP and GIF)
    card_files = sorted(list(placeholders_dir.glob('*.webp')) + list(placeholders_dir.glob('*.gif')))
    
    if not card_files:
        print('No card files found in assets/placeholders/')
        return
    
    print(f'Removing white borders from {len(card_files)} card images\n')
    print('=' * 60)
    
    for card_path in card_files:
        process_card(card_path, threshold=240, edge_tolerance=10)
        print()
    
    print('=' * 60)
    print(f'\nDone! {len(card_files)} cards processed to remove white borders.')

if __name__ == '__main__':
    main()
