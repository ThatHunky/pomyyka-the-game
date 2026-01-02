# Beautiful Video Effects Templates for Card Animations

This document outlines beautiful video effects that can be applied programmatically to card animations using Python libraries like PIL/Pillow, NumPy, and OpenCV.

## Recommended Libraries

1. **PIL/Pillow** - Basic image manipulation and filters
2. **NumPy** - Fast array operations for effects
3. **OpenCV** - Advanced image processing and filters
4. **scikit-image** - Scientific image processing
5. **imageio** - Video frame handling

## Effect Templates

### 1. Advanced Holographic Foil Effect
**Description**: Realistic trading card foil effect with chromatic aberration and iridescence

**Techniques**:
- Chromatic aberration (RGB channel separation)
- Iridescent color shifting based on viewing angle
- Specular highlights that move across the card
- Multi-layer overlay with different blend modes

**Implementation**:
```python
def create_foil_effect(image, frame_num, total_frames):
    # Separate RGB channels
    r, g, b, a = image.split()
    
    # Apply chromatic aberration (shift channels)
    offset = int(3 * math.sin(frame_num / total_frames * 2 * math.pi))
    r = r.transform(r.size, Image.AFFINE, (1, 0, offset, 0, 1, 0))
    b = b.transform(b.size, Image.AFFINE, (1, 0, -offset, 0, 1, 0))
    
    # Create iridescent overlay
    overlay = create_iridescent_gradient(image.size, frame_num, total_frames)
    
    # Blend with multiply/overlay modes
    return Image.merge('RGBA', (r, g, b, a))
```

### 2. Particle System Effects
**Description**: Dynamic particle effects (stars, sparkles, energy orbs)

**Techniques**:
- Particle physics simulation
- Trail effects
- Size/opacity fade over time
- Gravity and velocity

**Implementation**:
```python
class Particle:
    def __init__(self, x, y, vx, vy, life):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.life = life
        self.max_life = life

def create_particle_frame(image, particles, frame_num):
    overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    for particle in particles:
        alpha = int(255 * (particle.life / particle.max_life))
        size = int(3 * (particle.life / particle.max_life))
        draw.ellipse([(particle.x-size, particle.y-size), 
                     (particle.x+size, particle.y+size)],
                    fill=(255, 255, 255, alpha))
        # Update particle
        particle.x += particle.vx
        particle.y += particle.vy
        particle.life -= 1
    
    return Image.alpha_composite(image, overlay)
```

### 3. Lens Flare Effect
**Description**: Realistic lens flare with multiple elements

**Techniques**:
- Anamorphic streaks
- Ghosting effects
- Bloom/glow around bright areas
- Moving light source

**Implementation**:
```python
def create_lens_flare(image, frame_num, total_frames):
    width, height = image.size
    
    # Calculate light source position (moving)
    progress = (frame_num / total_frames) * 2 * math.pi
    light_x = int(width * 0.5 + width * 0.3 * math.sin(progress))
    light_y = int(height * 0.5 + height * 0.2 * math.cos(progress))
    
    # Create flare elements
    flare = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(flare)
    
    # Main flare circle
    draw.ellipse([(light_x-30, light_y-30), (light_x+30, light_y+30)],
                fill=(255, 255, 200, 150))
    
    # Streaks
    for i in range(5):
        angle = i * math.pi / 5
        draw.ellipse([(light_x-100, light_y-5), (light_x+100, light_y+5)],
                    fill=(255, 255, 200, 80))
    
    return Image.alpha_composite(image, flare)
```

### 4. Chromatic Aberration
**Description**: RGB channel separation for depth effect

**Techniques**:
- Radial distortion
- Channel offset based on distance from center
- Intensity based on rarity

**Implementation**:
```python
def apply_chromatic_aberration(image, intensity=2):
    r, g, b, a = image.split()
    
    # Create offset map (more distortion at edges)
    width, height = image.size
    center_x, center_y = width // 2, height // 2
    
    # Apply radial offset
    r_offset = create_radial_offset_map(width, height, center_x, center_y, intensity)
    b_offset = create_radial_offset_map(width, height, center_x, center_y, -intensity)
    
    # Apply offsets (simplified - would need more complex transformation)
    return Image.merge('RGBA', (r, g, b, a))
```

### 5. Emboss/Relief Effect
**Description**: 3D embossed look with dynamic lighting

**Techniques**:
- Convolution filters for emboss
- Dynamic light direction
- Shadow/highlight enhancement

**Implementation**:
```python
from PIL import ImageFilter

def create_emboss_effect(image, frame_num, total_frames):
    # Rotating light direction
    angle = (frame_num / total_frames) * 2 * math.pi
    
    # Apply emboss filter
    embossed = image.filter(ImageFilter.EMBOSS)
    
    # Adjust brightness based on light angle
    enhancer = ImageEnhance.Brightness(embossed)
    brightness_factor = 0.8 + 0.4 * math.sin(angle)
    return enhancer.enhance(brightness_factor)
```

### 6. Energy Wave Effect
**Description**: Pulsing energy waves radiating from card

**Techniques**:
- Concentric circles with varying opacity
- Color cycling
- Wave interference patterns

