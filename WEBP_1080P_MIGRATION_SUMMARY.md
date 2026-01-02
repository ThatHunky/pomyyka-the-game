# WebP + 1080p Migration Summary

## Changes Made

### 1. Image Format Migration (PNG → WebP)

#### `utils/images.py`
- Changed `save_generated_image()` to save as `.webp` instead of `.png`
- Updated filename generation: `{uuid}.webp`
- Updated docstrings to reflect WebP format

#### `services/nano_banana.py`
- Updated `_get_placeholder_path()` to look for `.webp` files first
- Changed placeholder path from `{biome}_{rarity}.png` to `{biome}_{rarity}.webp`
- Fallback still uses `NORMAL_{rarity}.webp`

### 2. Animation Resolution Upgrade (1080p)

#### `services/card_animator.py`
- Changed frame saving from PNG to WebP format
- Updated ffmpeg input pattern from `frame_%04d.png` to `frame_%04d.webp`
- Added 1080p scaling to ffmpeg command:
  ```bash
  -vf 'scale=1080:1920:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2'
  ```
- This scales to 1080x1920 (portrait) while maintaining aspect ratio and ensuring even dimensions

#### `utils/animations.py`
- Updated `send_card_animation()` to look for `.webp` base images
- Changed from `.png` to `.webp` in path resolution
- Set default dimensions to 1080x1920 when file not found

### 3. Animation Playback Fixes

#### `services/card_animator.py`
- Added H.264 baseline profile for maximum compatibility: `-profile:v baseline`
- Added H.264 level specification: `-level 3.0`
- Improved movflags: `-movflags +faststart`
- Changed WebP quality settings: `quality=95, method=4`

#### `utils/animations.py` (NEW FILE)
- Created helper function `send_card_animation()` to properly send animations with:
  - Duration parameter (2 seconds)
  - Width and height parameters (from base image or default 1080x1920)
  - Proper FSInputFile handling
- Created `send_card_animation_to_callback()` for callback query responses

#### `handlers/admin_autocard.py`
- Imported and used `send_card_animation()` helper
- Replaced direct `answer_animation()` calls with helper function

#### `handlers/player.py`
- Imported `send_card_animation_to_callback()` helper
- Updated to use helper function for callback responses

### 4. Documentation

#### `ANIMATION_ISSUES_ANALYSIS.md` (NEW FILE)
- Documented root cause analysis of animation playback issues
- Listed identified problems:
  1. Missing loop flag in MP4
  2. Missing duration parameter
  3. Profile/level issues
  4. Filename extension confusion
  5. Missing width/height parameters
- Proposed solutions and implementation order

## Migration Steps Required

### For Existing Deployments

1. **Regenerate Placeholder Files**
   - Convert all PNG placeholders to WebP format
   - Ensure all files follow naming: `{BIOME}_{RARITY}.webp`
   - Minimum file size: 1KB
   - Resolution: 1080x1920 (portrait)

2. **Regenerate Existing Card Images**
   - Existing PNG cards will still work
   - New cards will be generated as WebP
   - Optional: Run migration script to convert existing cards

3. **Regenerate Animations**
   - Run `regenerate_animations.py` to recreate MP4 files with new encoding
   - New animations will have proper loop, profile, and 1080p resolution

### For New Installations

- All placeholder files must be WebP format
- Resolution should be 1080x1920 (portrait)
- Follow naming convention: `{BIOME}_{RARITY}.webp`

## Benefits

1. **Smaller File Sizes**: WebP typically 25-35% smaller than PNG
2. **Better Quality**: WebP provides better compression at same quality
3. **Higher Resolution**: 1080p provides sharper, more detailed cards
4. **Better Compatibility**: H.264 baseline profile works on all devices
5. **Proper Autoplay**: Duration/width/height parameters help Telegram clients

## Potential Issues

1. **Backward Compatibility**: Old PNG files will still work, but new system expects WebP
2. **Storage**: 1080p files are larger than lower resolutions (but WebP helps offset this)
3. **Processing Time**: Higher resolution may take slightly longer to generate
4. **ffmpeg Dependency**: Requires ffmpeg with WebP support

## Testing Checklist

- [ ] Generate new card with WebP output
- [ ] Verify placeholder fallback works (biome → NORMAL)
- [ ] Test animation generation at 1080p
- [ ] Verify MP4 autoplay on desktop Telegram
- [ ] Verify MP4 autoplay on mobile Telegram
- [ ] Test animation playback in different Telegram clients
- [ ] Verify file sizes are reasonable
- [ ] Check that old PNG cards still display correctly
