#!/usr/bin/env python3
"""
Desktop Pet Hybrid Rendering Engine (golden v71 final template)
=========================================================
CONFIG: PET_NAME / PET_NAME_ASCII / BARK_TEXT / EAT_TEXT + ANIMS dict
Core principles (same as Deskpet Dog competitor):
  1. Original sprite frames as base (preserve original charm)
  2. Real-time procedural overlays:
     - Breathing: crop chest region, redraw at 0.9 opacity + 1.5-2.5% scale
     - Idle bob: sinusoidal Y-axis micro-float
     - Walk sway: +/-2deg rotation + bounce, synced to gait frames
     - Roll: 360deg continuous rotation (procedural)
     - Landing squash & stretch
     - Drag tilt: rotate by velocity
     - Direction flip: scale(-1,1) mirror
  3. 60fps continuous rendering, frame animation + transform overlays
  4. Full behavior AI: taskbar roam / desktop fixed / tease chase / potty / sleep
  5. Physics: inertial drag + throw + gravity bounce
  6. Particle FX: hearts / Zzz / stink / stars / crumbs / speech bubbles
"""

import sys
import math
import random
import time
import os
import json

# PyInstaller onefile fix: Qt5 needs to find platforms plugin in temp dir
if getattr(sys, 'frozen', False):
    _base = sys._MEIPASS
    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.path.join(_base, 'PyQt5', 'Qt5', 'plugins', 'platforms')
    # Also add _base to DLL search path
    if hasattr(os, 'add_dll_directory'):
        os.add_dll_directory(_base)

from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer, QPoint, QPointF, QRectF, QRect, QThread, QEventLoop, QEvent
from PyQt5.QtGui import (
    QPainter, QPen, QBrush, QColor, QPainterPath, QFont, QFontMetrics,
    QImage, QImageReader, QCursor, QRadialGradient, QLinearGradient
)

# Cross-platform font: macOS has no Microsoft YaHei, fallback to system sans
_UI_FONT = 'Helvetica' if sys.platform == 'darwin' else 'Arial'

# ═══ v66 parameterization (change for new pet) ═══
PET_NAME = 'Golden Vest Puppy'        # Display name
PET_NAME_ASCII = 'GoldenVestPet'       # ASCII name (window title / mutex)
BARK_TEXT, EAT_TEXT = 'Woof!', 'Yummy!'   # Bubble text


def asset_path():
    """Resource path (PyInstaller compatible)"""
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'assets')


# ═══════════════════════════════════════════════════════════
#  Animation config  --  frame sequence and duration per state
# ═══════════════════════════════════════════════════════════
ANIMS = {
    # state: (prefix, frame_count, frame_ms, loop, intro_frames)
    # All states now 121 frames (SAM2+BiRefNet pipeline, darkblue video source)
    # v107: 统一42ms=24fps，所有动作一轮=5.08秒，duration对齐整数倍轮次
    'idle':      ('idle',      121, 42,  True,  0),
    'walk':      ('walk',      121, 42,  True,  0),
    'run':       ('run',       121, 42,  True,  0),
    'eat':       ('eat',       121, 42,  True,  0),
    'bark':      ('bark',      121, 42,  True,  0),
    'sleep':     ('sleep',     121, 42,  True,  0),
    'sit':       ('sit',       121, 42,  True,  0),
    'lick':      ('lick',      121, 42,  True,  0),
    'happy':     ('happy',     121, 42,  False, 0),
    'roll':      ('roll',      121, 42,  False, 0),
    'dance':     ('dance',     121, 42,  True,  0),
    'stretch':   ('stretch',   121, 42,  False, 0),
    'beg':       ('beg',       121, 42,  True,  0),
    'bath':      ('bath',      121, 42,  True, 0),
    'surprised': ('surprised', 121, 42,  True,  0),
    'play_dead': ('play_dead', 121, 42,  False, 0),
    'pet':       ('pet',       121, 42,  False, 0),
    'kiss':      ('kiss',      121, 42,  False, 0),
    'wave':      ('wave',      121, 42,  True,  0),
    'type':      ('type',      121, 42,  True,  0),
    'potty_run': ('run',       121, 42,  True,  0),
    'potty':     ('sit',       121, 42,  True,  0),
}

# Side-view states (walk/run face right by default, mirror when moving left; mirror direction controlled by self.flipped=facing<0)
LEFT_FACING = {'walk', 'run'}

CANVAS = 320          # Window size (320>250+squash/rotation overflow margin, prevents transform clipping)
DRAW_SIZE = 250       # Sprite draw size
GROUND_PAD = 14       # Foot bottom padding

# ═══════════════════════════════════════════════════════════
#  v25 (P9): Global zoom  --  menu "Size" scale up/down/reset, ratio persisted
# ═══════════════════════════════════════════════════════════
ZOOM_DEFAULT = 1.0
ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.5, 2.5, 0.25


def zoom_cfg_path():
    """Zoom config file location (next to exe after packaging)"""
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.dirname(sys.executable), 'zoom_config.json')
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'zoom_config.json')


def load_zoom():
    try:
        with open(zoom_cfg_path(), 'r', encoding='utf-8') as f:
            return max(ZOOM_MIN, min(ZOOM_MAX, float(json.load(f).get('zoom', ZOOM_DEFAULT))))
    except Exception:
        return ZOOM_DEFAULT


def save_zoom(zoom):
    try:
        with open(zoom_cfg_path(), 'w', encoding='utf-8') as f:
            json.dump({'zoom': zoom}, f)
    except Exception:
        pass


def _target_dpr(widget=None):
    """v2 highresolution: Sprite texture size must multiply by devicePixelRatio  --  otherwise Retina (dpr=2)
    250px logical texture stretched to 500 device pixels = constant 2x blur
    (#1 cause of Mac/HiDPI "roughness"). Uses dpr of the screen the window is on."""
    scr = None
    if widget is not None and widget.windowHandle() is not None:
        scr = widget.windowHandle().screen()
    if scr is None and widget is not None:
        try:
            scr = QApplication.screenAt(widget.geometry().center())
        except Exception:
            scr = None
    if scr is None:
        scr = QApplication.primaryScreen()
    try:
        return float(scr.devicePixelRatio())
    except Exception:
        return 1.0


# ═══════════════════════════════════════════════════════════
#  v67: Self-drawn rounded menu  --  fixes macOS QMenu white corners
#  QMenu+WA_TranslucentBackground still renders white outside rounded corners on macOS;
#  Use QPainterPath self-drawn popup same as main window, pixel-identical on both platforms.
# ═══════════════════════════════════════════════════════════
_MENU_BG = QColor('#2b2b3a')
_MENU_FG = QColor('#e8e8f0')
_MENU_HOVER = QColor('#4a4a6e')
_MENU_BORDER = QColor('#45455c')
_MENU_ITEM_H = 34
_MENU_SEP_H = 9
_MENU_PAD = 8


