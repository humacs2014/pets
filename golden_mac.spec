# -*- mode: python ; coding: utf-8 -*-
# macOS build spec — outputs .app bundle (PyInstaller uses BUNDLE on macOS, not onefile EXE)

a = Analysis(
    ['golden_pet.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=['PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,        # BUNDLE mode: binaries go into .app, not single file
    name='GoldenPet',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                    # UPX can corrupt Mach-O signing on macOS, keep off
    console=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = BUNDLE(
    exe,
    a.binaries,
    a.datas,
    name='GoldenPet.app',
    icon='app.icns',
    bundle_identifier='com.humac.goldendesktoppet',
    info_plist={
        'CFBundleDisplayName': 'GoldenPet',
        'CFBundleName': 'GoldenDesktopPet',
        'CFBundleShortVersionString': '1.0',
        'NSHighResolutionCapable': True,
        'LSApplicationCategoryType': 'public.app-category.entertainment',
        'LSMinimumSystemVersion': '11.0',
        # Desktop pet needs to float above all windows
        'NSRequiresAquaSystemAppearance': False,
        'LSUIElement': True,        # No Dock icon, no Cmd+Tab entry — floating desktop companion
    },
)
