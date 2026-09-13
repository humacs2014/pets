# -*- mode: python ; coding: utf-8 -*-
# Windows onefile build spec — single EXE, double-click to run
# UPX disabled (Qt DLLs break when compressed)

excludes = [
    'PyQt5.QtBluetooth', 'PyQt5.QtDBus', 'PyQt5.QtDesigner',
    'PyQt5.QtHelp', 'PyQt5.QtLocation', 'PyQt5.QtMultimedia',
    'PyQt5.QtMultimediaWidgets', 'PyQt5.QtNetwork', 'PyQt5.QtNfc',
    'PyQt5.QtOpenGL', 'PyQt5.QtPositioning', 'PyQt5.QtQml',
    'PyQt5.QtQuick', 'PyQt5.QtQuickWidgets', 'PyQt5.QtRemoteObjects',
    'PyQt5.QtSensors', 'PyQt5.QtSerialPort', 'PyQt5.QtSql',
    'PyQt5.QtSvg', 'PyQt5.QtTest', 'PyQt5.QtWebChannel',
    'PyQt5.QtWebEngine', 'PyQt5.QtWebSockets', 'PyQt5.QtXml',
    'PyQt5.QtXmlPatterns', 'PyQt5.QtChart',
    'asyncio', 'concurrent', 'csv', 'dbm', 'distutils',
    'ftplib', 'gettext', 'imaplib', 'lib2to3',
    'mailbox', 'multiprocessing', 'pydoc', 'pydoc_data',
    'smtplib', 'socketserver', 'sqlite3',
    'tkinter', 'turtle', 'unittest',
    'xmlrpc', 'ensurepip', 'pip', 'setuptools',
    'pkg_resources', 'wheel', 'platformdirs',
    'numpy', 'pandas', 'scipy', 'matplotlib',
    'PIL', 'numpy.core', 'numpy.fft', 'numpy.linalg',
    'numpy.ma', 'numpy.matrixlib', 'numpy.polynomial',
    'numpy.random', 'numpy.testing',
    'sympy', 'IPython', 'jupyter', 'notebook',
    'tornado', 'zmq', 'jedi', 'parso',
    'cryptography', 'OpenSSL', 'cffi', 'pycparser',
]

a = Analysis(['pet_engine.py'],
             pathex=[],
             binaries=[],
             datas=[('assets', 'assets'), ('icon.png', '.'),
                    ('C:/Users/humac/anaconda3/Library/plugins/platforms', 'PyQt5/Qt5/plugins/platforms')],
             hiddenimports=['PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui'],
             hookspath=[],
             hooksconfig={},
             runtime_hooks=[],
             excludes=excludes,
             noarchive=False,
             optimize=2)

pyz = PYZ(a.pure)

exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.datas,
          [],
          name='GoldenVestPet',
          debug=False,
          bootloader_ignore_signals=False,
          strip=True,
          upx=False,
          upx_exclude=[],
          runtime_tmpdir=None,
          console=False,
          disable_windowed_traceback=False,
          argv_emulation=False,
          target_arch=None,
          codesign_identity=None,
          entitlements_files=None,
          icon='icon.ico')
