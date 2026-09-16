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


def create_background(output_path, width=600, height=390):
    """Generate a standard macOS DMG background PNG.

    White background with a subtle gray arrow pointing from App icon (left)
    to Applications (right). Exact dimensions match the DMG window size
    in points (non-Retina). For Retina, dmgbuild auto-detects @2x versions
    in the same directory and merges them into a multi-resolution TIFF.

    Args:
        output_path: Where to save the PNG (the 1x version).
        width/height: Window size in points (1x pixels).
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("WARN: Pillow not installed, DMG will have no background image")
        return False

    # --- 1x version (600x390) ---
    img = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Arrow from app area (~x=130) to Applications area (~x=460)
    arrow_y = height // 2
    arrow_left = 175
    arrow_right = 425
    arrow_color = (180, 180, 180)

    band_h = 4
    draw.rectangle([arrow_left, arrow_y - band_h // 2, arrow_right, arrow_y + band_h // 2],
                   fill=arrow_color)

    head_w = 18
    head_h = 14
    draw.polygon([
        (arrow_right, arrow_y - head_h),
        (arrow_right + head_w, arrow_y),
        (arrow_right, arrow_y + head_h),
    ], fill=arrow_color)

    img.save(output_path, "PNG")
    print(f"Background 1x saved to {output_path}")

    # --- @2x version (1200x780) ---
    base, ext = os.path.splitext(output_path)
    ret_path = f"{base}@2x{ext}"
    img2 = Image.new('RGB', (width * 2, height * 2), (255, 255, 255))
    draw2 = ImageDraw.Draw(img2)

    arrow_y2 = height  # center of 2x image
    arrow_left2 = arrow_left * 2
    arrow_right2 = arrow_right * 2

    band_h2 = band_h * 2
    draw2.rectangle([arrow_left2, arrow_y2 - band_h2 // 2, arrow_right2, arrow_y2 + band_h2 // 2],
                    fill=arrow_color)

    head_w2 = head_w * 2
    head_h2 = head_h * 2
    draw2.polygon([
        (arrow_right2, arrow_y2 - head_h2),
        (arrow_right2 + head_w2, arrow_y2),
        (arrow_right2, arrow_y2 + head_h2),
    ], fill=arrow_color)

    img2.save(ret_path, "PNG")
    print(f"Background @2x saved to {ret_path}")

    return True


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

    app_name = os.path.basename(app_path)

    # Generate background images (1x + @2x for Retina)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    bg_dir = os.path.join(script_dir, "_dmg_bg_tmp")
    os.makedirs(bg_dir, exist_ok=True)
    bg_path = os.path.join(bg_dir, "background.png")
    has_bg = create_background(bg_path)

    # Write a dmgbuild settings file — this is the most reliable way to
    # pass settings because dmgbuild exec()'s the file as Python code,
    # ensuring all variables (especially 'background' path) are resolved
    # in the correct context.
    settings_path = os.path.join(bg_dir, "dmg_settings.py")
    settings_content = f'''
# Auto-generated dmgbuild settings
files = [{app_path!r}]
symlinks = {{"Applications": "/Applications"}}
format = 'ULFO'
default_view = 'icon-view'
icon_size = 128
text_size = 16
icon_locations = {{
    {app_name!r}: (140, 190),
    "Applications": (460, 190),
}}
window_rect = ((100, 100), (600, 390))
show_toolbar = False
show_status_bar = False
show_pathbar = False
show_sidebar = False
background = {bg_path!r}
'''
    with open(settings_path, 'w') as f:
        f.write(settings_content)
    print(f"Settings file written to {settings_path}")

    # Build using settings file (not dict) — most reliable for background images
    print(f"Building DMG: {output_path}")
    dmgbuild.build_dmg(
        filename=output_path,
        volume_name=volname,
        settings_file=settings_path,
    )

    # Cleanup
    import shutil
    if os.path.exists(bg_dir):
        shutil.rmtree(bg_dir)

    size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"=== DMG created: {output_path} ({size_mb:.1f} MB) ===")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python make_dmg.py <GoldenVestPet.app> [output.dmg]")
        sys.exit(1)
    app = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) > 2 else "GoldenVestPet.dmg"
    build_dmg(app, output)
