"""Utility functions for image handling."""

import base64
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image


def save_generated_image(image_bytes: bytes, directory: str = "media/cards") -> str:
    """
    Save generated image bytes to disk with UUID filename.

    Args:
        image_bytes: Raw image bytes (may be base64 encoded or raw bytes).
        directory: Directory path for storing images (default: "media/cards").

    Returns:
        Relative filepath to the saved image (e.g., "media/cards/{uuid}.webp").
    """
    # Ensure directory exists
    cards_dir = Path(directory)
    cards_dir.mkdir(parents=True, exist_ok=True)

    # Decode base64 if needed (check if it's a base64 string)
    if isinstance(image_bytes, str):
        try:
            image_bytes = base64.b64decode(image_bytes)
        except Exception:
            # If decoding fails, treat as raw bytes string
            image_bytes = image_bytes.encode() if isinstance(image_bytes, str) else image_bytes

    # Generate UUID filename with WebP extension
    image_uuid = uuid4()
    filename = f"{image_uuid}.webp"
    filepath = cards_dir / filename

    # Save to disk
    with open(filepath, "wb") as f:
        f.write(image_bytes)

    # Return relative path - normalize to use forward slashes
    # If directory is absolute, try to make it relative to current working directory
    try:
        relative_dir = Path(directory).relative_to(Path.cwd())
        return str(relative_dir / filename)
    except ValueError:
        # If directory is not relative to cwd, return as-is with forward slashes
        return str(Path(directory) / filename).replace("\\", "/")


def save_uploaded_image_to_webp(image_bytes: bytes, directory: str = "media/cards") -> str:
    """
    Save an uploaded image (any common format) as WebP with UUID filename.

    This is safer than writing raw bytes to a `.webp` file because uploads may be
    JPEG/PNG/HEIC/etc. We normalize into a consistent WebP file.

    Args:
        image_bytes: Raw uploaded image bytes.
        directory: Directory path for storing images (default: "media/cards").

    Returns:
        Relative filepath to the saved image (e.g., "media/cards/{uuid}.webp").
    """
    cards_dir = Path(directory)
    cards_dir.mkdir(parents=True, exist_ok=True)

    image_uuid = uuid4()
    filename = f"{image_uuid}.webp"
    filepath = cards_dir / filename

    with Image.open(BytesIO(image_bytes)) as img:
        # Normalize color mode for WebP
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")

        img.save(
            filepath,
            format="WEBP",
            quality=90,
            method=6,
        )

    try:
        relative_dir = Path(directory).relative_to(Path.cwd())
        return str(relative_dir / filename)
    except ValueError:
        return str(Path(directory) / filename).replace("\\", "/")
