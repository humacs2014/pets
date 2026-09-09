# -*- mode: python ; coding: utf-8 -*-
# macOS打包spec — 输出 .app bundle（必须在macOS上执行）
# 优化：排除不需要模块、optimize=2、strip=True
a = Analysis(
    ['pet_engine.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets'), ('icon.png', '.')],
    hiddenimports=['PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # PyQt5不需要的子模块
        'PyQt5.QtBluetooth', 'PyQt5.QtDBus', 'PyQt5.QtDesigner',
        'PyQt5.QtHelp', 'PyQt5.QtLocation', 'PyQt5.QtMultimedia',
        'PyQt5.QtMultimediaWidgets', 'PyQt5.QtNetwork', 'PyQt5.QtNfc',
        'PyQt5.QtOpenGL', 'PyQt5.QtPositioning', 'PyQt5.QtQml',
        'PyQt5.QtQuick', 'PyQt5.QtQuickWidgets', 'PyQt5.QtRemoteObjects',
        'PyQt5.QtSensors', 'PyQt5.QtSerialPort', 'PyQt5.QtSql',
        'PyQt5.QtSvg', 'PyQt5.QtTest', 'PyQt5.QtWebChannel',
        'PyQt5.QtWebEngine', 'PyQt5.QtWebSockets', 'PyQt5.QtXml',
        'PyQt5.QtXmlPatterns', 'PyQt5.QtChart',
        # Python不需要的标准库（zipfile/zlib/json/urllib/logging/email等被PyInstaller运行时钩子间接依赖，不能排除）
        'asyncio', 'concurrent', 'csv', 'dbm', 'distutils',
        'ftplib', 'gettext', 'imaplib', 'lib2to3',
        'mailbox', 'multiprocessing', 'pydoc', 'pydoc_data',
        'smtplib', 'socketserver', 'sqlite3',
        'tkinter', 'turtle', 'unittest',
        'xmlrpc',
    ],
    noarchive=False,
    optimize=2,  # 字节码优化级别2
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,        # BUNDLE模式：binaries放进.app而非单文件
    name='金毛背心',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,                   # 去除调试符号
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
    name='金毛背心.app',
    icon='app.icns',              # 需在macOS上用 sips/iconutil 从 icon.png 生成
    bundle_identifier='com.goldenvest.pet',
    info_plist={
        'CFBundleDisplayName': '金毛背心',
        'CFBundleName': 'GoldenVestPet',
        'CFBundleShortVersionString': '1.0',
        'NSHighResolutionCapable': True,
        'LSApplicationCategoryType': 'public.app-category.entertainment',
        'LSMinimumSystemVersion': '11.0',
        'NSRequiresAquaSystemAppearance': False,
    },
)
