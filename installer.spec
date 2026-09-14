# -*- mode: python ; coding: utf-8 -*-
# 安装器打包spec — 将dist/GoldenVestPet整个目录内嵌为datas
# 输出: dist/GoldenVestPet-Setup.exe (~68MB)
# 用户双击 → 解压到当前目录/GoldenVestPet/ → 自动启动

a = Analysis(
    ['installer.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('dist/GoldenVestPet', 'GoldenVestPet'),
    ],
    hiddenimports=[],
    hookspath=[],
    excludes=[
        'numpy', 'scipy', 'matplotlib', 'pandas',
        'PIL', 'pillow', 'cryptography', 'pytest',
        'tkinter', 'transformers', 'torch',
        'IPython', 'jupyter', 'sympy', 'networkx',
    ],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='GoldenVestPet-Setup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)