class RoundedMenu(QWidget):
    """Self-drawn popup menu: QPainterPath rounded corners, supports separators and hover-expand submenus.
    exec_menu(global_pos) -> selected item key or None."""

    def __init__(self, parent=None):
        # v67: Don't use Qt.Popup  --  two independent Popups for main/submenu cause mouse capture
        # conflict on Windows (submenu opens but main menu stops receiving events). Use Tool+toplevel+app-level
        # eventFilter for unified mouse routing; outside click/Escape self-closes.
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.items = []  # ('item',key,text) / ('sep',) / ('sub',text,RoundedMenu)
        self.hover_idx = -1
        self.sub_open = None
        self.root = self
        self._loop = None
        self._result = None
        self._rects = []
        self._w = self._h = 10
        self._font = QFont(_UI_FONT)
        self._font.setPixelSize(13)

    # ---- Build ----
    def add_item(self, key, text):
        self.items.append(('item', key, text))

    def add_sep(self):
        self.items.append(('sep',))

    def add_sub(self, text, submenu):
        # Submenu stays as independent top-level popup (correct cascading menu form);
        # Cannot setParent to main menu  --  otherwise render/grab's DrawChildren
        # would also render unlayouted child popups causing crash.
        submenu.root = self.root
        self.items.append(('sub', text, submenu))

    # ---- Layout/Positioning ----
    def _layout(self):
        fm = QFontMetrics(self._font)
        w = 0
        for it in self.items:
            if it[0] == 'sep':
                continue
            # item=('item',key,text) / sub=('sub',text,menu)
            text = it[1] if it[0] == 'sub' else it[2]
            w = max(w, fm.horizontalAdvance(text))
        self._w = w + _MENU_PAD * 2 + 58  # icon+text+submenu arrow padding
        y = _MENU_PAD
        self._rects = []
        for it in self.items:
            h = _MENU_SEP_H if it[0] == 'sep' else _MENU_ITEM_H
            self._rects.append(QRect(_MENU_PAD, y, self._w - _MENU_PAD * 2, h))
            y += h
        self._h = y + _MENU_PAD
        self.setFixedSize(self._w, self._h)

    def _clamp(self, x, y, pos):
        scr = QApplication.screenAt(pos) or QApplication.primaryScreen()
        sg = scr.geometry()
        if x + self._w > sg.right():
            x = sg.right() - self._w
        if y + self._h > sg.bottom():
            y = sg.bottom() - self._h
        return max(sg.left(), x), max(sg.top(), y)

    def exec_menu(self, pos):
        """Modal display at global pos, returns selected item key (None=cancelled)"""
        self._layout()
        self._result = None
        self.move(*self._clamp(pos.x(), pos.y(), pos))
        self.show()
        # P3-fix2: DO NOT call activateWindow() — steals focus from Chrome/other apps
        # raise_() is safe for Z-order without focus change
        self.raise_()
        # App-level filter: unified mouse routing for main/submenu (fix for Qt.Popup dual-window capture conflict)
        QApplication.instance().installEventFilter(self)
        self._loop = QEventLoop()
        self._loop.exec_()
        self._loop = None
        QApplication.instance().removeEventFilter(self)
        return self._result

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.MouseMove:
            gp = ev.globalPos()
            if self.sub_open is not None and self.sub_open.geometry().contains(gp):
                tgt = self.sub_open
            elif self.geometry().contains(gp):
                tgt = self
            else:
                # Gap zone (2px seam between main/submenu) or outside menu: don't disturb hover, avoid flicker
                return False
            if tgt.hover_idx != tgt._idx_at(gp):
                ni = tgt._idx_at(gp)
                if ni < 0 and tgt.hover_idx >= 0:
                    # v68: Pad border/separator band doesn't disturb current hover (highlight held),
                    # avoids highlight flicker when crossing gaps, and eliminates any cascade-close path
                    return False
                tgt.hover_idx = ni
                tgt.update()
                tgt._sync_submenu()
        elif t == QEvent.MouseButtonPress:
            if ev.button() == Qt.LeftButton:
                gp = ev.globalPos()
                if self.sub_open is not None and self.sub_open.geometry().contains(gp):
                    self.sub_open._press_at(gp)
                elif self.geometry().contains(gp):
                    self._press_at(gp)
                elif not isinstance(obj, RoundedMenu):
                    self.close_all()  # Click outside menu = cancel (gap zone clicks don't close)
        elif t == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
            self.close_all()
        return False

    # ---- Submenu ----
    def _sync_submenu(self):
        it = self.items[self.hover_idx] if 0 <= self.hover_idx < len(self.items) else None
        if it is not None and it[0] == 'sub':
            sub = it[2]
            if self.sub_open is not sub:
                self._close_submenu()
                self.sub_open = sub
                sub._layout()
                r = self._rects[self.hover_idx]
                gp = self.mapToGlobal(r.topRight())
                x = gp.x() + 2
                y = gp.y() - _MENU_PAD
                scr = QApplication.screenAt(gp) or QApplication.primaryScreen()
                if x + sub._w > scr.geometry().right():
                    x = self.mapToGlobal(r.topLeft()).x() - sub._w - 2
                sub.move(*sub._clamp(x, y, gp))
                sub.show()
        elif it is not None and self.sub_open is not None:
            # v68: only close submenu when hover lands on "another clear item". hover=-1 (pad border/
            # separator) keeps submenu -- path to submenu requires crossing 8px pad band on main menu right,
            # old logic closed on hover=-1, slow mouse crossing always triggers (cause of "sometimes auto-collapses").
            self._close_submenu()

    def _close_submenu(self):
        if self.sub_open is not None:
            self.sub_open.close_all()
            self.sub_open = None

    def close_all(self):
        self._close_submenu()
        self.close()

    # ---- Interaction ----
    def _idx_at(self, global_pos):
        lp = self.mapFromGlobal(global_pos)
        for i, r in enumerate(self._rects):
            if r.contains(lp) and self.items[i][0] != 'sep':
                return i
        return -1

    def _press_at(self, global_pos):
        idx = self._idx_at(global_pos)
        if idx < 0:
            return
        it = self.items[idx]
        if it[0] == 'sub':
            return  # Submenu items expand on hover
        self.root._result = it[1]
        self.root.close_all()

    def closeEvent(self, e):
        self._close_submenu()
        if self._loop is not None:
            self._loop.quit()
        super().closeEvent(e)

    # ---- Drawing ----
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 8, 8)
        p.fillPath(path, _MENU_BG)
        p.setPen(QPen(_MENU_BORDER, 1))
        p.drawPath(path)
        p.setFont(self._font)
        for i, it in enumerate(self.items):
            r = self._rects[i]
            if it[0] == 'sep':
                p.setPen(QPen(_MENU_BORDER, 1))
                p.drawLine(r.left() + 10, r.center().y(), r.right() - 10, r.center().y())
                continue
            if i == self.hover_idx:
                hp = QPainterPath()
                hp.addRoundedRect(QRectF(r).adjusted(2, 2, -2, -2), 5, 5)
                p.fillPath(hp, _MENU_HOVER)
            text = it[1] if it[0] == 'sub' else it[2]
            p.setPen(_MENU_FG)
            p.drawText(r.adjusted(12, 0, -12, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
            if it[0] == 'sub':
                p.drawText(r.adjusted(-14, 0, -6, 0), Qt.AlignVCenter | Qt.AlignRight, '>')
        p.end()

# ═══════════════════════════════════════════════════════════
#  v24: LEG_RIG cleared  --  per-frame visual analysis proves:
#  1) walk v13 frames already have authentic crossing gait (front/rear legs swap per frame, full walk cycle),
#     leg-swing pendulum rigidly swings legs in sync, destroying crossing gait into "all four legs swaying together".
#  2) run old frames have frozen legs (8 frames same pose), rig only causes paired swaying.
#  Correct approach: walk plays frames directly; run regenerated with Agnes real gallop loop video then extracted (see agnes_test).
#  Historical rig calibration backup in test_p2_rigcal_v13.py output, reference if re-enabling rig.
# ═══════════════════════════════════════════════════════════
LEG_RIG = {
    # v24: Empty  --  pure frame playback. walk frames have built-in crossing gait; run frames also pure playback after regeneration.
}
RIG_BODY_OVERLAP = 12  # Body block extends below cut line rows (covers seam)  --  v19: 4->12, no gap under belly during leg rotation
RIG_LEG_TOP = 8        # Leg block starts N rows above cut line (overlaps body)  --  v19: 2->8 deeper overlap
RIG_FADE = 12          # Leg block top N rows alpha linear fade (seam blending)  --  v19: 6->12 eliminates hard cut line


def _approach(v, target, rate, dt):
    """Smoothly approach target at rate v (for velocity easing)"""
    if v < target:
        return min(v + rate * dt, target)
    return max(v - rate * dt, target)


# ═══════════════════════════════════════════════════════════
#  Sprite bank  --  load/scale/mirror preprocessing
# ═══════════════════════════════════════════════════════════
_BODY_BOTTOM_CACHE = {}   # v66: cacheKey -> bottom row (pixel scan result cache)
_BODY_BOTTOM_CACHE2 = {}  # v66: cacheKey -> content bottom row (lift scan cache)


def _crash_log(tag):
    """v69-fix: QThread uncaught exception triggers C++ std::terminate  --  no traceback/no event log/
    no crash.log, process dies silently (cause of "auto-closes after action"). This function is for thread run()
    fallback except to write log, degrading death to "action blank but process alive"."""
    import traceback
    try:
        if getattr(sys, 'frozen', False):
            log = os.path.join(os.path.dirname(sys.executable), 'crash.log')
        else:
            log = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'crash.log')
        with open(log, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%Y-%m-%d %H:%M:%S ') + tag + '\n'
                    + traceback.format_exc() + '\n')
    except Exception:
        pass


_crash_fh = None  # faulthandler file handle held globally (prevent GC closing)


class _LoadThread(QThread):
    """v48: Background sprite rebuild -- main thread sync load() freezes UI (579 frames x pure Python pixel scan).
    Build complete bank data in thread, atomic swap on finished in main thread, no half-state during rendering."""
    def __init__(self, draw_size):
        super().__init__()
        self.draw_size = draw_size
        self.result = None

    def run(self):
        try:
            b = SpriteBank()
            b.draw_size = self.draw_size
            b.load()
            self.result = b
        except Exception:
            # v69-fix: QThread uncaught exception = std::terminate = silent process death (no crash.log/
            # no event log/no traceback, one cause of "auto-closes after action"). Catch and log, degrade gracefully.
            _crash_log('LoadThread')
            self.result = None


class _StateLoadThread(QThread):
    """v64: lazy-loadsinglestate --  -- backgroundBuildshouldstateframe table, finishedaftermain threadwrite backbank. """
    def __init__(self, bank, state):
        super().__init__()
        self.bank, self.state = bank, state
        self._draw_size = bank.draw_size  # v100: record for zoom-change rescale detection
        self.imgs = None
        self.lift = None

    def run(self):
        try:
            self.imgs, self.lift = self.bank._build_state(self.state)
        except Exception:
            # v69-fix: Same  --  lazy load thread exception no longer kills process, logs and degrades (action blank but alive)
            _crash_log(f'StateLoadThread[{self.state}]')
            self.imgs, self.lift = None, None


class SpriteBank:
    # v64: tight canvas states (assets rebaked by rebake_v64.py: trim whitespace + center centroid + bottom anchor,
    # calm six-state baseline unified 560). walk = approved version keeps 1024^2 square canvas original path.
    TIGHT = {'idle', 'run', 'eat', 'bark', 'sleep', 'sit', 'lick', 'happy',
             'roll', 'dance', 'stretch', 'beg', 'bath', 'surprised',
             'play_dead', 'pet', 'kiss', 'wave', 'type', 'walk'}
    # v64: One-shot/low-frequency states lazy-loaded  --  not preloaded at startup, first set_state triggers background async load,
    # resident set = 7 high-frequency interactive states, memory peak greatly reduced.
    # v67: dance/beg/bath moved to lazy set (resident -28MB textures), first trigger uses sync fast path.
    # v22g: roll moved out of LAZY -> resident set. roll is menu interaction action, lazy-load caused only 1 frame loaded
    #      -> during background thread build, bank replaced by fullbank/zoom swap -> full frame table lost
    #      -> animation stuck on 1 frame = user reports "ends in 2 seconds". Resident set preloads at startup, no issue.
    # v67: Only idle is mandatory startup state, all others LAZY (background async load, first trigger sync-loads 5 frames + background full)
    # v67-resident: High-frequency interaction states moved to resident set to eliminate first-trigger freeze.
    #   These states (walk/run/bark/sit/sleep/eat/lick) are the most common AI auto-actions.
    #   Low-frequency performance states (dance/beg/bath/happy/stretch/pet/play_dead/surprised/kiss/wave/type/roll) stay lazy.
    LAZY = {'happy', 'stretch', 'pet', 'play_dead', 'surprised',
            'dance', 'beg', 'bath', 'kiss', 'wave', 'type', 'roll',
            'run', 'eat', 'bark', 'sleep', 'sit', 'lick', 'walk'}  # v99: ALL non-idle states lazy — startup loads only idle
    ASSET_SCALE = 1.05  # Texture long side = screen device pixel long side x 1.05 (1:1 sharpness + small margin)

    def __init__(self):
        self.frames = {}     # state -> [QImage normal]
        self.frames_m = {}   # state -> [QImage mirrored]
        self.geo = {}        # v64: state -> (source width, source height) first frame size (tight constant)
        self.alias = {}      # v64: state -> frame table owner (potty->sit etc, dedup no double-load)
        self._lazy_threads = {}
        # Leg rig parts: state -> dict(body/front/rear each [QImage normal, QImage mirrored])
        self.rig_parts = {}
        self.rig_parts_m = {}
        self.lift_map = {}   # state -> [per-frame lift height 0..1] (jump arc drives shadow)
        self._sprite_meta = None  # unused

    def _state_draw(self, state):
        """P5-fix: draw = target pixel size for the state's content.
        For tight states, draw maps to DRAW_SIZE based on canvas height.
        _build_state now scans actual content and scales by max_content_h uniformly."""
        draw = getattr(self, 'draw_size', DRAW_SIZE)
        if state in self.TIGHT:
            w, h = self.geo.get(state, (1024, 1024))
            # Use canvas height as reference — _build_state will override with content-based scale
            ref = h
            return max(96, min(1024, int(round(draw * ref / 1024.0
                                               * self.ASSET_SCALE))))
        return min(draw, 1024)

    def load(self):
        base = asset_path()
        #  --  v98: Try loading sprite_meta.json for geometry -- 
        meta_path = os.path.join(base, 'sprite_meta.json')
        if os.path.exists(meta_path) and self._sprite_meta is None:
            try:
                with open(meta_path, 'r') as fp:
                    self._sprite_meta = json.load(fp)
            except Exception:
                self._sprite_meta = {}
        #  --  v64 geometry table: read each state's first frame size (tight assets have constant size per state) --
        for state, (prefix, _c, _f, _l, _i) in ANIMS.items():
            if state in self.geo or state in self.alias:
                pass
            else:
                for ext in ('webp', 'png'):
                    fn = os.path.join(base, f'{prefix}_000.{ext}')
                    if os.path.exists(fn):
                        r = QImageReader(fn)
                        sz = r.size()
                        if sz.isValid():
                            self.geo[state] = (sz.width(), sz.height())
                        break
            self.geo.setdefault(state, (1024, 1024))
        #  --  v64 alias table: same-prefix states share frame list (potty->sit, potty_run->run) -- 
        for state, (prefix, _c, _f, _l, _i) in ANIMS.items():
            owner = next((s2 for s2, (p2, _c2, _f2, _l2, _i2) in ANIMS.items()
                          if p2 == prefix), None)
            if owner and owner != state:
                self.alias[state] = owner
                self.geo.setdefault(state, self.geo.get(owner, (1024, 1024)))
        #  --  Loading: aliases point to owner list; lazy states placeholder empty tables loaded on first trigger  -- 
        # v99b: ALL states are LAZY. idle sync-loads only frame 0 for first screen (<10ms),
        # then startup preload queue loads everything in background.
        for state in ANIMS:
            if state in self.alias:
                owner = self.alias[state]
                self.frames[state] = self.frames[owner]
                self.frames_m[state] = self.frames_m[owner]
                self.lift_map[state] = self.lift_map[owner]
            else:
                self.frames[state] = []
                self.frames_m[state] = []
                self.lift_map[state] = []
        # Sync-load idle ALL frames (not just frame 0) — needed for animation on first screen
        # Background preload is async; idle must be ready immediately or pet appears frozen
        idle_imgs, idle_lift = self._build_state('idle')
        if idle_imgs:
            self.frames['idle'] = idle_imgs
            self.frames_m['idle'] = [None] * len(idle_imgs)
            self.lift_map['idle'] = idle_lift
        # v19: Per-frame leg cutting  --  run frames contain gallop jumps (per-frame body_bot displacement up to 31px),
        # fixed cut line (only frame 0) misaligns leg blocks on jump frames. Cut per-frame by own body bottom,
        # preserving in-frame gallop undulation while keeping cut line aligned with body.
        # potty_run reuses run frames, same rig
        rig_map = {}
        for state, (prefix, _c, _f, _l, _i) in ANIMS.items():
            if prefix in LEG_RIG:
                rig_map[state] = LEG_RIG[prefix]
        for state, geo in rig_map.items():
            imgs = self.frames.get(state, [])
            imgs_m = self.frames_m.get(state, [])
            if not imgs or not imgs_m:
                continue
            parts, parts_m = [], []
            for img, img_m in zip(imgs, imgs_m):
                bb = self._body_bottom(img)
                if bb is None:
                    cut = geo['cut_row']
                else:
                    cut = max(40, min(240, bb - 8))   # cut line = 8 rows above body bottom
                g2 = dict(geo, cut_row=cut,
                          front_hip=(geo['front_hip'][0], cut + 1),
                          rear_hip=(geo['rear_hip'][0], cut + 1))
                parts.append(self._cut_rig(img, g2, mirrored=False))
                parts_m.append(self._cut_rig(img_m, g2, mirrored=True))
            self.rig_parts[state] = parts
            self.rig_parts_m[state] = parts_m

    def _sync_first_frame(self, state):
        """v99b: DEPRECATED — do not call from main thread. All loading is async via ensure_state -> _StateLoadThread.
        Only kept as internal helper for background preload queue."""
        owner = self.alias.get(state, state)
        if owner not in self.LAZY:
            return
        if self.frames.get(owner) or owner in self._lazy_threads:
            return
        try:
            imgs, lift = self._build_state(owner)
        except Exception:
            return
        if imgs:
            self.frames[owner] = imgs
            self.frames_m[owner] = [None] * len(imgs)
            self.lift_map[owner] = lift
            self._loaded_order = getattr(self, '_loaded_order', [])
            if owner not in self._loaded_order:
                self._loaded_order.append(owner)

    def ensure_state(self, state):
        """v99b: Pure async — start background thread to load frames.
        Main thread never blocks. get() returns empty QImage while loading."""
        owner = self.alias.get(state, state)
        if owner not in self.LAZY or self.frames.get(owner):
            return
        if owner in self._lazy_threads:
            return
        t = _StateLoadThread(self, owner)
        self._lazy_threads[owner] = t
        t.finished.connect(lambda s=owner, th=t: self._on_lazy_done(s, th))
        t.start()

    def _on_lazy_done(self, state, t):
        self._lazy_threads.pop(state, None)
        if t.imgs is not None:
            # v94-fix race: During lazy-load thread build, bank may be replaced by fullbank/zoom swap,
            # old code wrote back to old bank = new bank never gets full frame table (action stuck on first frame = action disappears).
            # Route via _replaced_by chain to latest bank before writing.
            bank = self
            while getattr(bank, '_replaced_by', None) is not None:
                bank = bank._replaced_by
            # v100-fix: If draw_size changed during lazy load (zoom), rescale frames to match new bank
            imgs = t.imgs
            if hasattr(t, '_draw_size') and abs(t._draw_size - bank.draw_size) > 1 and bank.draw_size > 0:
                sc = bank.draw_size / float(t._draw_size)
                imgs = [img.scaled(max(2, int(round(img.width() * sc))),
                                   max(2, int(round(img.height() * sc))),
                                   Qt.KeepAspectRatio, Qt.FastTransformation)
                        for img in t.imgs]
            bank.frames[state] = imgs
            bank.frames_m[state] = [None] * len(imgs)
            bank.lift_map[state] = t.lift
            # v67: After full frame table replaces first-frame fast path, current frame index may overflow (first-frame bank length 1),
            # notify window to reset animation phase to avoid IndexError/stuck frame.
            cb = getattr(bank, 'on_state_reloaded', None)
            if cb:
                cb(state)
        t.deleteLater()

    def _load_state(self, state, frame_limit=None):
        imgs, lift = self._build_state(state, frame_limit)
        self.frames[state] = imgs
        self.frames_m[state] = [None] * len(imgs)
        self.lift_map[state] = lift
        # v66 LRU: Record load order (for unloading least-recently-used lazy states)
        self._loaded_order = getattr(self, '_loaded_order', [])
        if state in self.LAZY and state not in self._loaded_order:
            self._loaded_order.append(state)

    def unload_idle_lazy(self, active_state, keep=3):
        """v66: Memory reclaim  --  loaded lazy states exceeding keep count and not current state,
        unload least-recently-triggered (clear frames/frames_m/lift back to lazy placeholder).
        Aliased states (potty->sit), current state, and resident states not unloaded. Return unload count."""
        order = getattr(self, '_loaded_order', [])
        n = 0
        for st in list(order):
            if len(order) - n <= keep:
                break
            if st == active_state or not self.frames.get(st):
                continue
            # Alias state points to it -> don't unload
            if any(self.alias.get(s2) == st for s2 in self.alias):
                continue
            self.frames[st] = []
            self.frames_m[st] = []
            self.lift_map[st] = []
            order.remove(st)
            n += 1
        return n

    def _build_state(self, state, frame_limit=None):
        """v99: Load pre-scaled assets directly (no runtime scaling).
        Assets are baked offline at DRAW_MAX size, engine loads with zero scaling.
        Falls back to legacy scaled path if assets are full-size."""
        base = asset_path()
        prefix, count, _f, _l, _i = ANIMS[state]
        tight = state in self.TIGHT
        draw = self._state_draw(state)
        if frame_limit:
            count = min(count, frame_limit)
        raw_imgs = []
        # P5-fix: For tight states, collect raw frames first to compute unified content-based scale
        # Old approach: scale each frame by canvas height → content height varies → dog size pulsates.
        # New: scan content bbox of all frames, find max content height, scale uniformly by content.
        if tight:
            for i in range(count):
                fn = os.path.join(base, f'{prefix}_{i:03d}.webp')
                if not os.path.exists(fn):
                    fn = os.path.join(base, f'{prefix}_{i:03d}.png')
                img = QImage(fn)
                if not img.isNull():
                    raw_imgs.append(img.convertToFormat(QImage.Format_ARGB32_Premultiplied))
            # Scan content bbox of all raw frames to find max content height and width
            max_content_h = 0
            max_content_w = 0
            content_tops = []
            content_bots = []
            for img in raw_imgs:
                ct, cb = self._content_bbox_v(img)
                cl, cr = self._content_bbox_h(img)
                content_tops.append(ct)
                content_bots.append(cb)
                ch = cb - ct + 1 if cb >= ct else img.height()
                cw = cr - cl + 1 if cr >= cl else img.width()
                if ch > max_content_h:
                    max_content_h = ch
                if cw > max_content_w:
                    max_content_w = cw
            # v101-fix: Use max dimension (not just height) for scale calculation.
            # Side-facing states (walk/run) have content_w >> content_h; scaling by height only
            # makes frames wider than draw → paintEvent clips left/right edges of the dog.
            max_dim = max(max_content_h, max_content_w)
            sc = draw / float(max_dim) if max_dim > 0 else 1.0
            imgs = []
            for img in raw_imgs:
                w, h = img.width(), img.height()
                img = img.scaled(max(2, int(round(w * sc))),
                                 max(2, int(round(h * sc))),
                                 Qt.KeepAspectRatio, Qt.FastTransformation)
                imgs.append(img)
        else:
            imgs = []
            for i in range(count):
                fn = os.path.join(base, f'{prefix}_{i:03d}.webp')
                if not os.path.exists(fn):
                    fn = os.path.join(base, f'{prefix}_{i:03d}.png')
                img = QImage(fn)
                if img.isNull():
                    continue
                img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
                img = img.scaled(draw, draw,
                                  Qt.KeepAspectRatio, Qt.FastTransformation)
                imgs.append(img)
        if not tight and imgs:
            # v49: Mirror lazy generation  --  get() mirrors centered draw x draw canvas on first request
            # (centered = naturally symmetric, no shift error).
            imgs, _sh = self._center_frames(imgs)
        #  --  Per-frame lift height: content bbox bottom relative to max bottom of full sequence, normalized 0..1 -- 
        # Pure Python sample scan: bottom-up per row, every 8 columns (feet usually hit in first few rows)
        # v66: cacheKey caches bottom (repeat action trigger/zoom rebuild no rescan, eliminates trigger CPU spike)
        bottoms = []
        for im in imgs:
            key = im.cacheKey()
            if key in _BODY_BOTTOM_CACHE2:
                bottoms.append(_BODY_BOTTOM_CACHE2[key])
                continue
            buf = im.constBits()
            buf.setsize(im.byteCount())
            data = bytes(buf)   # bytes index returns int, can compare directly
            w4 = im.width() * 4
            bpl = im.bytesPerLine()
            cols = range(0, w4, 32)   # Sample alpha channel every 8 columns
            bottom = im.height() - 1
            for row in range(im.height() - 1, -1, -1):
                rowbase = row * bpl + 3
                if any(data[rowbase + c] > 16 for c in cols):
                    bottom = row
                    break
            if len(_BODY_BOTTOM_CACHE2) > 2000:
                _BODY_BOTTOM_CACHE2.clear()
            _BODY_BOTTOM_CACHE2[key] = bottom
            bottoms.append(bottom)
        if bottoms:
            ground = max(bottoms)
            var = ground - min(bottoms)
            # Shadow flicker cause: small bottom jitter (<30px) from leg pose/breathing is not real jumping,
            # old code normalized with max(6.0, var) amplifying 12px leg lift to 100% airborne -> shadow shrinks 45% per step.
            # Variance <30px treated as grounded, lift=0; only real jumping states (run/jump/stretch etc) keep shadow linkage.
            if var < 30:
                lift = [0.0 for _ in bottoms]
            else:
                span = float(var)
                lift = [max(0.0, min(1.0, (ground - b) / span)) for b in bottoms]
        else:
            lift = []
        return imgs, lift

    @staticmethod
    def _body_bottom(img):
        """First 'wide row' (>62% of max row width) above content bottom = body bottom; no content returns None.
        v66: cacheKey cache (same image no rescan, zoom rebuild/repeat rig saves CPU)."""
        key = img.cacheKey()
        cache = _BODY_BOTTOM_CACHE
        if key in cache:
            return cache[key]
        w, h = img.width(), img.height()
        buf = img.constBits()
        buf.setsize(img.byteCount())
        data = bytes(buf)
        bpl = img.bytesPerLine()
        row_w = []
        for y in range(h):
            rb = y * bpl + 3
            row_w.append(sum(1 for x in range(0, w * 4, 8) if data[rb + x] > 24))
        max_w = max(row_w)
        if max_w < 8:
            cache[key] = None
            return None
        rows = [y for y in range(h) if row_w[y] > 0]
        bot = rows[-1]
        for y in range(bot, -1, -1):
            if row_w[y] > max_w * 0.62:
                if len(cache) > 400:
                    cache.clear()
                cache[key] = y
                return y
        if len(cache) > 400:
            cache.clear()
        cache[key] = bot
        return bot

    def _content_bbox_v(self, img):
        """P5-fix: Get vertical content bbox (top, bottom rows with alpha>24).
        4x downsampled for speed. Returns (top, bottom) 0-indexed, or (0, h-1) if no content."""
        w, h = img.width(), img.height()
        if w < 1 or h < 1:
            return 0, max(0, h - 1)
        buf = img.constBits()
        buf.setsize(img.byteCount())
        # Python 3.12 fix: sip.voidptr[index] returns bytes, not int; convert to memoryview
        buf = memoryview(buf).cast('B')
        bpl = img.bytesPerLine()
        top = h
        bot = 0
        found = False
        for y in range(0, h, 4):
            rb = y * bpl + 3
            for x in range(0, w * 4, 32):
                if buf[rb + x] > 24:
                    if y < top:
                        top = y
                    if y > bot:
                        bot = y
                    found = True
                    break
        # Refine top/bot by checking adjacent rows
        if found:
            # Refine top (check rows above first hit)
            for y in range(max(0, top - 4), top):
                rb = y * bpl + 3
                for x in range(0, w * 4, 32):
                    if buf[rb + x] > 24:
                        top = y
                        break
            # Refine bot (check rows below last hit)
            for y in range(bot + 1, min(h, bot + 5)):
                rb = y * bpl + 3
                for x in range(0, w * 4, 32):
                    if buf[rb + x] > 24:
                        bot = y
                        break
            return top, bot
        return 0, h - 1

    def _content_bbox_h(self, img):
        """v101: Get horizontal content bbox (left, right cols with alpha>24).
        4x downsampled for speed. Returns (left, right) 0-indexed, or (0, w-1) if no content."""
        w, h = img.width(), img.height()
        if w < 1 or h < 1:
            return 0, max(0, w - 1)
        buf = img.constBits()
        buf.setsize(img.byteCount())
        buf = memoryview(buf).cast('B')
        bpl = img.bytesPerLine()
        left = w
        right = 0
        found = False
        for x in range(0, w, 4):
            xb = x * 4 + 3
            for y in range(0, h, 4):
                rb = y * bpl
                if buf[rb + xb] > 24:
                    if x < left:
                        left = x
                    if x > right:
                        right = x
                    found = True
                    break
        if found:
            for x in range(max(0, left - 4), left):
                xb = x * 4 + 3
                for y in range(0, h, 4):
                    if buf[y * bpl + xb] > 24:
                        left = x
                        break
            for x in range(right + 1, min(w, right + 5)):
                xb = x * 4 + 3
                for y in range(0, h, 4):
                    if buf[y * bpl + xb] > 24:
                        right = x
                        break
            return left, right
        return 0, w - 1

    def _content_centroid_x(self, img):
        """Content (alpha>24) horizontal centroid x; no content returns None
        v48: 4x downsample (old per-pixel pure Python scan was 70% of load(), 20s at 2.5x zoom).
        Uniform downsample centroid error <2px, shift uses int(round) so output unchanged."""
        w, h = img.width(), img.height()
        buf = img.constBits()
        buf.setsize(img.byteCount())
        data = bytes(buf)
        bpl = img.bytesPerLine()
        sum_x, cnt = 0.0, 0
        for y in range(0, h, 4):
            rowbase = y * bpl + 3  # ARGB32 alpha channel
            for x in range(0, w, 4):
                if data[rowbase + x * 4] > 24:
                    sum_x += x
                    cnt += 1
        return sum_x / cnt if cnt else None

    def _center_frames(self, imgs, shift=None):
        """v11 frame horizontal centering: shared offset across sequence, fixes 'out of frame'.
        Cause: walk frame content hugs left edge (left margin=0), centroid offset -44px, after mirror dog head at window edge;
        and inter-frame centroid drift causes left-right wobble. Use sequence-average centroid for unified shift  -- 
        both centers dog in window and eliminates inter-frame jitter. v25: draw at current zoom size.
        v48: shift can be external (mirror frame formula derivation), returns (out, shift) for caller to derive mirror offset."""
        draw = self.draw_size
        if shift is None:
            cxs = [c for c in (SpriteBank._content_centroid_x(im) for im in imgs) if c is not None]
            if not cxs:
                return imgs, 0
            shift = int(round(draw / 2 - sum(cxs) / len(cxs)))
        if shift == 0:
            return imgs, 0
        out = []
        for im in imgs:
            canvas = QImage(draw, draw, QImage.Format_ARGB32_Premultiplied)
            canvas.fill(Qt.transparent)
            p = QPainter(canvas)
            p.drawImage(shift, 0, im)
            p.end()
            out.append(canvas)
        return out, shift

    def _cut_rig(self, img, geo, mirrored=False):
        """Split sprite into body/front-leg/rear-leg three blocks (with seam fade)
        mirrored=True: input is mirrored image: cut line mirrored, parts named by anatomy"""
        # Normalize to draw_size canvas (horizontal center/bottom align), strictly aligned with offline bake geometry
        draw = self.draw_size
        canvas = QImage(draw, draw, QImage.Format_ARGB32_Premultiplied)
        canvas.fill(Qt.transparent)
        cp = QPainter(canvas)
        cp.drawImage((draw - img.width()) // 2,
                     draw - img.height(), img)
        cp.end()
        img = canvas

        w, h = img.width(), img.height()
        cut = geo['cut_row']
        split = geo['split_x'] if not mirrored else w - geo['split_x']
        # Body block: full width, extends below cut line by RIG_BODY_OVERLAP rows (covers hip seam)
        body = img.copy(0, 0, w, min(h, cut + RIG_BODY_OVERLAP))
        # Leg block: starts RIG_LEG_TOP rows above cut line (overlaps body, no bottom gap during rotation)
        leg_y0 = max(0, cut - RIG_LEG_TOP)
        leg_h = h - leg_y0
        left = img.copy(0, leg_y0, split, leg_h)
        right = img.copy(split, leg_y0, w - split, leg_h)
        if mirrored:
            # After mirror, anatomical front leg is on right
            front, front_x0 = right, split
            rear, rear_x0 = left, 0
        else:
            front, front_x0 = left, 0
            rear, rear_x0 = right, split
        # Leg block top fade (seam blending):DestinationIn with alpha gradient mask
        for part in (front, rear):
            mp = QPainter(part)
            mp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            grad = QLinearGradient(0, 0, 0, RIG_FADE)
            grad.setColorAt(0.0, QColor(0, 0, 0, 0))
            grad.setColorAt(1.0, QColor(0, 0, 0, 255))
            mp.fillRect(0, 0, part.width(), RIG_FADE, QBrush(grad))
            mp.end()
        # Hip joint pivot: transform to each leg block's local coordinates
        fhx, fhy = geo['front_hip']
        rhx, rhy = geo['rear_hip']
        if mirrored:
            fhx, rhx = w - fhx, w - rhx
        return {'body': body,
                'front': front, 'front_x0': front_x0,
                'front_pivot': (fhx - front_x0, fhy - leg_y0),
                'rear': rear, 'rear_x0': rear_x0,
                'rear_pivot': (rhx - rear_x0, rhy - leg_y0),
                'leg_y0': leg_y0,
                'amp_deg': geo['amp_deg']}

    def get(self, state, idx, flipped):
        state = self.alias.get(state, state)   # v64: Alias resolution (potty->sit), lazy-owner safe
        if flipped:
            bank = self.frames_m[state]
            i = idx % len(bank) if bank else 0
            if not bank or bank[i] is None:
                src = self.frames.get(state) or []
                if not src:
                    return QImage()   # v64 lazy-load incomplete -> empty image skip draw
                # v49 mirror lazy generation: mirror on first request, memory halved
                bank[i] = src[i].mirrored(True, False)
            return bank[i]
        bank = self.frames[state]
        if not bank:
            return QImage()           # v64 lazy-load incomplete -> empty image skip draw
        return bank[idx % len(bank)]


# ═══════════════════════════════════════════════════════════
#  Particle system
# ═══════════════════════════════════════════════════════════
class ParticleSystem:
    HEART, ZZZ, STINK, SPARKLE, CRUMB, BUBBLE, DUST = range(7)

    def __init__(self):
        self.particles = []

    def emit(self, ptype, x, y, count=1, text=''):
        for _ in range(count):
            life = random.uniform(1.0, 2.2)
            self.particles.append({
                'type': ptype,
                'x': x + random.uniform(-12, 12),
                'y': y + random.uniform(-8, 8),
                'vx': random.uniform(-0.4, 0.4),
                'vy': random.uniform(-1.4, -0.6),
                'life': life, 'max_life': life,
                'size': random.uniform(9, 16),
                'phase': random.uniform(0, math.tau),
                'text': text,
            })

    def update(self, dt):
        alive = []
        for p in self.particles:
            p['life'] -= dt
            if p['life'] <= 0:
                continue
            p['phase'] += dt * 3
            p['x'] += p['vx'] + math.sin(p['phase']) * 0.35
            p['y'] += p['vy']
            t = p['type']
            if t == self.ZZZ:
                p['vy'] = -0.45
                p['x'] += math.sin(p['phase'] * 0.7) * 0.4
            elif t == self.STINK:
                p['vy'] = -0.6
            elif t == self.CRUMB or t == self.DUST:
                p['vy'] += 0.1
            alive.append(p)
        self.particles = alive

    def draw(self, painter):
        for p in self.particles:
            alpha = max(0.0, min(1.0, p['life'] / p['max_life']))
            x, y, s = p['x'], p['y'], p['size']
            t = p['type']

            if t == self.HEART:
                c = QColor(255, 105, 125, int(alpha * 230))
                painter.setPen(Qt.NoPen)
                painter.setBrush(c)
                r = s * 0.5 * (0.6 + alpha * 0.4)
                path = QPainterPath()
                path.moveTo(x, y + r * 0.35)
                path.cubicTo(x - r, y - r * 0.45, x - r * 0.5, y - r, x, y - r * 0.35)
                path.cubicTo(x + r * 0.5, y - r, x + r, y - r * 0.45, x, y + r * 0.35)
                painter.drawPath(path)

            elif t == self.ZZZ:
                c = QColor(150, 180, 255, int(alpha * 200))
                f = QFont('Arial', max(6, int(s * alpha)))
                f.setBold(True)
                painter.setFont(f)
                painter.setPen(c)
                painter.drawText(QPointF(x, y), 'Z' if s > 12 else 'z')

            elif t == self.STINK:
                c = QColor(140, 180, 80, int(alpha * 130))
                painter.setPen(QPen(c, 2))
                painter.setBrush(Qt.NoBrush)
                path = QPainterPath()
                for i in range(7):
                    yy = y - i * 3.5
                    xx = x + math.sin(p['phase'] + i * 0.9) * 4
                    if i == 0:
                        path.moveTo(xx, yy)
                    else:
                        path.lineTo(xx, yy)
                painter.drawPath(path)

            elif t == self.SPARKLE:
                c = QColor(255, 220, 100, int(alpha * 255))
                painter.setPen(Qt.NoPen)
                painter.setBrush(c)
                r = s * 0.28 * alpha
                painter.drawEllipse(QPointF(x, y), r, r)
                painter.setPen(QPen(c, 1))
                painter.drawLine(QPointF(x - r * 2, y), QPointF(x + r * 2, y))
                painter.drawLine(QPointF(x, y - r * 2), QPointF(x, y + r * 2))

            elif t in (self.CRUMB, self.DUST):
                c = QColor(200, 165, 110, int(alpha * 200)) if t == self.CRUMB \
                    else QColor(180, 180, 185, int(alpha * 160))
                painter.setPen(Qt.NoPen)
                painter.setBrush(c)
                painter.drawEllipse(QPointF(x, y), s * 0.2, s * 0.16)

            elif t == self.BUBBLE:
                # Speech bubble text (e.g. "Woof!")
                f = QFont(_UI_FONT, 11)
                f.setBold(True)
                painter.setFont(f)
                text = p['text']
                tw = QFontMetrics(f).horizontalAdvance(text)
                bw, bh = tw + 18, 26
                bx, by = x - bw / 2, y - bh
                c_bg = QColor(255, 255, 255, int(alpha * 235))
                c_bd = QColor(90, 100, 120, int(alpha * 255))
                painter.setPen(QPen(c_bd, 1.5))
                painter.setBrush(c_bg)
                painter.drawRoundedRect(QRectF(bx, by, bw, bh), 12, 12)
                # Little tail
                path = QPainterPath()
                path.moveTo(x - 4, by + bh - 1)
                path.lineTo(x, by + bh + 6)
                path.lineTo(x + 5, by + bh - 1)
                painter.drawPath(path)
                painter.setPen(QColor(70, 80, 100, int(alpha * 255)))
                painter.drawText(QPointF(x - tw / 2, by + 18), text)


# ═══════════════════════════════════════════════════════════
#  Physics system
# ═══════════════════════════════════════════════════════════
class Physics:
    def __init__(self):
        self.vx = 0.0
        self.vy = 0.0
        self.active = False
        self.gravity = 1600.0
        self.restitution = 0.38
        self.squash = 0.0   # Landing squash timer

    def throw(self, vx, vy):
        self.vx = max(-1400, min(1400, vx))
        self.vy = max(-1400, min(1400, vy))
        self.active = True

    def update(self, dt, win, floor_y, screen_l, screen_r):
        if not self.active:
            self.squash = max(0, self.squash - dt * 4)
            return 0
        self.vy += self.gravity * dt
        x = win.x() + self.vx * dt
        y = win.y() + self.vy * dt
        bounced = 0

        # Ground
        if y >= floor_y:
            y = floor_y
            if abs(self.vy) > 120:
                self.vy = -self.vy * self.restitution
                self.vx *= 0.85
                bounced = abs(self.vy)
                self.squash = 1.0
            else:
                self.vy = 0.0
                self.vx *= 0.8
                if abs(self.vx) < 15:
                    self.vx = 0.0
                    self.active = False
                    self.squash = 0.6
        # Left/right walls
        if x < screen_l:
            x = screen_l
            self.vx = -self.vx * 0.5
        elif x > screen_r:
            x = screen_r
            self.vx = -self.vx * 0.5
        # Ceiling: thrown pets can't fly off screen top (old code had no upper bound -> pet flew off visible area)
        if y < 0:
            y = 0
            if self.vy < 0:
                self.vy = -self.vy * 0.35

        win.move(int(x), int(y))
        self.squash = max(0, self.squash - dt * 4)
        return bounced


# ═══════════════════════════════════════════════════════════
#  Main window
# ═══════════════════════════════════════════════════════════
WINDOW_TITLE = PET_NAME_ASCII + '_MainWindow'  # Fixed window title: for FindWindow to locate and activate on repeated launch (derived from CONFIG, no change needed for new pet)


class PetWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        # P3 fix: macOS uses Qt.Tool (no focus steal, no Cmd-Tab entry, fixes Chrome keyboard bug)
        # Windows uses Qt.Window + WS_EX_NOACTIVATE (Tool windows get hidden on app switch)
        if sys.platform == 'darwin':
            self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        # P3: disable keyboard focus (attribute may not exist in all PyQt5 versions)
        if hasattr(Qt, 'WA_InputMethodDisabled'):
            self.setAttribute(Qt.WA_InputMethodDisabled, True)
        # P3-fix2: Never accept keyboard focus — prevents stealing input from Chrome/other apps
        self.setFocusPolicy(Qt.NoFocus)

        # v25 (P9): Read persisted zoom ratio (default 1.0)
        self.zoom = load_zoom()
        self.setFixedSize(int(CANVAS * self.zoom), int(CANVAS * self.zoom))

        self.bank = SpriteBank()
        # v2 HiDPI: Texture size = logical size x dpr, Retina device pixel 1:1 (no more 2x blur)
        self.bank.draw_size = int(DRAW_SIZE * self.zoom * _target_dpr(self))
        # v67: Startup fast path  --  main thread only sync-loads FAST_BOOT four states limited frames (<300ms first screen),
        # full resident set built in background then atomic swap (old sync full = 800+ frame decode, startup stutter + blank).
        self.bank.fast_boot = True
        self.bank.load()
        self.bank.on_state_reloaded = self._on_state_reloaded
        # v99: No _fullbank_thread — all states are LAZY, loaded on-demand only
        self._fullbank_thread = None
        self.particles = ParticleSystem()
        self.physics = Physics()
        # Windows native extended style: pet window no activation, no focus stealing (Tool-like behavior without Tool's disappear bug)
        if sys.platform == 'win32':
            try:
                import ctypes
                GWL_EXSTYLE = -20
                WS_EX_NOACTIVATE = 0x08000000
                WS_EX_TOOLWINDOW = 0x00000080  # No taskbar button (original Qt.Tool feel)
                user32 = ctypes.windll.user32
                st = user32.GetWindowLongW(int(self.winId()), GWL_EXSTYLE)
                user32.SetWindowLongW(int(self.winId()), GWL_EXSTYLE,
                                      st | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
            except Exception:
                pass

        self.state = 'idle'
        self.state_started = time.perf_counter()
        self.anim_elapsed = 0.0
        self.frame_idx = 0
        self.facing = 1          # 1=right -1=left (assets face left, mirror when moving right)
        self.flipped = False

        # Modes
        self.mode = 'taskbar'    # desktop(drag-drop fixed spot doing actions) / taskbar(taskbar roaming) / tease(teasing)
        self.roam_target = None
        self.tease_last_cursor = None

        # Properties
        self.fullness = 80.0
        self.happiness = 70.0
        self.energy = 90.0
        self.potty_need = 0.0

        # AI
        self.ai_timer = random.uniform(3, 7)
        self.walk_dir = random.choice([-1, 1])
        self.state_duration = {}  # Timed states

        # Drag
        self.dragging = False
        self.drag_off = QPoint()
        self.mouse_hist = []
        self.throw_vel = (0, 0)

        # Render transforms & motion state
        self.roll_angle = 0.0
        self.vel_x = 0.0        # Current horizontal velocity px/s (eased)
        self.move_acc = 0.0     # Subpixel accumulator
        self.pop_t = 0.0        # State entry spring
        self.antic_t = 0.0      # Start antic crouch
        self.settle_t = 0.0     # Stop settle squash
        self.turn_phase = None  # Turn animation 0..1
        self.turn_flipped = False
        self.turn_new_facing = 1
        self.smooth_air = 0.0   # Smoothed airborne height (prevents per-frame shadow jitter/flicker)
        self.micro = None       # Idle micro-action (head tilt/shake/small jump)
        self.sleep_twitch_t = 0.0
        self.sleep_twitch_next = random.uniform(5, 9)

        # Leg rig animation phase (continuous accumulator, not limited by 60fps frame steps)
        self.leg_phase = 0.0    # Gait phase [0, 2pi)
        self.leg_amp = 0.0      # Swing amplitude (ease-in on start, ease-out on stop)
        self._last_paint_dt = time.perf_counter()
        self._tick_cur = 16     # v66: Current timer interval (adaptive)

        # Initial position: screen bottom (positioned by zoomed window size)
        sg = QApplication.primaryScreen().geometry()
        self.floor_y = sg.bottom() - int(CANVAS * self.zoom) - 45
        self.move(sg.center().x() - int(CANVAS * self.zoom) // 2, self.floor_y)

        self.last_t = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)  # Windows default timer jitter 15-31ms, precise mode reduces frame interval variance
        self.timer.timeout.connect(self.game_loop)
        self.timer.start(16)
        self.show()

        # v99: Background-preload lazy states after startup (walk/run/eat etc)
        QTimer.singleShot(50, self._start_lazy_preload)

        # v25 (P1): Visibility guard  --  whatever causes window hide/minimize, force restore within 2s.
        # Pet persists on desktop: only right-click menu "Exit" can truly close it.
        self._vis_timer = QTimer(self)
        self._vis_timer.timeout.connect(self._ensure_visible)
        self._vis_timer.start(2000)

    #  --  --  --  --  -- ─ v25 (P1/P9): Persistence guard & zoom  --  --  --  --  -- ─
    def _ensure_visible(self):
        """Force restore when window invisible/minimized, refresh stay-on-top to prevent being covered by other apps"""
        if not self.isVisible() or self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
            self.show()
        # v26: Refresh stay-on-top  --  WindowStaysOnTopHint may be overridden by other top windows
        # P3-fix2: DO NOT call raise_() or activateWindow() here — these steal focus from Chrome/other apps
        # Instead use lower-level re-raise that doesn't change Z-order focus

    def changeEvent(self, event):
        """Intercept external minimize (e.g. Win+D/taskbar "Show Desktop" briefly hides all windows), stay persistent"""
        if event.type() == event.WindowStateChange and self.isMinimized():
            QTimer.singleShot(0, self._ensure_visible)
        super().changeEvent(event)

    def set_zoom(self, new_zoom):
        """v25 (P9): Runtime zoom switch  --  rebuild sprites + adjust window + bottom anchor, and persist
        v48: Rebuild moved to background thread (old main thread sync load() = 579 frame reload + pixel scan, freezes UI).
        During load, old sprite auto-scaled by paintEvent top-level scale(zoom), atomic swap on completion."""
        new_zoom = max(ZOOM_MIN, min(ZOOM_MAX, new_zoom))
        if abs(new_zoom - self.zoom) < 1e-6:
            return
        self.zoom = new_zoom
        save_zoom(new_zoom)
        cw = int(CANVAS * new_zoom)
        old_w, old_h = self.width(), self.height()
        self.setFixedSize(cw, cw)
        sg = QApplication.primaryScreen().geometry()
        self.floor_y = sg.bottom() - cw - 45
        # Zoom anchored at window center, clamped within screen
        nx = self.x() + old_w // 2 - cw // 2
        if self.mode == 'desktop':
            # drag-drop fixed mode: keep current y position, do not snap back to bottom
            ny = self.y() + old_h - cw
        else:
            ny = min(self.y() + old_h - cw, self.floor_y)
        nx = max(0, min(nx, sg.right() - cw))
        ny = max(0, min(ny, sg.bottom() - cw))
        self.move(nx, ny)
        t = _LoadThread(int(DRAW_SIZE * new_zoom * _target_dpr(self)))
        t.finished.connect(self._on_zoom_loaded)
        self._load_seq = getattr(self, '_load_seq', 0) + 1
        t._seq = self._load_seq
        self._pending_loads = getattr(self, '_pending_loads', [])
        self._pending_loads.append(t)
        t.start()
        self.update()

    def _on_zoom_loaded(self):
        """Background sprite build complete -- only latest takes effect, atomic bank swap, UI never blocks"""
        t = self.sender()
        try:
            self._pending_loads.remove(t)
        except (ValueError, AttributeError):
            pass
        if t._seq == getattr(self, '_load_seq', 0) and t.result is not None:
            old = self.bank
            new = t.result
            # v94-fix: Migrate loaded lazy state frame tables (old zoom rebuild lost action frames = actions disappear)
            # v100-fix: Rescale migrated frames to new draw_size (zoom change changes draw_size,
            # old frames rendered at old draw_size would be mis-scaled by k=DRAW_SIZE/new_draw)
            _new_draw = new.draw_size
            _old_draw = old.draw_size
            _need_rescale = abs(_new_draw - _old_draw) > 1
            for st, fr in old.frames.items():
                if fr and st in new.LAZY:
                    if _need_rescale:
                        sc = _new_draw / float(_old_draw) if _old_draw > 0 else 1.0
                        new.frames[st] = [img.scaled(max(2, int(round(img.width() * sc))),
                                                      max(2, int(round(img.height() * sc))),
                                                      Qt.KeepAspectRatio, Qt.FastTransformation)
                                          for img in fr]
                    else:
                        new.frames[st] = fr
                    new.frames_m[st] = [None] * len(new.frames[st])
                    new.lift_map[st] = old.lift_map.get(st) or []
            new._loaded_order = list(getattr(old, '_loaded_order', []))
            old._replaced_by = new   # v94-fix: In-flight lazy load write-back routes to latest bank
            self.bank = new
            self.bank.on_state_reloaded = self._on_state_reloaded
            self.update()
        t.deleteLater()

    def _on_fullbank_loaded(self):
        """v67: Background full resident set build complete -> atomic swap. Lazy state loaded first-frame tables retained
        (full bank's lazy set is empty placeholder, after swap _loaded_order retained, frames retained).
        v96-fix: Do NOT reset frame_idx/anim_elapsed after swap. The fast_boot now loads ALL frames
        (not 30), so the swap is identical frame data - no frame count change = no jump.
        Old reset caused mid-animation restart = visible stutter on first EXE open."""
        t = self._fullbank_thread
        self._fullbank_thread = None
        if t.result is None:
            t.deleteLater()
            return
        new = t.result
        # Retain lazy state loaded frame tables (actions triggered by user after startup not lost)
        # v100-fix: Rescale if draw_size changed (shouldn't happen in fullbank swap, but guard)
        _new_draw = new.draw_size
        _old_draw = self.bank.draw_size
        _need_rescale = abs(_new_draw - _old_draw) > 1
        for st, fr in self.bank.frames.items():
            if fr and st in new.LAZY:
                if _need_rescale:
                    sc = _new_draw / float(_old_draw) if _old_draw > 0 else 1.0
                    new.frames[st] = [img.scaled(max(2, int(round(img.width() * sc))),
                                                  max(2, int(round(img.height() * sc))),
                                                  Qt.KeepAspectRatio, Qt.FastTransformation)
                                      for img in fr]
                else:
                    new.frames[st] = fr
                new.frames_m[st] = [None] * len(new.frames[st])
                new.lift_map[st] = self.bank.lift_map.get(st) or []
        new._loaded_order = list(getattr(self.bank, '_loaded_order', []))
        new.on_state_reloaded = self._on_state_reloaded
        self.bank._replaced_by = new   # v94-fix: In-flight lazy load write-back routes to latest bank
        self.bank = new
        # v96-fix: No frame_idx/anim_elapsed reset - bank swap is now transparent
        # (fast_boot loads full 121 frames, swap replaces with identical data)
        self.update()
        t.deleteLater()
        # v98: Disabled startup preload — strict on-demand loading only.
        # Lazy states load when user triggers them via menu, not at startup.
        # This eliminates startup IO/CPU spike that caused first-open stutter.

    def _start_lazy_preload(self):
        """v99b: Parallel background preload — spawn 3 threads at a time for all lazy states.
        With FastTransformation, each state loads in ~50-100ms, so 3 parallel threads
        finish all 20 states in ~1 second total."""
        states = [s for s in ANIMS if s not in self.bank.alias and not self.bank.frames.get(s)]
        if not states:
            return
        # Prioritize common interaction states first
        priority = ['idle', 'walk', 'run', 'bark', 'sit', 'sleep', 'eat', 'lick',
                    'happy', 'pet', 'stretch', 'dance', 'beg', 'bath',
                    'play_dead', 'surprised', 'kiss', 'wave', 'type', 'roll']
        ordered = [s for s in priority if s in states] + [s for s in states if s not in priority]
        self._preload_queue = ordered
        self._preload_parallel = 3
        # Launch initial batch
        for _ in range(min(self._preload_parallel, len(self._preload_queue))):
            self._preload_launch_next()

    def _preload_launch_next(self):
        """Launch one background thread for next state in queue."""
        if not getattr(self, '_preload_queue', None):
            return
        state = self._preload_queue.pop(0)
        owner = self.bank.alias.get(state, state)
        if not (self.bank.frames.get(owner) or owner in self.bank._lazy_threads):
            t = _StateLoadThread(self.bank, owner)
            self.bank._lazy_threads[owner] = t
            t.finished.connect(lambda s=owner, th=t: self._on_preload_done(s, th))
            t.start()

    def _on_preload_done(self, state, t):
        """Preload thread finished: write frames + launch next in queue."""
        self.bank._lazy_threads.pop(state, None)
        if t.imgs is not None:
            bank = self.bank
            while getattr(bank, '_replaced_by', None) is not None:
                bank = bank._replaced_by
            bank.frames[state] = t.imgs
            bank.frames_m[state] = [None] * len(t.imgs)
            bank.lift_map[state] = t.lift
            bank._loaded_order = getattr(bank, '_loaded_order', [])
            if state not in bank._loaded_order:
                bank._loaded_order.append(state)
            # Notify window if this is current state
            if hasattr(self, 'state') and self.bank.alias.get(self.state, self.state) == state:
                self._on_state_reloaded(state)
            self.update()
        t.deleteLater()
        # Launch next in queue
        if getattr(self, '_preload_queue', None):
            self._preload_launch_next()

    def _on_state_reloaded(self, state):
        """v99b: After background load completes, reset animation phase so it starts from frame 0."""
        owner = self.bank.alias.get(state, state)
        if self.bank.alias.get(self.state, self.state) == owner:
            self.frame_idx = 0
            self.anim_elapsed = 0.0
        self.update()

    #  --  --  --  --  -- ─ State switching  --  --  --  --  -- ─
    def set_state(self, s, duration=None):
        if s not in ANIMS:
            return
        self.bank.ensure_state(s)   # v99b: Pure async — background thread loads, get() returns empty during load
        # No sync loading on main thread — eliminates first-trigger freeze
        prev = self.state
        # Same-state re-entry (AI continue walk): keep gait frame continuity, don't reset animation phase  -- 
        # otherwise every AI re-decision hard-cuts frame_idx to 0, causing periodic gait stutter
        same_move = (s == prev and s in ('walk', 'run', 'potty_run'))
        self.state = s
        self.state_started = time.perf_counter()
        if not same_move:
            self.anim_elapsed = 0.0
            self.frame_idx = 0
        self.roll_angle = 0.0
        self.pop_t = 0.0 if same_move else 0.16
        # v106-fix: 切到任何非移动状态时立即清零水平速度，彻底消灭窗口滑行
        if s not in ('walk', 'run', 'potty_run'):
            self.vel_x = 0.0
            self.move_acc = 0.0
        # Start antic: crouch before running to build momentum
        # v96-fix: Reduced from 0.18 to 0.05 - old 0.18s caused "stands still for a few frames before walking"
        if s in ('walk', 'run', 'potty_run') and prev not in ('walk', 'run', 'potty_run'):
            self.antic_t = 0.05
        # Stop settle: forward lean squash on hard stop
        if prev in ('walk', 'run', 'potty_run') and s not in ('walk', 'run', 'potty_run'):
            self.settle_t = 0.28
        if duration:
            self.state_duration[s] = duration
        if s == 'bark':
            self.particles.emit(ParticleSystem.BUBBLE, CANVAS / 2, 60, 1, text=BARK_TEXT)
        elif s == 'happy':
            self.particles.emit(ParticleSystem.HEART, CANVAS / 2, 90, 4)
        elif s == 'eat':
            self.say(EAT_TEXT)
        # v66: LRU touch (current lazy state moved to queue tail) + excess lazy state unload to reclaim memory
        owner = self.bank.alias.get(s, s)
        if owner in self.bank.LAZY:
            order = getattr(self.bank, '_loaded_order', [])
            if owner in order:
                order.remove(owner)
                order.append(owner)
        self.bank.unload_idle_lazy(owner)

    def state_time(self):
        return time.perf_counter() - self.state_started

    def say(self, text):
        self.particles.emit(ParticleSystem.BUBBLE, CANVAS / 2, 55, 1, text=text)

    #  --  --  --  --  -- ─ Motion/easing helpers  --  --  --  --  -- ─
    def _integrate_vel(self, dt, target, accel, decel):
        """Velocity-eased approach to target, subpixel integral moves window (eliminates jitter and foot sliding)"""
        rate = accel if abs(target) > 0.5 else decel
        self.vel_x = _approach(self.vel_x, target, rate, dt)
        self.move_acc += self.vel_x * dt
        step = int(self.move_acc)
        if step:
            self.move_acc -= step
            nx = self.x() + step
            # v10 out-of-bounds fix: all movement clamped within screen.
            # old tease mode chased mouse without bounds -> dog ran off screen, head/tail clipped by screen edge.
            sg = QApplication.primaryScreen().geometry()
            lo, hi = sg.left(), sg.right() - self.width()
            if nx < lo:
                nx = lo; self.vel_x = max(0.0, self.vel_x); self.move_acc = 0.0
            elif nx > hi:
                nx = hi; self.vel_x = min(0.0, self.vel_x); self.move_acc = 0.0
            self.move(nx, self.y())

    def _start_turn(self, new_facing):
        """Start turn animation (decelerate -> turn -> re-accelerate, not instant flip)"""
        if self.turn_phase is not None or new_facing == self.facing:
            return
        self.turn_phase = 0.0
        self.turn_new_facing = new_facing

    def _update_turn(self, dt):
        if self.turn_phase is None:
            return
        self.turn_phase += dt / 0.22  # v19: 0.45->0.22 competitor-style fast turn (pure mirror flip must be fast to look natural, slow+no compression looks stiff)
        if self.turn_phase >= 0.5 and not self.turn_flipped:
            self.turn_flipped = True
            self.facing = self.turn_new_facing
            self.flipped = self.facing < 0
        if self.turn_phase >= 1.0:
            self.turn_phase = None
            self.turn_flipped = False

    def turn_scale(self):
        """v19 deprecated: always returns 1.0.
        History: v11 used X-axis compression (max 0.35) to simulate turn, user twice criticized as "card flip".
        Now changed to competitor-style pure mirror flip  --  _update_turn switches flipped at phase=0.5,
        no X-axis scaling at all, with 0.22s fast turn, looks like dog turning crisply"""
        return 1.0

    def _update_micro(self, dt):
        """Idle micro-action: occasional head tilt/shake/small jump, avoids wooden standing"""
        if self.state in ('idle', 'sit') and not self.dragging:
            if self.micro is None:
                if random.random() < dt / 6.5:
                    self.micro = {'type': random.choice(['tilt', 'shake', 'hop']), 't': 0.0}
            else:
                self.micro['t'] += dt
                dur = {'tilt': 0.7, 'shake': 0.5, 'hop': 0.45}[self.micro['type']]
                if self.micro['t'] >= dur:
                    self.micro = None
        else:
            self.micro = None

    #  --  --  --  --  -- ─ Main loop  --  --  --  --  -- ─
    def game_loop(self):
        now = time.perf_counter()
        raw_dt = now - self.last_t
        dt = min(raw_dt, 0.05)
        # v107-fix: 启动卡顿时原始dt>>0.05，AI用wall clock的state_time()已经>duration
        # 导致连续快速切状态→窗口位移堆叠→视觉滑行。根治：原始dt>0.1时只重置时钟，跳过AI/物理
        self.last_t = now
        skip_ai_physics = raw_dt > 0.1
        if skip_ai_physics:
            # 重置状态开始时间，防止wall clock累积导致误触发duration到期
            self.state_started = now

        # Frame advance (gait frames synced with actual speed, prevents foot sliding: slower speed = slower gait frames)
        st_for_frame = self.state
        if st_for_frame in ('walk', 'run', 'potty_run'):
            cruise = 150.0 if st_for_frame != 'walk' else 65.0
            # Floor 0.45: animation doesn't freeze during turn deceleration (old 0.12 caused 0.3s frozen feel)
            frame_speed = max(0.45, min(1.0, abs(self.vel_x) / cruise))
        else:
            frame_speed = 1.0
        self.anim_elapsed += dt * 1000 * frame_speed
        prefix, count, frame_ms, loop, intro = ANIMS[self.state]
        raw_idx = int(self.anim_elapsed / frame_ms)
        if intro > 0 and loop:
            # Intro segment plays once, then loops main body
            if raw_idx < intro:
                self.frame_idx = raw_idx
            else:
                body_len = count - intro
                body_idx = raw_idx - intro
                # P2-fix: bath uses simple loop instead of ping-pong — ping-pong reversal
                # caused visible flicker on foam/shake frames at the reversal point
                self.frame_idx = intro + (body_idx % body_len)
        else:
            self.frame_idx = raw_idx % count if loop else min(raw_idx, count - 1)

        # Leg rig: gait phase continuous accumulation, frequency proportional to actual speed (prevents foot sliding)
        # Note: walk/run frames have built-in complete gait animation, no leg_phase needed
        # leg_phase only for non-gait frames needing leg swing
        if self.state in ('walk', 'run', 'potty_run'):
            # Frames have built-in gait, disable leg_phase to avoid double gait
            self.leg_amp = max(0.0, self.leg_amp - dt * 12.0)   # Quick stop leg rig
            if self.leg_amp < 0.01:
                self.leg_phase = 0.0
        else:
            self.leg_amp = max(0.0, self.leg_amp - dt * 8.0)   # Stop ease-out

        # Motion/transition timers
        self.pop_t = max(0.0, self.pop_t - dt)
        self.antic_t = max(0.0, self.antic_t - dt)
        self.settle_t = max(0.0, self.settle_t - dt)
        self._update_turn(dt)
        self._update_micro(dt)

        # v107: vel_x always zeroed on state switch to non-moving state,
        # only physics throw can set non-zero vel_x during surprised state
        if (self.state not in ('walk', 'run', 'potty_run')
                and not self.physics.active and not self.dragging):
            self.vel_x = 0.0
            self.move_acc = 0.0
        # Occasional leg kick twitch during sleep
        if self.state == 'sleep':
            self.sleep_twitch_next -= dt
            if self.sleep_twitch_next <= 0:
                self.sleep_twitch_t = 1.0
                self.sleep_twitch_next = random.uniform(5, 10)
            self.sleep_twitch_t = max(0.0, self.sleep_twitch_t - dt * 2.5)
        # Airborne height smoothing (EMA ~90ms): run etc per-frame bottom jitter no longer directly drives shadow size
        lift_seq = self.bank.lift_map.get(
            self.bank.alias.get(self.state, self.state))
        if lift_seq:
            raw_air = lift_seq[self.frame_idx % len(lift_seq)]
        else:
            raw_air = 0.0
        self.smooth_air += (raw_air - self.smooth_air) * min(1.0, dt / 0.09)
        # v107-fix: 卡顿时跳过AI/物理，防止wall clock累积导致连续快速切状态→滑行
        if not skip_ai_physics:
            self.update_ai(dt)
            impact = self.physics.update(dt, self, self.floor_y, 0,
                                          QApplication.primaryScreen().geometry().right() - self.width())
            if impact > 200:
                self.particles.emit(ParticleSystem.DUST, CANVAS / 2, CANVAS - GROUND_PAD, 4)

        self.particles.update(dt)
        self.update_stats(dt)
        self.emit_state_particles(dt)
        #  --  v66 adaptive tick: static states reduce frame rate to save CPU, action/transition/particle active stays 16ms  -- 
        # Source animations are 24fps native (frame_ms~=42-114), 16ms tick redraws over half are wasted frames.
        # Static period tick = source frame rate (source animation ~20fps, higher = redrawing same frame wastes CPU);
        # action/transition/particle/physics/drag active period = 16ms, ensures action quality no frame drops.
        moving = self.state in ('walk', 'run', 'potty_run') and abs(self.vel_x) > 2
        active = (self.pop_t > 0 or self.antic_t > 0 or self.settle_t > 0
                  or self.turn_phase is not None or self.micro is not None
                  or self.dragging or self.physics.active
                  or self.sleep_twitch_t > 0 or self.particles.particles
                  or self.leg_amp > 0.01)
        frame_ms = ANIMS[self.state][2]
        tgt = 16 if (active or moving) else max(16, min(66, frame_ms))
        if tgt != self._tick_cur:
            self._tick_cur = tgt
            self.timer.setInterval(tgt)
        # v66: static and frame unchanged -> skip redraw (transparent window no change = zero draw CPU)
        if (active or moving
                or getattr(self, '_last_drawn', None) != (self.state, self.frame_idx, self.flipped)):
            self.update()

    #  --  --  --  --  -- ─ Behavior AI  --  --  --  --  -- ─
    def update_ai(self, dt):
        st = self.state
        st_time = self.state_time()
        sg = QApplication.primaryScreen().geometry()

        # Timed states end — always return to idle (user-triggered actions should not
        # invoke AI random behavior after completion, which causes inconsistent returns)
        if st in self.state_duration and st_time > self.state_duration[st]:
            del self.state_duration[st]
            self.set_state('idle')
            return

        if self.dragging:
            return

        #  --  teaseModes: chase mouse(easedvelocity+turnanimation) -- 
        if self.mode == 'tease':
            cursor = QCursor.pos()
            cx = self.x() + self.width() // 2
            dx = cursor.x() - cx
            if abs(dx) > 46:
                if st not in ('run', 'walk'):
                    self.set_state('run')
                new_facing = 1 if dx > 0 else -1
                if new_facing != self.facing:
                    self._start_turn(new_facing)
                if self.turn_phase is None:
                    # Decelerate when approaching cursor, faster when farther away
                    target = new_facing * min(165.0, 35.0 + abs(dx) * 0.75)
                    self._integrate_vel(dt, target, 900.0, 1400.0)
            else:
                self._integrate_vel(dt, 0.0, 0.0, 2400.0)
                if st == 'run':
                    self.set_state('idle')
            # Show hearts when close to mouse
            dist = math.hypot(cursor.x() - cx, cursor.y() - (self.y() + self.height() // 2))
            if dist < 150 and random.random() < dt * 2.5:
                self.particles.emit(ParticleSystem.HEART, CANVAS / 2, 80, 1)
            return

        #  --  In physical motion  -- 
        if self.physics.active:
            if st != 'surprised':
                self.set_state('surprised')
            return
        # P8-fix: surprised state should play for its duration, not immediately return to idle
        # Old code: if st == 'surprised': self.set_state('idle') — this made surprised button useless
        # Now: surprised plays until state_duration expires (set in contextMenuEvent)
        if st == 'surprised' and st not in self.state_duration and st_time > 2.0:
            self.set_state('idle')
            return

        #  --  Potty  -- 
        if self.potty_need >= 100 and st not in ('potty_run', 'potty'):
            self.set_state('potty_run')
            edge = random.choice([30, sg.right() - self.width() - 30])
            self.roam_target = edge
            self.say('Gotta go...')
            return

        if st == 'potty_run':
            tx = self.roam_target
            if tx is None:
                # Defensive: no target point, pick nearest screen edge to avoid None crash
                tx = self.roam_target = random.choice([30, sg.right() - self.width() - 30])
            if abs(self.x() - tx) < 28:
                self.state_duration.pop('sit', None)
                self.set_state('potty')
                self.potty_need = 0.0
            else:
                new_facing = 1 if tx > self.x() else -1
                if new_facing != self.facing:
                    self._start_turn(new_facing)
                if self.turn_phase is None:
                    self._integrate_vel(dt, new_facing * 150.0, 800.0, 1000.0)
            return

        if st == 'potty':
            if st_time > 3.0:
                self.set_state('idle')
                self.particles.emit(ParticleSystem.SPARKLE, CANVAS / 2, 100, 5)
                self.say('Much better!')
            return

        #  --  Sleep  -- 
        if st == 'sleep':
            if (st_time > 10 and self.energy >= 95) or st_time > 40:
                self.set_state('idle')
                self.say('Good morning!')
            return

        if self.energy < 15 and st == 'idle' and random.random() < dt * 0.5:
            self.set_state('sleep')
            self.say('Getting sleepy...')
            return

        #  --  Auto behavior timer  -- 
        self.ai_timer -= dt
        if self.ai_timer > 0:
            # Walk state continuous movement (velocity px/s, eased)
            if st == 'walk':
                self._do_walk(65.0, dt)
            elif st == 'run':
                self._do_walk(145.0, dt)
            return

        self.ai_timer = random.uniform(4, 11)

        # v10 action interruption fix: timed actions (dance/roll/lick/beg/bath/happy etc) during playback
        #      AI not allowed to switch actions  --  old ai_timer (4-11s) could be shorter than performance duration (dance 7.26s),
        #      performance cut mid-way by AI, looks = action interrupted half-way.
        #      after expiry, "timed state ended" branch above uniformly returns to idle, then normal decision.
        if st in self.state_duration:
            return

        # Choose next behavior
        r = random.random()
        if self.mode == 'taskbar':
            if r < 0.42:
                self.set_state('walk')
                sg2 = QApplication.primaryScreen().geometry()
                # When against wall, force walk toward open side
                if self.x() < 120:
                    self.walk_dir = 1
                elif self.x() > sg2.right() - self.width() - 120:
                    self.walk_dir = -1
                else:
                    self.walk_dir = random.choice([-1, 1])
                self._start_turn(self.walk_dir)
                if self.turn_phase is None:
                    self.facing = self.walk_dir
                    self.flipped = self.facing < 0
            elif r < 0.55:
                self.set_state('happy', duration=5.08)
            elif r < 0.66:
                self.set_state('bark', duration=5.08)
            elif r < 0.76:
                self.set_state('lick', duration=5.08)
            elif r < 0.84:
                self.set_state('roll', duration=10.16)
            else:
                self.set_state('idle')
        else:  # desktop  --  drag-drop fixed: after drag, fixed at current position, does various actions in place, no auto-walking
            if r < 0.30:
                self.set_state('idle')
            elif r < 0.45:
                self.set_state('happy', duration=5.08)
            elif r < 0.58:
                self.set_state('lick', duration=5.08)
            elif r < 0.70:
                self.set_state('roll', duration=10.16)
            elif r < 0.80:
                self.set_state('bark', duration=5.08)
            elif r < 0.90:
                self.set_state('dance', duration=10.16)
            else:
                self.set_state('sit', duration=5.08)

    def _do_walk(self, speed, dt):
        sg = QApplication.primaryScreen().geometry()
        if self.mode == 'desktop':
            # desktop mode = drag-drop fixed: only walks when there is a roam_target (e.g. potty),
            # otherwise stops in place, no auto-walking
            if self.roam_target is not None:
                tx = self.roam_target
                dist = tx - self.x()
                if abs(dist) < 26:
                    self.roam_target = None
                    self.set_state('idle')
                    return
                new_facing = 1 if dist > 0 else -1
                if new_facing != self.facing:
                    self._start_turn(new_facing)
                if self.turn_phase is not None:
                    self._integrate_vel(dt, 0.0, 0.0, 2600.0)
                    return
                cruise = speed
                near_speed = min(cruise, max(22.0, abs(dist) * 1.0))
                self._integrate_vel(dt, new_facing * near_speed, 380.0, 700.0)
            else:
                # desktop mode no target: stop walking, switch to idle
                self._integrate_vel(dt, 0.0, 0.0, 2600.0)
                if abs(self.vel_x) < 5:
                    self.set_state('idle')
        else:
            # Taskbar roaming: bounce at boundaries (with turn animation)
            if self.turn_phase is not None:
                self._integrate_vel(dt, 0.0, 0.0, 2600.0)
            else:
                self._integrate_vel(dt, self.walk_dir * speed, 380.0, 700.0)
            x = self.x()
            if x <= 0 and self.walk_dir < 0:
                self.walk_dir = 1
                self._start_turn(1)
                self.ai_timer = 0.0   # Re-decide immediately after hitting wall, avoid standing stuck
            elif x >= sg.right() - self.width() and self.walk_dir > 0:
                self.walk_dir = -1
                self._start_turn(-1)
                self.ai_timer = 0.0
            x = max(0, min(self.x(), sg.right() - self.width()))
            if x != self.x():
                self.move(x, self.y())

    #  --  --  --  --  -- ─ Properties  --  --  --  --  -- ─
    def update_stats(self, dt):
        self.fullness = max(0, self.fullness - dt * 0.06)
        self.happiness = max(0, self.happiness - dt * 0.04)
        self.potty_need = min(100, self.potty_need + dt * 0.12)
        if self.state == 'sleep':
            self.energy = min(100, self.energy + dt * 3.5)
        elif self.state in ('run', 'dance', 'roll'):
            self.energy = max(0, self.energy - dt * 1.2)
        else:
            self.energy = min(100, self.energy + dt * 0.15)

    def emit_state_particles(self, dt):
        st = self.state
        if st == 'sleep' and random.random() < dt * 0.8:
            self.particles.emit(ParticleSystem.ZZZ, CANVAS / 2 + 45, 120, 1)
        elif st == 'potty' and random.random() < dt * 2.5:
            self.particles.emit(ParticleSystem.STINK, CANVAS / 2 + 30, CANVAS - 60, 1)
        elif st == 'eat' and random.random() < dt * 4:
            self.particles.emit(ParticleSystem.CRUMB, CANVAS / 2 + 35, CANVAS - 70, 1)
        elif st == 'bath' and random.random() < dt * 3:
            self.particles.emit(ParticleSystem.SPARKLE, CANVAS / 2, 100, 1)

    # ---------- Drawing (core: hybrid rendering) ----------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        # v25 (P9): unified zoom -- all drawing logic keeps CANVAS=320 logical coordinate system,
        # one scale makes sprite (pre-rendered at zoom)/particles/bubble sync-scale
        painter.scale(self.zoom, self.zoom)

        now = time.perf_counter()
        t = now - self.state_started
        dx = CANVAS / 2
        dy = CANVAS - GROUND_PAD  # Foot anchor point

        #  --  Calculate real-time transforms  -- 
        bob = 0.0          # Vertical bob
        rot = 0.0          # Rotation (degrees)
        sx, sy = 1.0, 1.0  # Scale
        st = self.state
        speed_ratio = 1.0  # Speed ratio to cruise speed (adjusts stride amplitude)

        if st == 'idle' or st == 'sit':
            # v7: 3D idle animation has built-in breathing, programmatic bob removed (avoids "floating GIF feel")
            pass
        elif st == 'sleep':
            # v7.1: Lying frames have built-in breathing, no more programmatic bob (avoids floating feel); retains leg kick twitch accent
            if self.sleep_twitch_t > 0:
                tw = self.sleep_twitch_t
                rot += math.sin(tw * 22) * 1.5 * tw
        elif st in ('walk', 'run', 'potty_run'):
            # v7: 3D gait animation has built-in bounce and real leg swing, programmatic only keeps velocity forward lean
            rot = max(-3.5, min(3.5, self.vel_x * 0.011))
        elif st == 'happy':
            # v7: Jump_ToIdle animation has built-in full jump arc (liftoff->landing), no more programmatic jump overlay
            pass
        elif st == 'roll':
            # v7.1: True 3D roll baked into frames (Body rotates 360 degrees around front-back axis), no more programmatic whole-image rotation
            bob = -3
        elif st == 'dance':
            # v7.1: dance real animation (hind legs upright + front paw wave) baked into frames, no more programmatic rotation/bob overlay
            pass
        elif st == 'eat':
            # v7: Eating animation has built-in full head-down eating motion, no more programmatic wobble overlay
            pass
        elif st == 'bark':
            # v7: Attack animation has built-in lunge-bite motion, no more recoil overlay
            pass
        elif st in ('bath', 'surprised', 'stretch', 'beg', 'lick', 'sit', 'sleep'):
            # v7.1: true 3D animations (shake/startle/stretch/beg/lick/sit/sleep) baked into frames
            pass

        #  --  Start antic (crouch to build momentum) -- 
        if self.antic_t > 0:
            p = self.antic_t / 0.18
            sy *= 1.0 - 0.10 * p
            sx *= 1.0 + 0.07 * p
            rot -= self.facing * 3.0 * p
            bob += 2.0 * p

        #  --  Hard stop settle (forward lean squash) -- 
        if self.settle_t > 0:
            p = self.settle_t / 0.28
            rot += self.facing * 4.5 * p
            sy *= 1.0 - 0.05 * p

        # -- state entry spring (slight overshoot) --
        if self.pop_t > 0:
            p = self.pop_t / 0.16
            o = math.sin(p * math.pi) * 0.03  # v19: 0.07->0.03 reduce entry spring overshoot, prevents jump frame head pushed near window top (P1)
            sx *= 1.0 + o * 0.6
            sy *= 1.0 + o

        #  --  v19: Turn X-axis compression completely removed  --  changed to competitor (Deskpet Dog) style pure mirror flip.
        # User twice criticized X-axis squash as "card flip"; turn_scale() deprecated (always returns 1.0)  -- 

        #  --  Idle micro-actions  -- 
        if self.micro:
            mt = self.micro['t']
            mtype = self.micro['type']
            if mtype == 'tilt':
                rot += math.sin(mt / 0.7 * math.pi) * 5.0 * self.facing
            elif mtype == 'shake':
                rot += math.sin(mt * 38) * 2.6
            elif mtype == 'hop':
                hp = mt / 0.45
                bob -= math.sin(hp * math.pi) * 9
                if hp < 0.2:
                    sy *= 1.0 - (0.2 - hp) * 0.4
                elif hp > 0.85:
                    sy *= 1.0 - (hp - 0.85) * 0.6
                    sx *= 1.0 + (hp - 0.85) * 0.5

        #  --  Landing squash (physics) -- 
        if self.physics.squash > 0:
            sq = self.physics.squash
            sx *= 1.0 + sq * 0.18
            sy *= 1.0 - sq * 0.22

        # -- drag tilt --
        if self.dragging and len(self.mouse_hist) >= 2:
            (t0, x0, _), (t1, x1, _) = self.mouse_hist[0], self.mouse_hist[-1]
            if t1 > t0:
                vx = (x1 - x0) / (t1 - t0)
                rot += max(-8, min(8, vx * 0.012))  # Within +/-8 degrees doesn't exceed window margin, avoids rotation clipping

        #  --  Image fetch (v25 P2: dynamic shadow removed  --  user explicitly requested no bottom shadows) -- 
        img = self.bank.get(self.state, self.frame_idx, self.flipped)
        if img.isNull():
            # v99b: New state not loaded yet — keep showing last valid frame (no black flash)
            img = self._last_frame if hasattr(self, '_last_frame') and not self._last_frame.isNull() else QImage()
            if img.isNull():
                painter.end()
                return
        else:
            self._last_frame = img

        # -- apply transforms and draw --
        painter.save()
        painter.translate(dx, dy + bob)
        if rot:
            painter.rotate(rot)
        painter.scale(sx, sy)

        # v64: bottom-anchored proportional drawing -- tight assets drawn proportionally by frame w/h (canvas height = union height,
        # no in-frame pulsation; calm six-state baseline unified, no jump on state switch).
        # P4/P5-fix: k maps texture pixels to DRAW_SIZE logical coordinates.
        # Since _build_state scales by height (sc = draw / h), texture height == draw,
        # so k = DRAW_SIZE / draw maps correctly.
        _owner = self.bank.alias.get(self.state, self.state)
        _draw = self.bank._state_draw(_owner) if _owner in self.bank.TIGHT else max(96, min(self.bank.draw_size, 1024))
        k = DRAW_SIZE / _draw
        _iw, _ih = img.width(), img.height()
        draw_rect = QRectF(-_iw * k / 2, -_ih * k + GROUND_PAD, _iw * k, _ih * k)
        #  --  Leg rig rendering (Paper-Doll Rig): real walking swing  -- 
        # v19: Source legs frozen, runtime splits sprite into rear-leg -> body -> front-leg three layers,
        # pendulum swing around hip joint produces real gait. rig is per-frame list (follows frame_idx).
        rig_list = (self.bank.rig_parts_m if self.flipped
                    else self.bank.rig_parts).get(st)
        rig = rig_list[self.frame_idx % len(rig_list)] if rig_list else None
        if rig is not None and self.leg_amp > 0.01:
            top_y = -DRAW_SIZE + GROUND_PAD
            amp = rig['amp_deg'] * self.leg_amp
            swing_f = math.sin(self.leg_phase) * amp   # front leg
            swing_r = -swing_f                          # rear leg opposite phase (trot gait)
            # 1) Rear leg (drawn first, behind body)
            rp, (rpx, rpy) = rig['rear'], rig['rear_pivot']
            painter.save()
            painter.translate(rig['rear_x0'] - DRAW_SIZE / 2 + rpx,
                              top_y + rig['leg_y0'] + rpy)
            painter.rotate(swing_r)
            painter.drawImage(QRectF(-rpx, -rpy, rp.width(), rp.height()), rp)
            painter.restore()
            # 2) Body (covers hip seam)
            body = rig['body']
            painter.drawImage(QRectF(-DRAW_SIZE / 2, top_y,
                                     DRAW_SIZE, body.height()), body)
            # 3) front leg (drawn last, in front of body)
            fp, (fpx, fpy) = rig['front'], rig['front_pivot']
            painter.save()
            painter.translate(rig['front_x0'] - DRAW_SIZE / 2 + fpx,
                              top_y + rig['leg_y0'] + fpy)
            painter.rotate(swing_f)
            painter.drawImage(QRectF(-fpx, -fpy, fp.width(), fp.height()), fp)
            painter.restore()
        else:
            painter.drawImage(draw_rect, img)

        #  --  Breathing layer overlay: v7 disabled  -- 
        # 3D skeletal animation has real chest rise/fall, old 2D asset chest coordinates misalign with 3D model,
        # overlay would cause texture tearing. Comment retained to explain removal reason.

        painter.restore()

        #  --  Particles  -- 
        self.particles.draw(painter)
        self._last_drawn = (self.state, self.frame_idx, self.flipped)  # v66 skip-draw marker
        painter.end()

    #  --  --  --  --  -- ─ Interaction  --  --  --  --  -- ─
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_off = event.globalPos() - self.pos()
            self.mouse_hist = [(time.perf_counter(), event.globalPos().x(), event.globalPos().y())]
            self.physics.active = False
            if self.mode == 'tease':
                self.mode = 'taskbar'
                sg = QApplication.primaryScreen().geometry()
                self.floor_y = sg.bottom() - self.height() - 45
                self.set_state('idle')
                self.say('Got me!')
            else:
                self.set_state('surprised')

    def mouseMoveEvent(self, event):
        if self.dragging:
            now = time.perf_counter()
            gp = event.globalPos()
            self.mouse_hist.append((now, gp.x(), gp.y()))
            self.mouse_hist = [h for h in self.mouse_hist if now - h[0] < 0.12]
            # drag clamped within screen: old code could drag off screen -> head/tail clipped by screen edge
            sg = QApplication.primaryScreen().geometry()
            nx = max(0, min(gp.x() - self.drag_off.x(), sg.right() - self.width()))
            ny = max(0, min(gp.y() - self.drag_off.y(), sg.bottom() - self.height()))
            self.move(nx, ny)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.dragging:
            self.dragging = False
            # desktop drag-drop fixed mode: fixed at current position after drop, no throw physics
            if self.mode == 'desktop':
                self.set_state('idle')
                self.happiness = min(100, self.happiness + 3)
                self.particles.emit(ParticleSystem.HEART, CANVAS / 2, 90, 2)
                return
            # Calculate throw velocity
            if len(self.mouse_hist) >= 2:
                (t0, x0, y0), (t1, x1, y1) = self.mouse_hist[0], self.mouse_hist[-1]
                dt = t1 - t0
                if dt > 0.012:
                    vx = (x1 - x0) / dt
                    vy = (y1 - y0) / dt
                    if abs(vx) > 120 or vy < -120:
                        self.physics.throw(vx, vy)
                        self.set_state('surprised')
                    else:
                        self.set_state('idle')
                        self.happiness = min(100, self.happiness + 3)
                        self.particles.emit(ParticleSystem.HEART, CANVAS / 2, 90, 2)
                else:
                    self.set_state('idle')
            else:
                self.set_state('idle')

    def mouseDoubleClickEvent(self, event):
        trick = random.choice(['happy', 'roll', 'dance', 'bark'])
        # Each trick duration aligned to integer multiple of loop period (happy is one-shot), avoids hard cut mid-action
        # P3-fix: durations match actual frame counts to prevent premature cut
        self.set_state(trick, duration={'happy': 5.08, 'roll': 10.16,
                                        'dance': 10.16, 'bark': 5.08}[trick])
        self.happiness = min(100, self.happiness + 6)

    def contextMenuEvent(self, event):
        # v67: Self-drawn rounded menu  --  macOS QMenu+border-radius renders white outside rounded corners,
        # QPainterPath self-drawn popup same mechanism as main window, Windows/macOS pixel-identical.
        menu = RoundedMenu(self)

        tease_key = 'tease'
        menu.add_item(tease_key, '🐾 Stop Teasing' if self.mode == 'tease' else '🐾 Tease Me')
        menu.add_sep()
        menu.add_item('feed', '🍖 Feed')
        menu.add_item('pet', '🤚 Pet Me')
        menu.add_sep()
        trick_menu = RoundedMenu(self)
        trick_menu.add_item('happy', 'Happy Jump')
        trick_menu.add_item('roll', 'Roll Over')
        trick_menu.add_item('dance', 'Dance')
        trick_menu.add_item('bark', 'Bark')
        trick_menu.add_item('lick', 'Lick Fur')
        trick_menu.add_item('beg', 'Beg')
        trick_menu.add_item('bath', 'Bath')
        trick_menu.add_item('wave', 'Wave')
        trick_menu.add_item('stretch', 'Stretch')
        trick_menu.add_item('surprised', 'Surprised')
        trick_menu.add_item('kiss', 'Kiss')
        trick_menu.add_item('type', 'Type')
        trick_menu.add_item('play_dead', 'Play Dead')
        trick_menu.add_item('walk', 'Walk')
        menu.add_sub('🎪 Tricks', trick_menu)
        menu.add_sep()
        size_menu = RoundedMenu(self)
        size_menu.add_item('zoom_up', '➕ Bigger')
        size_menu.add_item('zoom_down', '➖ Smaller')
        size_menu.add_item('zoom_reset', '↩ Reset')
        menu.add_sub('🔍 Size', size_menu)
        menu.add_sep()
        mode_menu = RoundedMenu(self)
        mode_menu.add_item('mode_taskbar', 'Taskbar Roam')
        mode_menu.add_item('mode_desktop', 'Desktop Fixed')
        menu.add_sub('📍 Mode', mode_menu)
        menu.add_sep()
        menu.add_item('sleep', '💤 Sleep')
        menu.add_item('stats', '📊 Stats')
        menu.add_sep()
        menu.add_item('quit', '❌ Quit')

        action = menu.exec_menu(event.globalPos())
        if action is None:
            return

        if action == 'tease':
            if self.mode == 'tease':
                self.mode = 'taskbar'
                sg = QApplication.primaryScreen().geometry()
                self.floor_y = sg.bottom() - self.height() - 45
                self.set_state('idle')
            else:
                self.mode = 'tease'
                self.set_state('run')
                self.say('Catch me!')
        elif action == 'feed':
            self.set_state('eat', duration=5.08)
            self.fullness = min(100, self.fullness + 20)
            self.happiness = min(100, self.happiness + 5)
        elif action == 'pet':
            self.happiness = min(100, self.happiness + 10)
            self.set_state('pet', duration=5.08)
        elif action == 'happy':
            self.set_state('happy', duration=5.08)
        elif action == 'roll':
            self.set_state('roll', duration=10.16)
        elif action == 'dance':
            self.set_state('dance', duration=10.16)
        elif action == 'bark':
            self.set_state('bark', duration=5.08)
        elif action == 'lick':
            self.set_state('lick', duration=5.08)
        elif action == 'beg':
            self.set_state('beg', duration=5.08)
        elif action == 'bath':
            self.set_state('bath', duration=10.16)
        elif action == 'wave':
            self.set_state('wave', duration=5.08)
        elif action == 'stretch':
            self.set_state('stretch', duration=5.08)
        elif action == 'surprised':
            self.set_state('surprised', duration=5.08)
        elif action == 'kiss':
            self.set_state('kiss', duration=5.08)
        elif action == 'type':
            self.set_state('type', duration=5.08)
        elif action == 'play_dead':
            self.set_state('play_dead', duration=5.08)
        elif action == 'walk':
            # Perform walk: set direction and duration, make the dog walk
            self.walk_dir = random.choice([-1, 1])
            self._start_turn(self.walk_dir)
            if self.turn_phase is None:
                self.facing = self.walk_dir
                self.flipped = self.facing < 0
            self.set_state('walk')
            self.ai_timer = random.uniform(6, 12)  # walk 6-12 seconds
        elif action == 'mode_taskbar':
            self.mode = 'taskbar'
            sg = QApplication.primaryScreen().geometry()
            self.floor_y = sg.bottom() - self.height() - 45
            self.move(self.x(), self.floor_y)
            self.set_state('idle')
        elif action == 'mode_desktop':
            self.mode = 'desktop'
            self.roam_target = None  # No auto-walking, wait for user drag
            self.set_state('idle')
            self.say('Drag me anywhere!')
        elif action == 'zoom_up':
            self.set_zoom(self.zoom + ZOOM_STEP)
            self.say(f'Size {self.zoom:.2f}x')
        elif action == 'zoom_down':
            self.set_zoom(self.zoom - ZOOM_STEP)
            self.say(f'Size {self.zoom:.2f}x')
        elif action == 'zoom_reset':
            self.set_zoom(ZOOM_DEFAULT)
            self.say('Reset to default size')
        elif action == 'sleep':
            self.set_state('sleep')
        elif action == 'stats':
            self.say(f'Full{int(self.fullness)} Happy{int(self.happiness)} '
                      f' Energy{int(self.energy)}')
            self.particles.emit(ParticleSystem.SPARKLE, CANVAS / 2, 70, 4)
        elif action == 'quit':
            QApplication.quit()


def _install_excepthook():
    """After packaging (console=False) no stderr, exceptions must write to log or die silently"""
    import traceback

    def hook(exc_type, exc_value, exc_tb):
        text = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            if getattr(sys, 'frozen', False):
                log = os.path.join(os.path.dirname(sys.executable), 'crash.log')
            else:
                log = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'crash.log')
            with open(log, 'a', encoding='utf-8') as f:
                f.write(time.strftime('%Y-%m-%d %H:%M:%S\n') + text + '\n')
        except Exception:
            pass
        if sys.stderr is not None:
            sys.stderr.write(text)

    sys.excepthook = hook


_pet_window = None  # Must hold reference globally, prevent window GC destruction
_singleton_mutex = None  # Must hold globally, prevent mutex GC early release


def _acquire_single_instance():
    """Windows named mutex: prevents multiple pet instances/zombie processes from double-clicking"""
    if sys.platform != 'win32':
        return True
    import ctypes
    kernel32 = ctypes.windll.kernel32
    global _singleton_mutex
    _singleton_mutex = kernel32.CreateMutexW(None, False, PET_NAME_ASCII + '_V1_Singleton')
    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return False  # Instance already running
    return True


def _find_existing_window():
    """Enumerate top-level windows to find pet window: prefer exact title, then match historical version title prefix.
    (Old version EXE window title was set by PyInstaller from EXE name "Golden Retriever Desktop Pet vN")"""
    import ctypes
    import ctypes.wintypes as wt
    user32 = ctypes.windll.user32
    exact = user32.FindWindowW(None, WINDOW_TITLE)
    if exact:
        return exact
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND)
    def _cb(hwnd):
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value.startswith(PET_NAME):  # Derived from CONFIG: matches this pet's EXE window title prefix
                found.append(hwnd)
        return True

    user32.EnumWindows(_cb, 0)
    return found[0] if found else 0


def _activate_existing_instance():
    """When instance already running: bring its window to foreground, let user see \"pet already running\".
    Old version silently exited -> user got no feedback from double-click, thought program broken."""
    if sys.platform != 'win32':
        return
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = _find_existing_window()
    if not hwnd:
        return
    SW_RESTORE = 9          # Restore if minimized
    SW_SHOWNOACTIVATE = 4   # Show without stealing focus (pet window never activates)
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    # Top window (WindowStaysOnTopHint) may be overridden by other top windows,
    # SetForegroundWindow restricted for non-foreground processes, use AttachThreadInput for privilege
    kernel32 = ctypes.windll.kernel32
    fore_thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    app_thread = kernel32.GetCurrentThreadId()
    if fore_thread != app_thread:
        if user32.AttachThreadInput(fore_thread, app_thread, True):
            user32.SetForegroundWindow(hwnd)
            user32.AttachThreadInput(fore_thread, app_thread, False)
    else:
        user32.SetForegroundWindow(hwnd)


def _is_window_responsive(hwnd, timeout_ms=1500):
    """v66-fix: Use SendMessageTimeout(SMTO_ABORTIFHUNG) to probe old instance message queue liveness.
    If old instance event loop is frozen (zombie), call fails immediately without blocking this process."""
    import ctypes
    SMTO_ABORTIFHUNG = 0x0002
    result = ctypes.c_long()
    ok = ctypes.windll.user32.SendMessageTimeoutW(
        int(hwnd), 0x0000, 0, 0, SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(result))
    return bool(ok)


def _kill_process_of_hwnd(hwnd):
    """v66-fix: Terminate zombie old instance process (release singleton lock), don't touch this process"""
    import ctypes
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(int(hwnd), ctypes.byref(pid))
    if not pid.value or pid.value == os.getpid():
        return False
    PROCESS_TERMINATE = 0x0001
    kernel32 = ctypes.windll.kernel32
    ph = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid.value)
    if not ph:
        return False
    kernel32.TerminateProcess(ph, 0)
    kernel32.CloseHandle(ph)
    return True


def _release_singleton_mutex():
    """v66-fix: Close this process's mutex handle.
    Kernel mutex object destroyed only after all handles closed  --  if don't close own first handle,
    after killing old process second CreateMutexW still returns ALREADY_EXISTS (false takeover failure)."""
    global _singleton_mutex
    if _singleton_mutex:
        import ctypes
        ctypes.windll.kernel32.CloseHandle(_singleton_mutex)
        _singleton_mutex = None


def main():
    global _pet_window
    _install_excepthook()
    # v69-fix: C-level crash (Qt C++ abort/segfault/stack overflow) doesn't go through excepthook, leaves no log,
    # process "silently disappears". faulthandler registers native signal handlers, writes traceback to crash.log,
    # reproduce next time to locate. Handle held globally to prevent GC.
    global _crash_fh
    try:
        import faulthandler
        if getattr(sys, 'frozen', False):
            _crash_fh = open(os.path.join(os.path.dirname(sys.executable), 'crash.log'),
                             'a', encoding='utf-8')
        else:
            _crash_fh = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'crash.log'),
                             'a', encoding='utf-8')
        faulthandler.enable(file=_crash_fh, all_threads=True)
    except Exception:
        _crash_fh = None
    if not _acquire_single_instance():
        # v66-fix: When old instance exists, probe liveness first  --  only "activate existing window" if responsive;
        # if zombie (event loop frozen) terminate old process and take over startup,
        # fixes "new EXE always activates zombie old window, user sees frozen dog" dead loop.
        hwnd = _find_existing_window()
        if hwnd and _is_window_responsive(hwnd):
            _activate_existing_instance()
            return
        took_over = False
        if hwnd and _kill_process_of_hwnd(hwnd):
            time.sleep(0.6)  # Wait for old process to release mutex
            _release_singleton_mutex()  # Close this process handle, kernel object then destroyed
            took_over = _acquire_single_instance()
        if not took_over:
            _activate_existing_instance()
            return
    # HiDPI support: must set before QApplication creation
    # v49-fix: PassThrough rounding policy -- use monitor real scale (e.g. 1.5x), no integer rounding.
    # fixes Windows high-scale "back-buffer size != physical window size" compositing misalignment (black screen/pet fragments):
    # Default Round rounds 1.5x to 2.0, back-buffer 640px composited into ~427px window -> clipping+offset.
    # (Tested: SetProcessDpiAwarenessContext unsupported on this machine, err=87, don't add native DPI calls)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    _pet_window = PetWindow()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
