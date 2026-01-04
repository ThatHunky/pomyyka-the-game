# Card Generation Options - Implementation Summary

## Overview
Successfully implemented interactive card generation options for the `/autocard` command, allowing admins to regenerate images and edit card fields before final approval.

## Changes Made

### 1. Updated Blueprint Storage
**File**: `handlers/admin_autocard.py`
- Added `image_url` to the blueprint data stored in Redis
- This allows us to track the current image and replace it during regeneration

### 2. Extended Callback Actions
**File**: `handlers/admin_autocard.py`
- Updated `AutocardCallback` class to support 4 actions: `approve`, `cancel`, `regenerate`, `edit`
- Added FSM states for card editing (`CardEditStates`)

### 3. Updated Keyboard Layout
**File**: `handlers/admin_autocard.py`
- Changed from 2 buttons to 4 buttons:
  - 🔄 Перегенерувати Зображення (Regenerate Image)
  - ✏️ Редагувати Поля (Edit Fields)
  - ✅ Затвердити та Видати (Approve and Add)
  - ❌ Скасувати (Cancel)

### 4. New Helper Functions
**File**: `handlers/admin_autocard.py`

#### `_regenerate_card_image(blueprint_data, bot)`
- Regenerates card image from blueprint data
- Uses `ArtForgeService` to generate new image
- Keeps the same blueprint (name, stats, lore)
- Returns new image path or None on failure

#### `_send_card_preview(message, blueprint_data, image_url, blueprint_id)`
- Sends card preview with image and caption
- Handles different card types (animated MP4 for rare cards, static images for common)
- Creates keyboard with all 4 action buttons
- Reusable for both initial generation and regeneration

### 5. New Callback Handlers

#### `handle_autocard_regenerate(callback, callback_data, bot)`
- Handles "Regenerate Image" button press
- Retrieves blueprint from Redis
- Deletes old message
- Regenerates image using `_regenerate_card_image()`
- Updates blueprint in Redis with new image path
- Sends new preview with same 4-button keyboard

#### `handle_autocard_edit(callback, callback_data, state)`
- Handles "Edit Fields" button press
- Shows current card values
- Asks admin to send JSON with fields to update
- Enters FSM state `CardEditStates.waiting_for_json`

#### `process_card_edit_json(message, state, bot)`
- FSM handler for processing JSON input
- Validates JSON format
- Validates field values (biome, rarity, stats range)
- Updates blueprint in Redis
- Automatically regenerates image with new data
- Sends new preview with 4-button keyboard
- Clears FSM state

### 6. Updated Imports
**File**: `handlers/admin_autocard.py`
- Added `FSMContext`, `State`, `StatesGroup` from aiogram.fsm
- Added `Rarity` from database.enums

## How It Works

### Flow 1: Regenerate Image
1. Admin runs `/autocard`
2. AI generates blueprint + image
3. Admin clicks "🔄 Перегенерувати Зображення"
4. Bot deletes old message
5. Bot generates new image with same blueprint
6. Bot shows new preview with same 4 buttons
7. Admin can regenerate again or approve/cancel

### Flow 2: Edit Fields
1. Admin runs `/autocard`
2. AI generates blueprint + image
3. Admin clicks "✏️ Редагувати Поля"
4. Bot shows current values and asks for JSON
5. Admin sends JSON like: `{"name": "New Name", "atk": 75, "def": 60}`
6. Bot validates JSON and updates blueprint
7. Bot automatically regenerates image with new data
8. Bot shows new preview with 4 buttons
9. Admin can edit again, regenerate, or approve/cancel

### Flow 3: Approve (unchanged)
1. Admin clicks "✅ Затвердити та Видати"
2. Bot saves card to database
3. Bot issues card to target user
4. Bot cleans up Redis data

### Flow 4: Cancel (unchanged)
1. Admin clicks "❌ Скасувати"
2. Bot cleans up Redis data
3. Bot shows cancellation message

## Editable Fields

The following fields can be edited via JSON:
- `name` - Card name (string)
- `biome` - Biome type (NORMAL, FIRE, WATER, GRASS, PSYCHIC, TECHNO, DARK)
- `rarity` - Rarity level (COMMON, RARE, EPIC, LEGENDARY, MYTHIC)
- `atk` - Attack stat (0-100)
- `def` - Defense stat (0-100)
- `lore` - Card lore/description (string)
- `raw_image_prompt_en` - Image generation prompt (English)
- `dominant_color_hex` - Primary color for gradients (hex format)
- `accent_color_hex` - Secondary color for highlights (hex format)
- `print_date` - Print date (MM/YYYY format)

## Testing Instructions

### Manual Testing Checklist
1. ✅ Run `/autocard` with a photo and verify 4 buttons appear
2. ⏳ Click "🔄 Перегенерувати Зображення" and verify new image is generated
3. ⏳ Click "✏️ Редагувати Поля", send JSON, verify image regenerates
4. ⏳ Click "✅ Затвердити та Видати" and verify card is saved
5. ⏳ Click "❌ Скасувати" and verify session is cleaned up
6. ⏳ Test with rare cards (animated MP4) and common cards (static images)
7. ⏳ Verify Redis TTL doesn't expire during editing

### Example JSON for Testing
```json
{"name": "Тестова Картка", "atk": 85, "def": 70}
```

```json
{"biome": "FIRE", "rarity": "EPIC", "atk": 90}
```

```json
{"lore": "Новий опис для картки з оновленою історією."}
```

## Error Handling

The implementation includes comprehensive error handling:
- Blueprint not found in Redis → Shows error, prompts to start over
- Image generation fails → Shows error, keeps blueprint, allows retry
- Invalid JSON in edit flow → Shows validation error with example
- Invalid field values → Shows specific validation error
- Admin permissions checked on every callback
- FSM state cleared on errors to prevent stuck states

## Notes

- User/group photos are not stored in Redis (memory efficiency trade-off)
- Regenerated images won't include user/group photos from original generation
- Redis TTL is set to 1 hour (3600 seconds) for blueprint data
- FSM state is automatically cleared after successful edit or on error
- Old messages are deleted when regenerating to avoid clutter
- All admin messages are in Ukrainian as per project requirements

## Files Modified

1. `handlers/admin_autocard.py` - Main implementation (all changes)

## Dependencies

No new dependencies added. Uses existing:
- `aiogram.fsm` for state management
- `services.art_forge.ArtForgeService` for image generation
- `services.nano_banana.NanoBananaService` for placeholder paths
- `services.session_manager.SessionManager` for Redis storage

## Deployment

The implementation is ready for deployment:
1. Code changes are complete
2. No database migrations required
3. No new environment variables needed
4. Bot restart required to load new handlers
5. Redis data structure is backward compatible

## Next Steps

1. Manual testing with real bot instance
2. Monitor Redis memory usage with blueprint storage
3. Consider adding undo/redo functionality if needed
4. Consider adding preview of changes before regeneration
5. Add unit tests for new handlers (optional)
