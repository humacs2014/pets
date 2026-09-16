#!/bin/bash
# create_dmg.sh — Create macOS DMG with proper drag-to-Applications layout
# Produces a DMG that opens with the classic Finder two-pane view:
#   Left: GoldenVestPet.app icon, Right: Applications shortcut
#   Custom background + icon positions + window size
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

# Create a writable DMG first (we need to set Finder attributes)
hdiutil create -volname "$VOLNAME" -srcfolder dmg_temp -ov -format UDRW "/tmp/temp_$VOLNAME.dmg"

# Mount the DMG to set Finder attributes
DEVICE=$(hdiutil attach -readwrite -noverify -noautoopen "/tmp/temp_$VOLNAME.dmg" | \
         grep "/Volumes/$VOLNAME" | awk '{print $1}')
MOUNT="/Volumes/$VOLNAME"

# Wait for mount
sleep 2

# Set Finder window properties using AppleScript
# This creates the classic "drag to install" two-pane layout
osascript <<EOF
tell application "Finder"
    tell disk "$VOLNAME"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        -- Window size: wide enough for two icons side by side
        set bounds of container window to {100, 100, 700, 450}
        -- Icon size
        set icon size of theViewOptions of container window to 128
        set arrangement of theViewOptions of container window to not arranged
        -- Position the app icon on the left, Applications on the right
        set position of item "GoldenVestPet.app" of container window to {150, 200}
        set position of item "Applications" of container window to {450, 200}
        -- Close and reopen to apply
        close container window
        open container window
        update without registering applications
        delay 2
    end tell
end tell
EOF

# Sync and unmount
sync
hdiutil detach "$DEVICE" -force

# Convert to compressed read-only DMG
hdiutil convert "/tmp/temp_$VOLNAME.dmg" -format UDZO -o "$OUTPUT"
rm -f "/tmp/temp_$VOLNAME.dmg"
rm -rf dmg_temp

echo "=== DMG created: $OUTPUT ==="
ls -lh "$OUTPUT"
