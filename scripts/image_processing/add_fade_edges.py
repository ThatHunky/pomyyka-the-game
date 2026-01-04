#!/usr/bin/env python3
"""Add rounded corners and fade-out to transparency on card edges for better sticker appearance."""

from pathlib import Path
from PIL import Image, ImageDraw

def round_corners(image: Image.Image, corner_radius: int = 80) -> Image.Image:
    """
    Round the corners of an image.
    
    Args:
        image: PIL Image object
        corner_radius: Radius of rounded corners in pixels (default 80)
        
    Returns:
        Image with rounded corners
    """
    # Ensure image has alpha channel
    if image.mode != 'RGBA':
        image = image.convert('RGBA')
    
    width, height = image.size
    
    # Create a mask for rounded corners
    mask = Image.new('L', (width, height), 0)
    draw = ImageDraw.Draw(mask)
    
    # Draw white rounded rectangle (this will be our mask)
    draw.rounded_rectangle(
        [(0, 0), (width, height)],
        radius=corner_radius,
        fill=255
    )
    
    # Apply mask to alpha channel
    alpha = image.split()[3]
    alpha = Image.composite(alpha, Image.new('L', (width, height), 0), mask)
    
    # Reconstruct image with new alpha
    r, g, b, _ = image.split()
    result = Image.merge('RGBA', (r, g, b, alpha))
    
    return result

def add_fade_edges(image: Image.Image, fade_size: int = 50) -> Image.Image:
    """
    Add fade-out to transparency on edges and corners.
    
    Args:
        image: PIL Image object
        fade_size: Size of fade area in pixels (default 50)
        
    Returns:
        Image with faded edges
    """
    # Ensure image has alpha channel
    if image.mode != 'RGBA':
        image = image.convert('RGBA')
    
    width, height = image.size
    
    # Create a mask that fades from center to edges
    # Start with fully opaque
    mask = Image.new('L', (width, height), 255)
    pixels = mask.load()
    
    # Calculate fade for each pixel
    for y in range(height):
        for x in range(width):
            # Calculate distance to nearest edge
            dist_left = x
            dist_right = width - x - 1
            dist_top = y
            dist_bottom = height - y - 1
            
            # Minimum distance to any edge
            dist_to_edge = min(dist_left, dist_right, dist_top, dist_bottom)
            
            # Calculate alpha based on distance
            if dist_to_edge < fade_size:
                # Fade from 1.0 (center) to 0.0 (edge)
                fade_ratio = dist_to_edge / fade_size
                # Apply smooth curve for better visual transition
                fade_ratio = fade_ratio ** 1.5
                alpha = int(255 * fade_ratio)
                pixels[x, y] = alpha
    
    # Apply mask to alpha channel
    alpha = image.split()[3]
    alpha = Image.composite(alpha, Image.new('L', (width, height), 0), mask)
    
    # Reconstruct image with new alpha
    r, g, b, _ = image.split()
    result = Image.merge('RGBA', (r, g, b, alpha))
    
    return result

def process_card(card_path: Path, corner_radius: int = 80, fade_size: int = 50) -> None:
    """Process a single card file."""
    print(f'Processing {card_path.name}...')
    
    try:
        # Open image
        img = Image.open(card_path)
        original_size = card_path.stat().st_size / 1024  # KB
        
        # Round corners first
        img_rounded = round_corners(img, corner_radius=corner_radius)
        
        # Then add fade edges
        img_faded = add_fade_edges(img_rounded, fade_size=fade_size)
        
        # Save (overwrite original)
        img_faded.save(card_path, 'WEBP', quality=90, method=6)
        
        new_size = card_path.stat().st_size / 1024  # KB
        
        print(f'  Original: {original_size:.1f} KB')
        print(f'  Updated: {new_size:.1f} KB')
        print(f'  SUCCESS: Rounded corners and fade edges added')
        
    except Exception as e:
        print(f'  ERROR: {e}')

def main():
    """Process all card WebP files in placeholders directory."""
    placeholders_dir = Path('assets/placeholders')
    
    # Find all WebP files
    webp_files = sorted(placeholders_dir.glob('*.webp'))
    
    if not webp_files:
        print('No WebP files found in assets/placeholders/')
        return
    
    print(f'Adding rounded corners and fade-out edges to {len(webp_files)} card images for sticker appearance\n')
    print('=' * 60)
    
    for webp_path in webp_files:
        process_card(webp_path, corner_radius=80, fade_size=50)
        print()
    
    print('=' * 60)
    print(f'\nDone! {len(webp_files)} cards now have rounded corners and smooth fade-out edges for better sticker appearance.')

if __name__ == '__main__':
    main()
