#!/usr/bin/env python3
"""make_dmg.py — Build a styled macOS DMG with dmgbuild (no Finder/AppleScript needed).

Produces a DMG with:
  - White background with standard macOS install layout (App icon → arrow → Applications)
  - Proper icon positions (app left, Applications symlink right)
  - Icon view with 128pt icons, no toolbar/statusbar
  - ULFO (lzfse) compression for fast drag-to-Applications copy speed

Usage (on macOS):
    python make_dmg.py GoldenVestPet.app GoldenVestPet.dmg

Dependencies: pip install dmgbuild Pillow
"""

import os, sys, tempfile
from pathlib import Path


def create_background(width=1200, height=780):
    """Generate a standard macOS DMG background PNG.

    White background, mimics the native macOS drag-to-Install experience:
    left side = app icon area, right side = Applications area,
    with a subtle right-pointing arrow between them.

    width/height are @2x pixels (window is 600x390 points on Retina).
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("WARN: Pillow not installed, DMG will have no background image")
        return None

    img = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Arrow: subtle gray, centered vertically, spanning from app area to Applications area
    # App icon at ~x=130pts (=260@2x center), Applications at ~x=460pts (=920@2x center)
    arrow_y = height // 2
    arrow_left = 340    # @2x: just right of app icon
    arrow_right = 840   # @2x: just left of Applications icon
    arrow_color = (180, 180, 180)

    # Horizontal band
    band_h = 8  # thin band
    draw.rectangle([arrow_left, arrow_y - band_h // 2, arrow_right, arrow_y + band_h // 2],
                   fill=arrow_color)

    # Arrow head (right-pointing triangle)
    head_w = 36
    head_h = 28
    draw.polygon([
        (arrow_right, arrow_y - head_h),
        (arrow_right + head_w, arrow_y),
        (arrow_right, arrow_y + head_h),
    ], fill=arrow_color)

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
        # v117: Use ULFO (lzfse) compression instead of default UDZO (zlib).
        # ULFO is Apple's native compression format — decompresses 3-5x faster than zlib,
        # so dragging .app to Applications is fast throughout (no late-stage slowdown).
        # UDZO forces macOS to decompress blocks in real-time during copy; large files
        # at the end of the image hit the slowest decompression paths.
        # ULFO requires macOS 10.11+ (El Capitan), which covers all supported Macs.
        'format': 'ULFO',
        # Icon view settings
        'view': 'icon-view',
        'icon_size': 128,
        'text_size': 16,
        'icon_locations': {
            app_name: (140, 190),       # Left side
            'Applications': (460, 190), # Right side
        },
        # Window settings (points, not pixels)
        'window_rect': ((100, 100), (600, 390)),
        # Hide toolbar and statusbar for clean look
        'toolbar_visible': False,
        'statusbar_visible': False,
        # White background with arrow (standard macOS install experience)
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
