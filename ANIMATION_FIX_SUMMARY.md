# Animation Issues - Investigation & Fix Summary

## Problem Statement

Based on the user's screenshots and feedback:
- **Desktop Telegram**: Animations show as GIFs but don't autoplay
- **Mobile Telegram**: Animations appear broken and display as videos
- **User Comment**: "Трохи похуйовило бо незакінчені темплейти" (Things got a bit better because of incomplete templates)

## Root Cause Analysis

### Issue 1: MP4 Encoding Parameters
The MP4 files were generated without optimal parameters for Telegram compatibility:
- No explicit H.264 profile specified (Telegram prefers baseline/main)
- No H.264 level specified
- Missing proper streaming optimization flags

### Issue 2: Missing Telegram API Parameters
When sending animations via `answer_animation()`, the bot wasn't providing:
- `duration` parameter (helps Telegram know the video length)
- `width` and `height` parameters (helps with proper display)

### Issue 3: File Format Inconsistency
- Placeholder files were mixed (PNG and WebP)
- Generated cards were PNG format
- No standardization across the system

### Issue 4: Resolution
- No explicit resolution target
- Cards could be various sizes

## Solutions Implemented

### 1. Improved MP4 Encoding (`services/card_animator.py`)

**Before:**
```python
cmd = [
    'ffmpeg',
    '-framerate', str(fps),
    '-i', str(temp_dir / 'frame_%04d.png'),
    '-c:v', 'libx264',
    '-pix_fmt', 'yuv420p',
    '-movflags', 'faststart',
    '-an',
    '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2',
    '-y',
    str(mp4_path)
]
```

**After:**
```python
cmd = [
    'ffmpeg',
    '-framerate', str(fps),
    '-i', str(temp_dir / 'frame_%04d.webp'),
    '-c:v', 'libx264',
    '-profile:v', 'baseline',  # Maximum compatibility
    '-level', '3.0',  # H.264 level
    '-pix_fmt', 'yuv420p',
    '-movflags', '+faststart',
    '-vf', 'scale=1080:1920:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2',  # 1080p portrait
    '-preset', 'fast',
    '-an',
    '-y',
    str(mp4_path)
]
```

**Key Changes:**
- ✅ Added `-profile:v baseline` for maximum device compatibility
- ✅ Added `-level 3.0` for H.264 level specification
- ✅ Changed to WebP input frames (smaller, faster)
- ✅ Added 1080p scaling (1080x1920 portrait)
- ✅ Improved movflags: `+faststart` instead of just `faststart`

### 2. Created Animation Helper (`utils/animations.py`)

New utility functions that properly send animations with all required parameters:

```python
async def send_card_animation(
    message: Message,
    animation_path: Path,
    caption: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = "Markdown",
) -> None:
    """Send card animation with proper parameters for Telegram compatibility."""
    animation_file = FSInputFile(str(animation_path))
    
    # Get dimensions from base image or use 1080p default
    width, height = 1080, 1920  # Default 1080p portrait
    duration = 2  # 40 frames at 20fps = 2 seconds
    
    # Try to get actual dimensions from base WebP file
    base_image_path = animation_path.parent / animation_path.name.replace("_animated.mp4", ".webp")
    if base_image_path.exists():
        with Image.open(base_image_path) as img:
            width, height = img.size
    
    await message.answer_animation(
        animation=animation_file,
        caption=caption,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        duration=duration,  # ← NEW
        width=width,        # ← NEW
        height=height,      # ← NEW
    )
```

**Benefits:**
- ✅ Provides duration, width, height to Telegram
- ✅ Helps Telegram clients properly display and autoplay animations
- ✅ Centralizes animation sending logic
- ✅ Consistent behavior across all handlers

### 3. WebP Migration

**Changed Files:**
- `utils/images.py`: Save as `.webp` instead of `.png`
- `services/nano_banana.py`: Look for `.webp` placeholders
- `services/card_animator.py`: Use WebP for frame storage
- `utils/animations.py`: Look for `.webp` base images

**Benefits:**
- ✅ 25-35% smaller file sizes
- ✅ Better compression quality
- ✅ Faster processing (smaller files)
- ✅ Modern format support

### 4. 1080p Resolution Standard

All new cards and animations will be generated at 1080p resolution (1080x1920 portrait):
- Sharper, more detailed cards
- Better viewing experience on modern devices
- Consistent sizing across all cards

### 5. Updated Handlers

**Updated:**
- `handlers/admin_autocard.py`: Uses `send_card_animation()` helper
- `handlers/player.py`: Uses `send_card_animation_to_callback()` helper

**Result:**
- Consistent animation sending across the bot
- Proper parameters always included
- Better error handling

## Technical Details

### H.264 Profile & Level

**Profile: Baseline**
- Most compatible H.264 profile
- Supported by all devices (old and new)
- Slightly larger files but maximum compatibility

**Level: 3.0**
- Supports up to 720p at 30fps or 1080p at lower fps
- Perfect for our 1080p at 20fps animations
- Wide device support

### Telegram Animation Requirements

According to Telegram Bot API and community findings:
1. **Format**: MP4 (H.264) or GIF
2. **Size Limit**: 10MB for GIFs (animations)
3. **Autoplay**: Requires proper MIME type and parameters
4. **Duration**: Helps clients pre-allocate resources
5. **Dimensions**: Helps with proper rendering

