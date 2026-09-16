#!/usr/bin/env python3
"""make_dmg.py — Build a styled macOS DMG with dmgbuild (no Finder/AppleScript needed).

Produces a DMG with:
  - Custom background image (left: app icon area, right: Applications arrow)
  - Proper icon positions (app left, Applications symlink right)
  - Icon view with 128pt icons, no toolbar/statusbar

Usage (on macOS):
    python make_dmg.py GoldenVestPet.app GoldenVestPet.dmg

Dependencies: pip install dmgbuild Pillow
"""

import os, sys, shutil, tempfile
from pathlib import Path

def create_background(width=1200, height=800, bg_color=(44, 44, 46)):
    """Generate a simple dark background PNG for the DMG window.
    width/height are @2x pixels (window is 600x400 points on Retina).
    Draws a subtle horizontal arrow hint pointing from left (app) to right (Applications).
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("WARN: Pillow not installed, DMG will have no background image")
        return None

    img = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # Subtle arrow: a light translucent band from app position to Applications position
    # App at ~x=130, Applications at ~x=410 (in points, = 260 and 820 in @2x)
    arrow_y = height // 2
    arrow_left = 200
    arrow_right = 1000
    arrow_color = (70, 70, 75)

    # Horizontal band
    draw.rectangle([arrow_left, arrow_y - 30, arrow_right, arrow_y + 30], fill=arrow_color)
    # Arrow head (right-pointing triangle)
    head_size = 40
    draw.polygon([
        (arrow_right, arrow_y - head_size - 10),
        (arrow_right + head_size + 10, arrow_y),
        (arrow_right, arrow_y + head_size + 10),
    ], fill=arrow_color)

    # Labels
    try:
        from PIL import ImageFont
        font_size = 28  # @2x, so appears as 14pt
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        except (OSError, IOError):
            font = ImageFont.load_default()
        draw.text((220, arrow_y + 80), "Drag to install", fill=(140, 140, 145), font=font)
    except Exception:
        pass  # Font not critical

    return img


def build_dmg(app_path, output_path, volname="GoldenVestPet"):
    """Build styled DMG using dmgbuild."""
    try:
        import dmgbuild
    except ImportError:
        print("ERROR: dmgbuild not installed. Run: pip install dmgbuild")
        sys.exit(1)

    app_path = os.path.abspath(app_path)
    output_path = os.path.abspath(output_path)

    if not os.path.isdir(app_path):
        print(f"FAIL: {app_path} not found")
        sys.exit(1)

    app_name = os.path.basename(app_path)  # e.g. "GoldenVestPet.app"

    # Generate background image
    bg_img = create_background()
    bg_path = None
    if bg_img is not None:
        bg_path = os.path.join(tempfile.gettempdir(), "dmg_background.png")
        bg_img.save(bg_path, "PNG")
        print(f"Background image saved to {bg_path}")

    # dmgbuild settings
    settings = {
        # Files to include
        'files': [app_path],
        # Symlinks
        'symlinks': {'Applications': '/Applications'},
        # Icon view settings
        'view': 'icon-view',
        'icon_size': 128,
        'text_size': 16,
        'icon_locations': {
            app_name: (140, 200),       # Left side
            'Applications': (460, 200), # Right side
        },
        # Window settings (points, not pixels)
        'window_rect': ((100, 100), (600, 400)),
        # Hide toolbar and statusbar for clean look
        'toolbar_visible': False,
        'statusbar_visible': False,
        # Background
        'background': bg_path if bg_path else None,
        # Volume icon (use app's .icns if available)
        'icon': None,
    }

    # Build
    print(f"Building DMG: {output_path}")
    dmgbuild.build_dmg(
        filename=output_path,
        volume_name=volname,
        settings=settings,
    )

    # Cleanup
    if bg_path and os.path.exists(bg_path):
        os.remove(bg_path)

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"=== DMG created: {output_path} ({size_mb:.1f} MB) ===")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python make_dmg.py <GoldenVestPet.app> [output.dmg]")
        sys.exit(1)
    app = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) > 2 else "GoldenVestPet.dmg"
    build_dmg(app, output)