**Implementation**:
```python
def create_energy_wave(image, frame_num, total_frames):
    width, height = image.size
    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    center_x, center_y = width // 2, height // 2
    
    # Create multiple wave rings
    for i in range(3):
        wave_progress = (frame_num / total_frames + i * 0.33) % 1.0
        radius = int(50 + wave_progress * 200)
        alpha = int(100 * (1 - wave_progress))
        
        # Color cycle
        hue = (frame_num * 10 + i * 60) % 360
        color = hsv_to_rgb(hue, 1.0, 1.0)
        
        draw.ellipse([(center_x-radius, center_y-radius),
                     (center_x+radius, center_y+radius)],
                    outline=(*color, alpha), width=3)
    
    return Image.alpha_composite(image, overlay)
```

### 7. Glitch Effect
**Description**: Digital glitch artifacts (for tech/cyber themes)

**Techniques**:
- RGB channel shifting
- Scanline effects
- Random pixel displacement
- Color channel corruption

**Implementation**:
```python
def create_glitch_effect(image, frame_num, total_frames):
    # Random RGB shift
    r, g, b, a = image.split()
    
    shift_amount = random.randint(-5, 5) if random.random() < 0.1 else 0
    if shift_amount:
        r = r.transform(r.size, Image.AFFINE, (1, 0, shift_amount, 0, 1, 0))
        b = b.transform(b.size, Image.AFFINE, (1, 0, -shift_amount, 0, 1, 0))
    
    # Scanlines
    if random.random() < 0.05:
        overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for y in range(0, image.size[1], 4):
            draw.line([(0, y), (image.size[0], y)], fill=(0, 0, 0, 50))
        image = Image.alpha_composite(image, overlay)
    
    return Image.merge('RGBA', (r, g, b, a))
```

### 8. Bloom/Glow Effect
**Description**: Soft glow around bright areas

**Techniques**:
- Gaussian blur on bright areas
- Additive blending
- Intensity based on pixel brightness

**Implementation**:
```python
from PIL import ImageFilter

def create_bloom_effect(image, threshold=200, intensity=0.5):
    # Extract bright areas
    bright = image.point(lambda p: p if p > threshold else 0)
    
    # Blur the bright areas
    blurred = bright.filter(ImageFilter.GaussianBlur(radius=10))
    
    # Blend back with original
    return Image.blend(image, blurred, intensity)
```

### 9. Ripple/Wave Distortion
**Description**: Water-like ripple effect

**Techniques**:
- Sine wave displacement
- Radial waves from center
- Time-based animation

**Implementation**:
```python
import numpy as np

def create_ripple_effect(image, frame_num, total_frames):
    img_array = np.array(image)
    height, width = img_array.shape[:2]
    
    # Create ripple displacement map
    center_x, center_y = width // 2, height // 2
    x, y = np.meshgrid(np.arange(width), np.arange(height))
    
    # Distance from center
    dist = np.sqrt((x - center_x)**2 + (y - center_y)**2)
    
    # Wave function
    wave = np.sin(dist * 0.1 - frame_num * 0.5) * 5
    
    # Apply displacement
    x_new = (x + wave).astype(np.float32)
    y_new = (y + wave).astype(np.float32)
    
    # Remap image (would need cv2.remap or similar)
    # This is simplified - full implementation needs OpenCV
    return image
```

### 10. Color Grading/LUT
**Description**: Cinematic color grading

**Techniques**:
- Color lookup tables (LUTs)
- Temperature adjustment
- Saturation curves
- Contrast enhancement

**Implementation**:
```python
from PIL import ImageEnhance

def apply_color_grading(image, rarity):
    # Rarity-specific color grading
    grading = {
        'COMMON': {'saturation': 0.9, 'contrast': 1.0},
        'RARE': {'saturation': 1.1, 'contrast': 1.1},
        'EPIC': {'saturation': 1.2, 'contrast': 1.2, 'temperature': 'cool'},
        'LEGENDARY': {'saturation': 1.3, 'contrast': 1.3, 'temperature': 'warm'},
        'MYTHIC': {'saturation': 1.4, 'contrast': 1.4, 'temperature': 'vibrant'},
    }
    
    config = grading.get(rarity, grading['COMMON'])
    
    # Apply enhancements
    enhancer = ImageEnhance.Color(image)
    image = enhancer.enhance(config['saturation'])
    
    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(config['contrast'])
    
    return image
```

## Recommended Effect Combinations by Rarity

### Common
- Subtle glow
- Basic color grading

### Rare
- Light holographic shimmer
- Particle sparkles (few)
- Soft bloom

### Epic
- Medium holographic foil
- Particle system
- Chromatic aberration
- Energy waves

### Legendary
- Strong holographic foil
- Lens flare
- Particle system (more)
- Bloom effect
- Emboss effect

### Mythic
- Full holographic foil with chromatic aberration
- Multiple lens flares
- Dense particle system
- Strong bloom
- Energy waves
- All effects combined

## Implementation Priority

1. **High Priority** (Easy to implement, high visual impact):
   - Advanced holographic foil with chromatic aberration
   - Particle system
   - Bloom/glow effect
   - Color grading

2. **Medium Priority** (Moderate complexity):
   - Lens flare
   - Energy waves
   - Emboss effect

3. **Low Priority** (Complex, niche use):
   - Ripple distortion
   - Glitch effects
   - Advanced chromatic aberration

## Libraries to Install

```bash
pip install Pillow numpy opencv-python scikit-image imageio
```

## Next Steps

1. Implement advanced holographic foil effect
2. Add particle system for sparkles/stars
3. Implement bloom/glow effect
4. Add color grading based on rarity
5. Combine effects for each rarity tier
