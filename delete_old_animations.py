#!/usr/bin/env python3
"""Delete old animated MP4 files so they regenerate with new effects."""

from pathlib import Path

def main():
    """Delete all old animated MP4 files."""
    placeholders_dir = Path('assets/placeholders')
    
    # Find and delete all animated MP4 files
    mp4_files = list(placeholders_dir.glob('*_animated.mp4'))
    
    if not mp4_files:
        print('No animated MP4 files found to delete.')
        return
    
    print(f'Deleting {len(mp4_files)} old animated MP4 files...\n')
    
    for mp4_file in mp4_files:
        try:
            mp4_file.unlink()
            print(f'  Deleted: {mp4_file.name}')
        except Exception as e:
            print(f'  ERROR deleting {mp4_file.name}: {e}')
    
    print(f'\nDone! Deleted {len(mp4_files)} files.')
    print('Animations will regenerate automatically when cards are created next time.')
    print('Or run the bot and use /test_normals to regenerate them.')

if __name__ == '__main__':
    main()
