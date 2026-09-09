# -*- mode: python ; coding: utf-8 -*-
# Windows单文件EXE打包spec（优化版）
# - assets用webp q80（~128MB vs PNG ~1GB）
# - 排除不需要的PyQt5/Python模块减小体积
# - UPX压缩启用
# - strip=True去除调试符号

excludes = [
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
    # Python不需要的标准库
    # 注意：zipfile/zlib/json/urllib/logging/email等被PyInstaller运行时钩子间接依赖，不能排除
    'asyncio', 'concurrent', 'csv', 'dbm', 'distutils',
    'ftplib', 'gettext', 'imaplib', 'lib2to3',
    'mailbox', 'multiprocessing', 'pydoc', 'pydoc_data',
    'smtplib', 'socketserver', 'sqlite3',
    'tkinter', 'turtle', 'unittest',
    'xmlrpc',
]

a = Analysis(['pet_engine.py'],
             pathex=[],
             binaries=[],
             datas=[('assets', 'assets'), ('icon.png', '.')],
             hiddenimports=['PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui'],
             hookspath=[],
             hooksconfig={},
             runtime_hooks=[],
             excludes=excludes,
             noarchive=False,
             optimize=2)  # Python字节码优化级别2（去除docstrings+asserts）

pyz = PYZ(a.pure)

exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.datas,
          [],
          name='金毛背心v1',
          debug=False,
          bootloader_ignore_signals=False,
          strip=True,       # 去除调试符号减小体积
          upx=True,         # UPX压缩
          upx_exclude=[],
          runtime_tmpdir=None,
          console=False,
          disable_windowed_traceback=False,
          argv_emulation=False,
          target_arch=None,
          codesign_identity=None,
          entitlements_files=None,
          icon='icon.ico')
