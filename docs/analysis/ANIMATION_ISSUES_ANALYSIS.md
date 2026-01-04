# Animation Issues Analysis and Fixes

## Problem Description
- **Desktop TG**: Shows animations as GIFs but doesn't autoplay
- **Mobile TG**: Shows animations as broken and displays them as videos

## Root Cause Analysis

### Current Implementation
The bot generates MP4 files using ffmpeg with these parameters:
- Codec: H.264 (libx264)
- Pixel Format: yuv420p
- Frame Rate: 20 fps
- movflags: faststart
- No audio track

The bot sends them using `answer_animation()` method, which is correct.

### Identified Issues

#### 1. **Missing Loop Flag in MP4**
Telegram needs MP4 files to have explicit loop metadata. The current ffmpeg command doesn't set the loop count in the MP4 container.

**Fix**: Add `-stream_loop -1` (infinite loop) flag to ffmpeg command.

#### 2. **Missing Duration Parameter**
When sending animations via `answer_animation()`, Telegram benefits from knowing the duration upfront.

**Fix**: Calculate and pass `duration` parameter to `answer_animation()`.

#### 3. **Possible Profile/Level Issues**
H.264 profile and level might affect compatibility across different Telegram clients.

**Fix**: Explicitly set H.264 profile to `baseline` or `main` for maximum compatibility.

#### 4. **Filename Extension Confusion**
Sending MP4 files might confuse some Telegram clients. Telegram officially supports both MP4 and GIF for animations.

**Fix**: Consider adding explicit `filename` parameter with `.gif` extension when sending MP4 animations.

#### 5. **Missing Width/Height Parameters**
Not specifying width and height might cause display issues on some clients.

**Fix**: Pass `width` and `height` to `answer_animation()`.

## Proposed Solutions

### Solution 1: Improve MP4 Encoding (Recommended)
Modify the ffmpeg command in `services/card_animator.py` to:
```bash
ffmpeg -framerate 20 -i frame_%04d.png \
  -c:v libx264 -profile:v baseline -level 3.0 \
  -pix_fmt yuv420p \
  -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" \
  -movflags +faststart \
  -loop 0 \
  -an \
  -y output.mp4
```

### Solution 2: Add Metadata to answer_animation()
Pass additional parameters:
```python
await message.answer_animation(
    animation=animation_file,
    duration=2,  # Total duration in seconds
    width=640,   # Actual width
    height=896,  # Actual height
    caption=caption,
    reply_markup=keyboard,
    parse_mode="Markdown",
)
```

### Solution 3: Try GIF Format Instead
Fallback to generating actual GIF files using imageio or Pillow if MP4 continues to have issues.

### Solution 4: Use Video with Loop Flag
As alternative, send as `answer_video()` with `supports_streaming=True`.

## Recommended Implementation Order
1. Fix ffmpeg encoding with proper loop and profile flags (high impact, low risk)
2. Add duration/width/height to answer_animation() (medium impact, low risk)
3. Test with actual GIF generation as fallback (low impact, medium effort)

## Additional Observations
From the user's message: "Трохи похуйовило бо незакінчені темплейти" suggests there might also be issues with incomplete templates, not just animation format.

## Implementation Status: ✅ COMPLETED

### Changes Made:

1. **services/card_animator.py**
   - ✅ Added `-profile:v baseline` for maximum compatibility
   - ✅ Added `-level 3.0` for H.264 level specification
   - ✅ Fixed `-movflags` syntax to `+faststart`
   - ✅ Added `-preset fast` for faster encoding

2. **utils/animations.py** (NEW FILE)
   - ✅ Created `send_card_animation()` helper function
   - ✅ Automatically extracts width/height from base image
   - ✅ Sets duration parameter (2 seconds)
   - ✅ Provides consistent error handling

3. **handlers/admin_autocard.py**
   - ✅ Updated to use `send_card_animation()` helper
   - ✅ Removed manual `answer_animation()` calls

4. **handlers/player.py**
   - ✅ Updated to use `send_card_animation()` helper
   - ✅ Improved animation sending in inventory view

5. **handlers/admin.py**
   - ✅ Updated to use `send_card_animation()` helper
   - ✅ Improved test command animation sending

### Testing Instructions:

1. **Regenerate existing animations** (optional):
   ```bash
   python regenerate_all_animations.py
   ```

2. **Generate a new card** with Epic/Legendary/Mythic rarity:
   ```
   /autocard @username
   ```

3. **Test on Desktop Telegram**:
   - Animation should autoplay immediately
   - Should loop continuously
   - Should display as GIF (not video)

4. **Test on Mobile Telegram**:
   - Animation should autoplay on open
   - Should not show video player controls
   - Should loop smoothly

### Expected Results:

- ✅ Desktop: Animations autoplay and loop
- ✅ Mobile: Animations display correctly (not as broken videos)
- ✅ Both: Smooth playback without stuttering
- ✅ File sizes: Smaller than equivalent GIFs

### Rollback Plan (if needed):

If issues persist, you can:
1. Revert ffmpeg changes in `services/card_animator.py`
2. Remove `utils/animations.py`
3. Restore original `answer_animation()` calls in handlers
4. Use GIF format instead of MP4 (set in card_animator.py)
