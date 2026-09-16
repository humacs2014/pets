# -*- mode: python ; coding: utf-8 -*-
# macOS build spec — outputs .app bundle (must run on macOS)
# Optimized: excludes unneeded modules, optimize=2, strip=True
a = Analysis(
    ['pet_engine.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets'), ('icon.png', '.')],
    hiddenimports=['PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui',
                   'objc', 'AppKit', 'Foundation'],
    hookspath=['hooks'],  # v113: custom hooks to block QtWebEngine collection
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # ═══ QtWebEngine — MUST be aggressively excluded (Chromium ~300-500MB) ═══
        # PyInstaller's PyQt5 hook can pull these in via QtWebChannel etc.
        'PyQt5.QtWebEngine', 'PyQt5.QtWebEngineCore',
        'PyQt5.QtWebEngineWidgets', 'PyQt5.QtWebChannel',
        # ═══ Unneeded PyQt5 submodules ═══
        'PyQt5.QtBluetooth', 'PyQt5.QtDBus', 'PyQt5.QtDesigner',
        'PyQt5.QtHelp', 'PyQt5.QtLocation', 'PyQt5.QtMultimedia',
        'PyQt5.QtMultimediaWidgets', 'PyQt5.QtNetwork', 'PyQt5.QtNfc',
        'PyQt5.QtOpenGL', 'PyQt5.QtPositioning', 'PyQt5.QtQml',
        'PyQt5.QtQuick', 'PyQt5.QtQuickWidgets', 'PyQt5.QtRemoteObjects',
        'PyQt5.QtSensors', 'PyQt5.QtSerialPort', 'PyQt5.QtSql',
        'PyQt5.QtSvg', 'PyQt5.QtTest', 'PyQt5.QtWebChannel',
        'PyQt5.QtWebEngine', 'PyQt5.QtWebSockets', 'PyQt5.QtXml',
        'PyQt5.QtXmlPatterns', 'PyQt5.QtChart',
        'PyQt5.Qt3DCore', 'PyQt5.Qt3DRender', 'PyQt5.Qt3DInput',
        'PyQt5.Qt3DLogic', 'PyQt5.Qt3DExtras', 'PyQt5.Qt3DAnimation',
        'PyQt5.QtDataVisualization', 'PyQt5.QtPurchasing',
        'PyQt5.QtVirtualKeyboard',
        # ═══ Unneeded stdlib ═══
        'asyncio', 'concurrent', 'csv', 'dbm', 'distutils',
        'ftplib', 'gettext', 'imaplib', 'lib2to3',
        'mailbox', 'multiprocessing', 'pydoc', 'pydoc_data',
        'smtplib', 'socketserver', 'sqlite3',
        'tkinter', 'turtle', 'unittest',
        'xmlrpc', 'ensurepip', 'pip', 'setuptools',
        'pkg_resources', 'wheel', 'platformdirs',
        # ═══ Heavy libraries not used by pet engine ═══
        'numpy', 'pandas', 'scipy', 'matplotlib',
        'PIL', 'Pillow', 'numpy.core', 'numpy.fft', 'numpy.linalg',
        'numpy.ma', 'numpy.matrixlib', 'numpy.polynomial', 'numpy.random',
        'numpy.testing', 'numpy.lib', 'numpy.compat', 'numpy.f2py',
        'sympy', 'IPython', 'jupyter', 'notebook',
        'tornado', 'zmq', 'jedi', 'parso',
        'cryptography', 'OpenSSL', 'cffi', 'pycparser',
        # ═══ v113: Extra heavy libs commonly on CI global site-packages ═══
        'docutils', 'sphinx', 'babel', 'pytz', 'dateutil',
        'requests', 'urllib3', 'certifi', 'charset_normalizer',
        'idna', 'chardet', 'html5lib', 'webencodings',
        'lxml', 'defusedxml', 'yaml', 'toml',
        'attr', 'attrs', 'pluggy', 'py', 'pytest',
        'importlib_metadata', 'importlib_resources',
        'zipp', 'filelock', 'virtualenv', 'distlib',
        'six', 'packaging', 'typing_extensions',
        'more_itertools', 'wcwidth', 'click', 'rich',
        # ═══ v113: Additional CI env leakers ═══
        'cmake', 'ninja', 'meson', 'scikit_build',
        'pyproject_hooks', 'build', 'installer',
        'trove_classifiers', 'pep517',
    ],
    noarchive=False,
    optimize=2,  # Bytecode optimization level 2
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,        # BUNDLE mode: binaries go into .app, not single file
    name='GoldenVestPet',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,                   # Remove debug symbols
    upx=False,                    # UPX breaks Mach-O signature structure on macOS, must be off
    console=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = BUNDLE(
    exe,
    a.binaries,
    a.datas,
    name='GoldenVestPet.app',
    icon='app.icns',              # Generate from icon.png on macOS using sips/iconutil
    bundle_identifier='com.goldenvest.pet',
    info_plist={
        'CFBundleDisplayName': 'Golden Vest Puppy',
        'CFBundleName': 'GoldenVestPet',
        'CFBundleShortVersionString': '1.0',
        'NSHighResolutionCapable': True,
        'LSApplicationCategoryType': 'public.app-category.entertainment',
        'LSMinimumSystemVersion': '11.0',
        'NSRequiresAquaSystemAppearance': False,
    },
)