### Why MP4 Instead of GIF?

- **File Size**: MP4 is 5-10x smaller than GIF for same quality
- **Quality**: H.264 provides better compression
- **Performance**: Faster to decode and display
- **Telegram Preference**: Telegram converts GIFs to MP4 internally anyway

## Migration Guide

### For Development/Testing

1. **Rebuild Docker Container** (if using Docker):
   ```bash
   docker-compose down
   docker-compose up --build -d
   ```

2. **Regenerate Placeholder Files**:
   - Convert all PNG placeholders to WebP
   - Ensure 1080p resolution (1080x1920)
   - Naming: `{BIOME}_{RARITY}.webp`

3. **Test Card Generation**:
   ```bash
   /autocard @username
   ```

4. **Verify Animation Playback**:
   - Check on desktop Telegram
   - Check on mobile Telegram (iOS and Android if possible)
   - Verify autoplay works
   - Verify loop works

### For Production Deployment

1. **Backup Existing Cards** (optional):
   ```bash
   cp -r media/cards media/cards_backup
   ```

2. **Deploy New Code**:
   ```bash
   git pull
   docker-compose up --build -d
   ```

3. **Regenerate Animations** (optional):
   ```bash
   python regenerate_animations.py
   ```

4. **Monitor Logs**:
   ```bash
   docker-compose logs -f bot
   ```

## Expected Results

### Desktop Telegram
- ✅ Animations should autoplay immediately
- ✅ Smooth looping
- ✅ Proper display size
- ✅ No "broken video" icons

### Mobile Telegram
- ✅ Animations should autoplay in chat
- ✅ No "play button" overlay
- ✅ Smooth playback
- ✅ Proper aspect ratio

### File Sizes (Estimated)
- **Static Card (WebP)**: ~200-400KB (was ~500-800KB as PNG)
- **Animated Card (MP4)**: ~500KB-1.5MB (40 frames at 1080p)
- **Total Savings**: ~30-40% reduction in storage

## Troubleshooting

### If Animations Still Don't Autoplay

1. **Check User Settings**:
   - Telegram → Settings → Data and Storage → Auto-Download Media
   - Telegram → Settings → Power Saving → Autoplay GIFs (should be ON)

2. **Check File Size**:
   ```python
   # In logs, look for:
   "Card animation generated successfully"
   # Check file_size_kb value
   ```

3. **Verify MP4 Format**:
   ```bash
   ffprobe media/cards/XXXXX_animated.mp4
   # Should show: h264 (Baseline), yuv420p
   ```

4. **Check Telegram API Response**:
   - Look for errors in bot logs
   - Verify no "Bad Request" errors

### If WebP Files Aren't Found

1. **Check Placeholder Directory**:
   ```bash
   ls -lh assets/placeholders/*.webp
   ```

2. **Verify File Sizes**:
   ```bash
   # All files should be > 1KB
   find assets/placeholders -name "*.webp" -size -1k
   ```

3. **Regenerate Missing Placeholders**:
   - Use AI Studio with prompts from `PROMPTS_FOR_AI_STUDIO.md`
   - Save as WebP format
   - Ensure 1080p resolution

## Performance Impact

### Positive
- ✅ Smaller WebP files = faster uploads to Telegram
- ✅ Faster frame processing (WebP encoding is fast)
- ✅ Less storage space required
- ✅ Better user experience (autoplay works)

### Negative
- ⚠️ 1080p = more pixels to process (but offset by WebP efficiency)
- ⚠️ Initial migration requires regenerating placeholders
- ⚠️ Slightly longer ffmpeg encoding time (higher resolution)

**Net Result**: Overall improvement in performance and user experience.

## Next Steps

1. **Test the Changes**:
   - Generate a new card with `/autocard`
   - Verify it's WebP format
   - Check animation playback on multiple devices

2. **Monitor User Feedback**:
   - Do animations autoplay now?
   - Any new issues reported?

3. **Optional Enhancements**:
   - Add thumbnail generation for animations
   - Implement progressive loading for large files
   - Add animation quality settings (low/medium/high)

## Files Changed

### Core Changes
- ✅ `services/card_animator.py` - Improved MP4 encoding
- ✅ `services/nano_banana.py` - WebP placeholder lookup
- ✅ `services/art_forge.py` - Updated docstrings
- ✅ `utils/images.py` - WebP file saving
- ✅ `utils/animations.py` - NEW: Animation helper functions

### Handler Updates
- ✅ `handlers/admin_autocard.py` - Uses animation helper
- ✅ `handlers/player.py` - Uses animation helper

### Documentation
- ✅ `ANIMATION_ISSUES_ANALYSIS.md` - Root cause analysis
- ✅ `WEBP_1080P_MIGRATION_SUMMARY.md` - Migration details
- ✅ `ANIMATION_FIX_SUMMARY.md` - This file

## Conclusion

The animation issues were caused by:
1. Suboptimal MP4 encoding parameters
2. Missing Telegram API parameters (duration, width, height)
3. Inconsistent file formats

The fixes address all these issues by:
1. Using H.264 baseline profile with proper flags
2. Providing all required parameters to Telegram
3. Standardizing on WebP format
4. Upgrading to 1080p resolution

**Expected Result**: Animations should now autoplay properly on both desktop and mobile Telegram clients.
