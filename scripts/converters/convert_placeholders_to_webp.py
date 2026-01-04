#!/usr/bin/env python3
"""
Convert placeholder PNG files to WebP.

By default, this overwrites any existing .webp files with the same stem, so you
can safely re-run after updating PNG templates.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def convert_png_to_webp(png_path: Path, webp_path: Path) -> None:
    with Image.open(png_path) as img:
        # Preserve alpha; WebP encoder works best in RGBA for templates.
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        # Use lossless to keep template text/crisp edges intact.
        webp_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(webp_path, "WEBP", lossless=True, method=6)


def main() -> None:
    placeholders_dir = Path("assets/placeholders")
    png_files = sorted(placeholders_dir.glob("*.png"))

    if not png_files:
        print("No PNG files found in assets/placeholders/")
        return

    print(f"Converting {len(png_files)} PNG placeholders to WebP\n")
    print("=" * 60)

    converted = 0
    for png_path in png_files:
        webp_path = png_path.with_suffix(".webp")
        try:
            convert_png_to_webp(png_path, webp_path)
            print(f"  OK: {png_path.name} -> {webp_path.name}")
            converted += 1
        except Exception as e:
            print(f"  ERROR: {png_path.name}: {e}")

    print("=" * 60)
    print(f"\nDone! Converted {converted}/{len(png_files)} files.")


if __name__ == "__main__":
    main()

