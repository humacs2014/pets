# -*- mode: python ; coding: utf-8 -*-
# macOS打包spec — 输出 .app bundle（PyInstaller在macOS上用BUNDLE而非onefile EXE）
# 占位符（全局替换）: mochi_pet.py=主程序文件名  麻薯=宠物显示名(中文)  Mochi=英文名  com.mochi.pet=如com.user.catpet
a = Analysis(
    ['mochi_pet.py'],
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
    name='麻薯',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                    # macOS上UPX容易破坏Mach-O签名结构，必须关闭
    console=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = BUNDLE(
    exe,
    a.binaries,
    a.datas,
    name='麻薯.app',
    icon='app.icns',              # CI用sips从icon.png生成，仓库根目录需icon.png
    bundle_identifier='com.mochi.pet',
    info_plist={
        'CFBundleDisplayName': '麻薯',
        'CFBundleName': 'Mochi',
        'CFBundleShortVersionString': '1.0',
        'NSHighResolutionCapable': True,
        'LSApplicationCategoryType': 'public.app-category.entertainment',
        'LSMinimumSystemVersion': '11.0',
        # 桌面宠物需要悬浮在所有窗口之上
        'NSRequiresAquaSystemAppearance': False,
    },
)
