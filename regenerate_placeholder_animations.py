#!/usr/bin/env python3
"""Regenerate placeholder card animations - simple version that imports only what's needed."""

import sys
from pathlib import Path

# Simple approach: just delete old files and let the bot regenerate them
# Or we can manually call the animator if we have the dependencies

def main():
    """Delete old animations so they regenerate."""
    placeholders_dir = Path('assets/placeholders')
    
    # Delete old MP4, GIF, and animated WebP files
    files_to_delete = (
        list(placeholders_dir.glob('*_animated.mp4')) +
        list(placeholders_dir.glob('*_animated.gif')) +
        list(placeholders_dir.glob('*_animated.webp'))
    )
    
    if not files_to_delete:
        print('No animated files found to delete.')
        return
    
    print(f'Deleting {len(files_to_delete)} old animated files...\n')
    
    deleted = 0
    for file in files_to_delete:
        try:
            file.unlink()
            print(f'  Deleted: {file.name}')
            deleted += 1
        except Exception as e:
            print(f'  ERROR deleting {file.name}: {e}')
    
    print(f'\nDone! Deleted {deleted} files.')
    print('\nTo regenerate with new effects:')
    print('1. Restart the bot (animations auto-generate on card creation)')
    print('2. Or create a new Epic/Legendary/Mythic card')
    print('3. Or wait for the next card generation')

if __name__ == '__main__':
    main()
