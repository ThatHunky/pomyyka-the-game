# Nano Banana Pro Card Placeholder Specification

## Overview
Placeholder PNG image for Nano Banana Pro cards that resembles Pokemon TCG cards. This placeholder will be used for generative editing, so all text/data areas should be clearly defined and editable.

## Card Layout Elements

### 1. **Card Name** (Top Center)
- **Field**: `template.name` (Ukrainian)
- **Location**: Top center of card, below border
- **Format**: Large, bold text
- **Placeholder Example**: `"НАЗВА КАРТКИ"` or `"Card Name"`

### 2. **Rarity Indicator** (Top Right/Corner)
- **Field**: `template.rarity` (Rarity enum)
- **Values**: 
  - `Common` (⚪)
  - `Rare` (🔵)
  - `Epic` (🟣)
  - `Legendary` (🟠)
  - `Mythic` (🔴)
- **Location**: Top right corner or near name
- **Format**: Emoji + text or symbol indicator
- **Placeholder Example**: `"🔵 RARE"` or rarity symbol/badge

### 3. **Biome Type** (Left Side/Top)
- **Field**: `template.biome_affinity` (BiomeType enum)
- **Values** (Ukrainian):
  - `Звичайний` (🌍)
  - `Вогняний` (🔥)
  - `Водний` (💧)
  - `Трав'яний` (🌿)
  - `Психічний` (🔮)
  - `Техно` (⚙️)
  - `Темний` (🌑)
- **Location**: Top left or left side, with emoji indicator
- **Format**: Emoji + Ukrainian text
- **Placeholder Example**: `"🔥 Вогняний"` or biome symbol/badge

### 4. **Artwork Area** (Center)
- **Field**: Main visual area (generated from `raw_image_prompt_en`)
- **Location**: Large center section of card
- **Format**: Illustration area with borders/frame
- **Placeholder**: Blank area or placeholder illustration frame
- **Style**: Pokemon Trading Card Game style

### 5. **Attack Stat (ATK)** (Bottom Left/Corner)
- **Field**: `stats['atk']` (integer 0-100)
- **Location**: Bottom left corner or bottom section
- **Format**: `"⚔️ ATK: 50"` or `"⚔️ 50"`
- **Placeholder Example**: `"⚔️ ATK: 00"` or `"⚔️ 00"`

### 6. **Defense Stat (DEF)** (Bottom Right/Corner)
- **Field**: `stats['def']` (integer 0-100)
- **Location**: Bottom right corner or bottom section
- **Format**: `"🛡️ DEF: 30"` or `"🛡️ 30"`
- **Placeholder Example**: `"🛡️ DEF: 00"` or `"🛡️ 00"`

### 7. **Meme Stat (Optional)** (Bottom Center)
- **Field**: `stats.get('meme')` (integer 0-100, optional)
- **Location**: Bottom center or between ATK/DEF
- **Format**: `"🎭 MEME: 75"` or `"🎭 75"`
- **Placeholder Example**: `"🎭 MEME: 00"` or `"🎭 00"`
- **Note**: This stat exists in blueprints but may not always be displayed

### 8. **Lore/Flavor Text** (Bottom, Above Stats)
- **Field**: `lore_ua` (Ukrainian, 2 sentences max, ~500 chars)
- **Location**: Bottom section, above stats, in italic/smaller font
- **Format**: Ukrainian text in italic, 2 lines max
- **Placeholder Example**: `"Це описова частина картки. Вона містить лор та історію персонажа або об'єкта."`

## Visual Style Requirements

### Art Style
- **Style**: Pokemon Trading Card Game style illustration, vibrant and colorful art style
- **Border**: Ornate border design elements (Pokemon TCG-like)
- **Quality**: Digital painting, masterpiece, highly detailed, 8k resolution
- **Lighting**: Cinematic lighting, rich textures

### Card Format
- **Aspect Ratio**: Standard trading card format (recommended: 2.5" x 3.5" ratio, e.g., 500x700px or 1000x1400px)
- **Layout**: Vertical/portrait orientation
- **Border**: Decorative frame around entire card
- **Background**: Card background should complement the artwork area

## Text Labels & Formatting

### Language
- **Card Name**: Ukrainian
- **Biome**: Ukrainian
- **Rarity**: English (Common, Rare, Epic, Legendary, Mythic)
- **Stats Labels**: Can be Ukrainian (АТАКА, ЗАХИСТ, МЕМНІСТЬ) or English (ATK, DEF, MEME)
- **Lore**: Ukrainian

### Typography Recommendations
- **Card Name**: Large, bold, prominent
- **Rarity/Biome**: Medium size, clear but not overwhelming
- **Stats**: Medium-bold, readable numbers
- **Lore**: Small-italic, readable but secondary

## Placeholder Values for Generation

When generating the placeholder, use these example values:

```
Card Name: "ПРИКЛАД КАРТКИ"
Rarity: "Rare" (🔵)
Biome: "Вогняний" (🔥)
Attack: 50
Defense: 30
Meme: 60 (if included)
Lore: "Це приклад лору картки. Він описує персонажа або об'єкт у двох реченнях."
```

## Data Fields Summary

| Element | Database Field | Type | Range/Values | Required |
|---------|---------------|------|--------------|----------|
| Card Name | `template.name` | string | Ukrainian text | ✅ Yes |
| Rarity | `template.rarity` | enum | Common, Rare, Epic, Legendary, Mythic | ✅ Yes |
| Biome | `template.biome_affinity` | enum | Звичайний, Вогняний, Водний, Трав'яний, Психічний, Техно, Темний | ✅ Yes |
| Attack | `stats['atk']` | integer | 0-100 | ✅ Yes |
| Defense | `stats['def']` | integer | 0-100 | ✅ Yes |
| Meme | `stats.get('meme')` | integer | 0-100 | ❌ Optional |
| Lore | `lore_ua` (blueprint) | string | Ukrainian, max 500 chars, 2 sentences | ❌ Optional |

## Notes for AI Studio Generation

1. **Clear Text Areas**: Make sure all text areas are clearly defined and can be easily edited/replaced
2. **Editable Regions**: The placeholder should allow for:
   - Replacing artwork area with generated images
   - Updating text fields (name, stats, lore)
   - Changing rarity/biome indicators
3. **Consistent Layout**: Maintain consistent positioning so the generative editing process knows where to place each element
4. **Pokemon TCG Aesthetic**: Use similar layout structure to Pokemon TCG cards (name top, artwork center, stats bottom, border frame)
5. **Pokemon TCG Theme**: The style should match Pokemon Trading Card Game aesthetic - clean, vibrant, and colorful
