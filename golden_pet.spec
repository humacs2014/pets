# -*- mode: python ; coding: utf-8 -*-
# Windows单文件EXE打包spec模板
# 占位符（全局替换）: golden_pet.py=主程序文件名(如cat_pet.py)  金毛犬桌面宠物=宠物显示名  v1=v56式版本号
a = Analysis(['golden_pet.py'], pathex=[], binaries=[], datas=[('assets', 'assets')], hiddenimports=['PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui'], hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='金毛犬桌面宠物v71', debug=False, bootloader_ignore_signals=False, strip=False, upx=True, upx_exclude=[], runtime_tmpdir=None, console=False, disable_windowed_traceback=False, argv_emulation=False, target_arch=None, codesign_identity=None, entitlements_files=None, icon='icon.ico')
