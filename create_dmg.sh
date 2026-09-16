#!/bin/bash
# create_dmg.sh — Create macOS DMG with proper drag-to-Applications layout
# Produces a DMG that Finder opens showing .app + Applications shortcut
#
# Usage: bash create_dmg.sh <GoldenVestPet.app path> [output.dmg]
set -euo pipefail

APP="${1:?Usage: create_dmg.sh <app_path> [output.dmg]}"
OUTPUT="${2:-GoldenVestPet.dmg}"
VOLNAME="GoldenVestPet"

[ -d "$APP" ] || { echo "FAIL: $APP not found"; exit 1; }

# Clean up any previous artifacts
rm -rf dmg_temp "$OUTPUT" 2>/dev/null || true

# Create staging directory
mkdir -p dmg_temp
cp -R "$APP" dmg_temp/
ln -s /Applications dmg_temp/Applications

# Create DMG with srcfolder — Finder will show app + Applications symlink
# -volname sets the volume name shown in Finder title bar
# -format UDZO = zlib-compressed read-only
# -noidme prevents "internet-enabled" attribute (which auto-closes DMG after download)
hdiutil create -volname "$VOLNAME" -srcfolder dmg_temp -ov -format UDZO "$OUTPUT"

# Clean up
rm -rf dmg_temp

echo "=== DMG created: $OUTPUT ==="
ls -lh "$OUTPUT"
