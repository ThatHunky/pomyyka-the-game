#!/usr/bin/env python3
"""Enhance card borders with decorative elements based on rarity."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter
import math

def add_decorative_border(
    image: Image.Image, 
    rarity: str,
    border_width: int = 15,
    corner_radius: int = 20
) -> Image.Image:
    """
    Add decorative border to card based on rarity.
    
    Args:
        image: PIL Image object
        rarity: Card rarity (COMMON, RARE, EPIC, LEGENDARY, MYTHIC)
        border_width: Width of decorative border in pixels
        corner_radius: Radius for rounded corners
        
    Returns:
        Image with enhanced decorative border
    """
    if image.mode != 'RGBA':
        image = image.convert('RGBA')
    
    width, height = image.size
    
    # Create a new image with border space
    new_width = width + (border_width * 2)
    new_height = height + (border_width * 2)
    result = Image.new('RGBA', (new_width, new_height), (0, 0, 0, 0))
    
    # Paste original image in center
    result.paste(image, (border_width, border_width), image if image.mode == 'RGBA' else None)
    
    # Draw decorative border based on rarity
    draw = ImageDraw.Draw(result)
    
    # Define rarity-specific border styles
    border_styles = {
        'COMMON': {
            'color': (200, 200, 200, 255),  # Light gray
            'pattern': 'simple',
            'glow': False,
        },
        'RARE': {
            'color': (100, 150, 255, 255),  # Blue
            'pattern': 'double',
            'glow': False,
        },
        'EPIC': {
            'color': (180, 100, 255, 255),  # Purple
            'pattern': 'ornate',
            'glow': True,
            'glow_color': (180, 100, 255, 100),
        },
        'LEGENDARY': {
            'color': (255, 180, 50, 255),  # Gold/Orange
            'pattern': 'ornate',
            'glow': True,
            'glow_color': (255, 200, 100, 120),
        },
        'MYTHIC': {
            'color': (255, 50, 50, 255),  # Red
            'pattern': 'ornate',
            'glow': True,
            'glow_color': (255, 100, 100, 150),
        },
    }
    
    style = border_styles.get(rarity, border_styles['COMMON'])
    
    # Draw border with rounded corners
    border_rect = [
        (border_width // 2, border_width // 2),
        (new_width - border_width // 2, new_height - border_width // 2)
    ]
    
    # Draw outer glow if applicable
    if style.get('glow', False):
        glow_color = style.get('glow_color', (255, 255, 255, 100))
        for i in range(3):
            glow_rect = [
                (border_width // 2 - i, border_width // 2 - i),
                (new_width - border_width // 2 + i, new_height - border_width // 2 + i)
            ]
            draw.rounded_rectangle(
                glow_rect,
                radius=corner_radius + i,
                outline=glow_color,
                width=2
            )
    
    # Draw main border
    if style['pattern'] == 'simple':
        # Simple single border
        draw.rounded_rectangle(
            border_rect,
            radius=corner_radius,
            outline=style['color'],
            width=border_width
        )
    elif style['pattern'] == 'double':
        # Double border
        draw.rounded_rectangle(
            border_rect,
            radius=corner_radius,
            outline=style['color'],
            width=border_width
        )
        inner_rect = [
            (border_width // 2 + 3, border_width // 2 + 3),
            (new_width - border_width // 2 - 3, new_height - border_width // 2 - 3)
        ]
        draw.rounded_rectangle(
            inner_rect,
            radius=corner_radius - 2,
            outline=style['color'],
            width=2
        )
    elif style['pattern'] == 'ornate':
        # Ornate border with decorative elements
        # Main border
        draw.rounded_rectangle(
            border_rect,
            radius=corner_radius,
            outline=style['color'],
            width=border_width
        )
        
        # Add corner decorations
        corner_size = border_width * 2
        corner_color = style['color']
        
        # Top-left corner
        draw.ellipse(
            [(0, 0), (corner_size, corner_size)],
            fill=corner_color,
            outline=None
        )
        # Top-right corner
        draw.ellipse(
            [(new_width - corner_size, 0), (new_width, corner_size)],
            fill=corner_color,
            outline=None
        )
        # Bottom-left corner
        draw.ellipse(
            [(0, new_height - corner_size), (corner_size, new_height)],
            fill=corner_color,
            outline=None
        )
        # Bottom-right corner
        draw.ellipse(
            [(new_width - corner_size, new_height - corner_size), (new_width, new_height)],
            fill=corner_color,
            outline=None
        )
        
        # Add decorative dots along border
        dot_spacing = 30
        dot_size = 3
        for i in range(0, new_width, dot_spacing):
            # Top border
            if border_width // 2 - dot_size < new_height - border_width // 2:
                draw.ellipse(
                    [(i, border_width // 2 - dot_size), (i + dot_size * 2, border_width // 2 + dot_size)],
                    fill=style['color']
                )
            # Bottom border
            if border_width // 2 - dot_size < new_height - border_width // 2:
                draw.ellipse(
                    [(i, new_height - border_width // 2 - dot_size), (i + dot_size * 2, new_height - border_width // 2 + dot_size)],
                    fill=style['color']
                )
        for i in range(0, new_height, dot_spacing):
            # Left border
            if border_width // 2 - dot_size < new_width - border_width // 2:
                draw.ellipse(
                    [(border_width // 2 - dot_size, i), (border_width // 2 + dot_size, i + dot_size * 2)],
                    fill=style['color']
                )
            # Right border
            if border_width // 2 - dot_size < new_width - border_width // 2:
                draw.ellipse(
                    [(new_width - border_width // 2 - dot_size, i), (new_width - border_width // 2 + dot_size, i + dot_size * 2)],
                    fill=style['color']
                )
    
    return result

def process_card(card_path: Path, rarity: str | None = None) -> None:
    """Process a single card file to enhance borders."""
    # Try to extract rarity from filename
    if not rarity:
        filename = card_path.stem.upper()
        if 'MYTHIC' in filename:
            rarity = 'MYTHIC'
        elif 'LEGENDARY' in filename:
            rarity = 'LEGENDARY'
        elif 'EPIC' in filename:
            rarity = 'EPIC'
        elif 'RARE' in filename:
            rarity = 'RARE'
        else:
            rarity = 'COMMON'
    
    print(f'Processing {card_path.name} (rarity: {rarity})...')
    
    try:
        # Open image
        img = Image.open(card_path)
        original_size = card_path.stat().st_size / 1024  # KB
        
        # Check if animated
        is_animated = getattr(img, 'is_animated', False)
        
        if is_animated:
            # Process all frames
            frames = []
            durations = []
            frame_count = 0
            
            while True:
                frame = img.copy()
                frame_enhanced = add_decorative_border(frame, rarity)
                frames.append(frame_enhanced)
                durations.append(img.info.get('duration', 100))
                frame_count += 1
                try:
                    img.seek(frame_count)
                except EOFError:
                    break
            
            if frames:
                # Save as GIF
                if card_path.suffix.lower() == '.gif':
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
                    # Save first frame as static
                    frames[0].save(card_path, 'WEBP', quality=90, method=6)
        else:
            # Process single frame
            img_enhanced = add_decorative_border(img, rarity)
            
            # Save
            if card_path.suffix.lower() == '.webp':
                img_enhanced.save(card_path, 'WEBP', quality=90, method=6)
            else:
                img_enhanced.save(card_path)
        
        new_size = card_path.stat().st_size / 1024  # KB
        
        print(f'  Original: {original_size:.1f} KB')
        print(f'  Updated: {new_size:.1f} KB')
        print(f'  SUCCESS: Decorative border added ({rarity} style)')
        
    except Exception as e:
        print(f'  ERROR: {e}')
        import traceback
        traceback.print_exc()

def main():
    """Process all placeholder card files in placeholders directory."""
    placeholders_dir = Path('assets/placeholders')
    
    # Find all placeholder card files
    card_files = sorted(
        list(placeholders_dir.glob('*.webp')) +
        list(placeholders_dir.glob('*.gif'))
    )
    
    if not card_files:
        print('No card files found in assets/placeholders/')
        return
    
    print(f'Enhancing borders on {len(card_files)} placeholder card images\n')
    print('=' * 60)
    
    for card_path in card_files:
        process_card(card_path)
        print()
    
    print('=' * 60)
    print(f'\nDone! {len(card_files)} cards now have beautiful decorative borders.')

if __name__ == '__main__':
    main()
