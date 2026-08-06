# -*- mode: python ; coding: utf-8 -*-
# macOS打包spec — 输出 .app bundle（PyInstaller在macOS上用BUNDLE而非onefile EXE）

a = Analysis(
    ['husky_pet_v7.py'],
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
    exclude_binaries=True,        # BUNDLE模式：binaries放进.app而非单文件
    name='哈士奇桌面宠物',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                    # macOS上UPX容易破坏Mach-O签名结构，关闭
    console=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = BUNDLE(
    exe,
    a.binaries,
    a.datas,
    name='哈士奇桌面宠物.app',
    icon='app.icns',
    bundle_identifier='com.humac.huskydesktoppet',
    info_plist={
        'CFBundleDisplayName': '哈士奇桌面宠物',
        'CFBundleName': 'HuskyDesktopPet',
        'CFBundleShortVersionString': '1.0',
        'NSHighResolutionCapable': True,
        'LSApplicationCategoryType': 'public.app-category.entertainment',
        'LSMinimumSystemVersion': '11.0',
        # 桌面宠物需要悬浮在所有窗口之上
        'NSRequiresAquaSystemAppearance': False,
    },
)
