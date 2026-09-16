# hook-PyQt5.QtWebEngine.py — Block QtWebEngine collection even if PyInstaller's
# default PyQt5 hook tries to pull it in via QtWebChannel dependency chain.
# This is a no-op hook that prevents PyInstaller from collecting QtWebEngine binaries.

# PyInstaller's default hook-PyQt5.QtWebEngine.py collects:
#   - PyQt5/QtWebEngine*.so
#   - QtWebEngineProcess (Chromium helper, ~300MB)
#   - qtwebengine_resources, locales, etc.
# By providing our own empty hook, we override the default and prevent all that.

# This file intentionally left blank — no datas, no binaries, no hiddenimports.
