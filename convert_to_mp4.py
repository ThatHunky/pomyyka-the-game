#!/usr/bin/env python3
"""Convert animated WebP and GIF files to MP4 format for Telegram."""

import subprocess
from pathlib import Path

def convert_to_mp4(input_path: Path, output_path: Path | None = None) -> Path | None:
    """
    Convert animated image (GIF/WebP) to MP4 using ffmpeg.
    
    Args:
        input_path: Path to animated GIF or WebP file
        output_path: Optional output path (defaults to input_path with .mp4 extension)
        
    Returns:
        Path to generated MP4 file, or None if conversion failed
    """
    if output_path is None:
        output_path = input_path.parent / f"{input_path.stem}.mp4"
    
    try:
        # For WebP files, convert to GIF first (ffmpeg has issues with animated WebP)
        temp_gif = None
        if input_path.suffix.lower() == '.webp':
            from PIL import Image
            try:
                # Convert WebP to GIF first
                temp_gif = input_path.parent / f"{input_path.stem}_temp.gif"
                webp_img = Image.open(input_path)
                
                if getattr(webp_img, 'is_animated', False):
                    frames = []
                    durations = []
                    frame_count = 0
                    
                    while True:
                        frames.append(webp_img.copy())
                        durations.append(webp_img.info.get('duration', 100))
                        frame_count += 1
                        try:
                            webp_img.seek(frame_count)
                        except EOFError:
                            break
                    
                    if frames:
                        frames[0].save(
                            temp_gif,
                            'GIF',
                            save_all=True,
                            append_images=frames[1:],
                            duration=durations,
                            loop=0,
                        )
                        input_path = temp_gif
                    else:
                        return None
                else:
                    return None
            except Exception as e:
                print(f'  WARNING: Failed to convert WebP to GIF first: {e}')
                return None
        
        # Use ffmpeg to convert to MP4
        # -movflags faststart: Optimize for streaming
        # -pix_fmt yuv420p: Ensure compatibility
        # -an: No audio track (silent video)
        # -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2": Ensure even dimensions (required for yuv420p)
        cmd = [
            'ffmpeg',
            '-i', str(input_path),
            '-movflags', 'faststart',
            '-pix_fmt', 'yuv420p',
            '-an',  # No audio
            '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',  # Ensure even dimensions
            '-y',  # Overwrite output file if exists
            str(output_path)
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        # Clean up temp GIF if created
        if temp_gif and temp_gif.exists():
            temp_gif.unlink()
        
        original_size = input_path.stat().st_size / 1024  # KB
        new_size = output_path.stat().st_size / 1024  # KB
        
        print(f'  Original: {original_size:.1f} KB')
        print(f'  MP4: {new_size:.1f} KB')
        print(f'  SUCCESS: {output_path.name}')
        
        return output_path
        
    except subprocess.CalledProcessError as e:
        print(f'  ERROR: ffmpeg failed: {e.stderr}')
        return None
    except FileNotFoundError:
        print(f'  ERROR: ffmpeg not found. Please install ffmpeg.')
        return None
    except Exception as e:
        print(f'  ERROR: {e}')
        import traceback
        traceback.print_exc()
        return None

def main():
    """Convert all animated files to MP4."""
    placeholders_dir = Path('assets/placeholders')
    
    # Find all animated files (GIF and animated WebP)
    animated_files = sorted(
        list(placeholders_dir.glob('*_animated.gif')) +
        list(placeholders_dir.glob('*_animated.webp'))
    )
    
    if not animated_files:
        print('No animated files found in assets/placeholders/')
        return
    
    print(f'Converting {len(animated_files)} animated files to MP4\n')
    print('=' * 60)
    
    converted_count = 0
    for animated_path in animated_files:
        print(f'Converting {animated_path.name}...')
        mp4_path = convert_to_mp4(animated_path)
        if mp4_path:
            converted_count += 1
        print()
    
    print('=' * 60)
    print(f'\nDone! Converted {converted_count} of {len(animated_files)} files to MP4 format.')

if __name__ == '__main__':
    main()
