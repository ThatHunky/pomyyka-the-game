#!/usr/bin/env python3
"""Regenerate card animations with new beautiful effects."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import directly to avoid import chain issues
import importlib.util
spec = importlib.util.spec_from_file_location(
    "card_animator",
    project_root / "services" / "card_animator.py"
)
card_animator_module = importlib.util.module_from_spec(spec)
sys.modules["card_animator"] = card_animator_module
spec.loader.exec_module(card_animator_module)

from database.enums import Rarity
CardAnimator = card_animator_module.CardAnimator

def main():
    """Regenerate all NORMAL card animations."""
    placeholders_dir = Path('assets/placeholders')
    animator = CardAnimator()
    
    # Cards to regenerate
    cards_to_animate = {
        'NORMAL_EPIC.webp': Rarity.EPIC,
        'NORMAL_LEGENDARY.webp': Rarity.LEGENDARY,
        'NORMAL_MYTHIC.webp': Rarity.MYTHIC,
    }
    
    print('Regenerating card animations with new beautiful effects\n')
    print('=' * 60)
    
    for card_name, rarity in cards_to_animate.items():
        card_path = placeholders_dir / card_name
        
        if not card_path.exists():
            print(f'WARNING: {card_name} not found, skipping...\n')
            continue
        
        print(f'Generating animation for {card_name} ({rarity.value})...')
        try:
            mp4_path = animator.generate_card_animation(
                card_path,
                rarity,
                total_frames=100,  # 100 frames for 5s animation
                duration=50,      # 50ms per frame = 20 fps
            )
            
            if mp4_path:
                print(f'  SUCCESS: {mp4_path.name}\n')
            else:
                print(f'  ERROR: Failed to generate animation\n')
        except Exception as e:
            print(f'  ERROR: {e}\n')
            import traceback
            traceback.print_exc()
    
    print('=' * 60)
    print('\nDone! All animations regenerated with new beautiful effects at 20 fps.')

if __name__ == '__main__':
    main()
