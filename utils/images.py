"""Utility functions for image handling."""

import base64
from pathlib import Path
from uuid import uuid4


def save_generated_image(image_bytes: bytes, directory: str = "media/cards") -> str:
    """
    Save generated image bytes to disk with UUID filename.

    Args:
        image_bytes: Raw image bytes (may be base64 encoded or raw bytes).
        directory: Directory path for storing images (default: "media/cards").

    Returns:
        Relative filepath to the saved image (e.g., "media/cards/{uuid}.png").
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

    # Generate UUID filename
    image_uuid = uuid4()
    filename = f"{image_uuid}.png"
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
