#!/usr/bin/env python3
"""
桌面宠物混合渲染引擎（golden v71 最终验证版模板，换宠物复制本文件为 <name>_pet.py）
=========================================================
换宠物只改 CONFIG 四值（PET_NAME/PET_NAME_ASCII/BARK_TEXT/EAT_TEXT）+ ANIMS 字典
（帧数与 extract RT_FRAMES / deploy ANIMS 三处 1:1 同步）。
核心原理（与竞品Deskpet Dog完全一致）：
  1. 原版金毛犬精灵图作为基底（保留原版神韵）
  2. 实时程序化叠加效果，让静态图"活"起来：
     - 呼吸层：裁切胸部区域，以0.9透明度放大1.5-2.5%重绘（竞品drawIdleSprite技术）
     - 待机浮动：整体Y轴正弦微浮
     - 行走摇摆：±2°旋转 + 弹跳，与步伐帧同步
     - 打滚：单帧精灵做360°连续旋转（纯程序化）
     - 落地挤压/拉伸（squash & stretch）
     - 拖拽倾斜：随速度旋转
     - 方向翻转：scale(-1,1)镜像
  3. 60fps连续渲染，帧动画+变换叠加
  4. 完整行为AI：任务栏漫步/桌面漫游/逗弄追鼠标/如厕/睡觉
  5. 物理系统：惯性拖拽+抛掷+重力弹跳
  6. 粒子特效：爱心/Zzz/臭味/星星/食物碎屑/气泡文字
"""

import sys
import math
import random
import time
import os
import json

from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer, QPoint, QPointF, QRectF, QRect, QThread, QEventLoop, QEvent
from PyQt5.QtGui import (
    QPainter, QPen, QBrush, QColor, QPainterPath, QFont, QFontMetrics,
    QImage, QImageReader, QCursor, QRadialGradient, QLinearGradient
)

# 跨平台中文字体：macOS无微软雅黑，回退到苹方
_UI_FONT = 'PingFang SC' if sys.platform == 'darwin' else 'Microsoft YaHei'

# ═══ v66 参数化（换宠物改这里）═══
PET_NAME = '金毛犬桌面宠物'            # 中文显示名（窗口前缀/单例提示）
PET_NAME_ASCII = 'GoldenDesktopPet'   # 英文名（窗口标题/单例mutex）
BARK_TEXT, EAT_TEXT = '汪!', '好吃!'   # 气泡文字


def asset_path():
    """资源路径（兼容PyInstaller打包）"""
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'assets')


# ═══════════════════════════════════════════════════════════
#  动画配置 — 每个状态的帧序列与帧时长
# ═══════════════════════════════════════════════════════════
ANIMS = {
    # state: (prefix, frame_count, frame_ms, loop, intro_frames)
    # v25(P4补帧): 帧数较v8提升1.7x~2x，消除掉帧感。frame_ms按比例缩短以保持
    #   总时长不变（引擎按 elapsed/frame_ms 推进帧，帧数翻倍则帧时长减半）。
    #   intro_frames同样按比例放大；帧间插值由build_reframe.py离线生成。
    #   sleep为intro(0-38坐→哈欠→侧倒)+循环段(39-47侧躺呼吸ping-pong)；stretch 49帧。
    # v53 节奏统一：所有状态源视频均24fps原生、时长≈5.04s（sleep 10.04s）。
    #   旧配置遗留v8-era压缩时长（1.9~4.9s不等），导致动作忽快忽慢（相对源速1.2~2.7倍）。
    #   frame_ms 一律恢复为 源时长/帧数，动作速度=Agnes生成时的真实动物速度。
    #   walk/run(步态循环+腿装配)、eat(定制碗)、sleep(10s含intro)、lick(双周期定制)为认可版，保持。
    'idle':      ('idle',      101, 50,  True,  0),   # 5.05s = 源5.04s
    'walk':      ('walk',      32, 83,  True,  0),   # v75: 3原生周期64帧stride2=32帧@83ms≈2.66s循环, 修"重复播放"(19帧2周期1.6s)
    'run':       ('run',       15, 54,  True,  0),
    'eat':       ('eat',       34, 96,  True,  0),    # 定制认可版(碗烤入),不升帧
    'bark':      ('bark',      57, 90,  True,  0),    # 5.13s = 源5.04s
    'sleep':     ('sleep',     51, 110, True,  39),   # v50 P3: 同源重生成(完全侧躺四脚摊开) 39 intro+12 loop
    'sit':       ('sit',       63, 80,  True,  22),   # 5.04s = 源5.04s
    # v46: 素材含2舔毛周期→"循环两次"感。重构54帧=0-7坐下intro(播一次)+
    #   8-31单舔毛周期正播+30-9倒播ping-pong(抬回=无缝循环)，duration配套4.0
    'lick':      ('lick',      54, 74,  True,  8),
    'happy':     ('happy',     121, 42, False, 0),  # v56: 24fps原生全帧(原62@82ms=12fps掉帧+模糊)
    'roll':      ('roll',      121, 42, False, 0),    # v54: puppy管线重生成 24fps原生全帧 5.08s 一次性(站→仰滚→坐)
    'dance':     ('dance',     57, 90,  True,  0),    # 5.13s = 源5.04s
    'stretch':   ('stretch',   117, 43, False, 0),    # 5.03s = 源5.04s
    'beg':       ('beg',       56, 91,  True,  0),    # 5.10s = 源5.04s
    'bath':      ('bath',      57, 90,  True,  0),    # 5.13s = 源5.04s
    'surprised': ('surprised', 45, 114, False, 0),    # 5.13s = 源5.04s 一次性
    'play_dead': ('play_dead', 68, 75,  False, 0),    # 5.10s = 源5.04s 一次性
    'pet':       ('pet',       107, 42, False, 0),    # v57: 独立摸摸头互动(人手抚摸+小狗享受) 24fps原生 一次性 4.5s
    'potty_run': ('run',       15, 54,  True,  0),  # 复用run帧，帧数必须与run一致
    'potty':     ('sit',       63, 80,  True,  22),   # 复用sit帧(同v53)
}

# 侧面视角状态（walk/run素材本身朝右，向左移动时需镜像；镜像方向由self.flipped=facing<0控制）
LEFT_FACING = {'walk', 'run'}

CANVAS = 320          # 窗口尺寸（320>250+挤压/旋转溢出余量，杜绝变换裁切）
DRAW_SIZE = 250       # 精灵绘制尺寸
GROUND_PAD = 14       # 脚底留白

# ═══════════════════════════════════════════════════════════
#  v25 (P9): 全局缩放 — 菜单"大小"可放大/缩小/重置，比例持久化
# ═══════════════════════════════════════════════════════════
ZOOM_DEFAULT = 1.0
ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.5, 2.5, 0.25


def zoom_cfg_path():
    """缩放配置文件位置（打包后在exe同目录）"""
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
    """v2 高分辨率: 精灵纹理尺寸必须乘 devicePixelRatio——否则 Retina(dpr=2)
    上 250px 逻辑尺寸的纹理被拉伸到 500 设备像素=恒定2倍放大模糊
    （Mac/高分屏"粗糙"的头号根因）。跨屏时取窗口所在屏的 dpr。"""
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
#  v67: 自绘圆角菜单 —— 根治 macOS QMenu 四角白角
#  QMenu+WA_TranslucentBackground 在 macOS 下圆角外仍渲染白底；
#  改用与主窗口同机制的 QPainterPath 自绘 popup，两平台像素级一致。
# ═══════════════════════════════════════════════════════════
_MENU_BG = QColor('#2b2b3a')
_MENU_FG = QColor('#e8e8f0')
_MENU_HOVER = QColor('#4a4a6e')
_MENU_BORDER = QColor('#45455c')
_MENU_ITEM_H = 34
_MENU_SEP_H = 9
_MENU_PAD = 8


class RoundedMenu(QWidget):
    """自绘 popup 菜单：QPainterPath 圆角绘制，支持分隔线与 hover 展开子菜单。
    exec_menu(global_pos) -> 选中项 key 或 None。"""

    def __init__(self, parent=None):
        # v67: 不用 Qt.Popup——主/子菜单两个独立 Popup 在 Windows 下鼠标捕获
        # 冲突（子菜单展开后主菜单收不到事件）。改 Tool+顶层+应用级
        # eventFilter 统一路由鼠标， outside 点击/Escape 自行关闭。
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

    # ---- 构建 ----
    def add_item(self, key, text):
        self.items.append(('item', key, text))

    def add_sep(self):
        self.items.append(('sep',))

    def add_sub(self, text, submenu):
        # 子菜单保持独立 top-level popup（级联菜单正确形态）；
        # 不可 setParent 到主菜单——否则 render/grab 的 DrawChildren
        # 会连带渲染未布局的子弹出窗口导致崩溃。
        submenu.root = self.root
        self.items.append(('sub', text, submenu))

    # ---- 布局/定位 ----
    def _layout(self):
        fm = QFontMetrics(self._font)
        w = 0
        for it in self.items:
            if it[0] == 'sep':
                continue
            # item=('item',key,text) / sub=('sub',text,menu)
            text = it[1] if it[0] == 'sub' else it[2]
            w = max(w, fm.horizontalAdvance(text))
        self._w = w + _MENU_PAD * 2 + 58  # 图标+文本+子菜单箭头留白
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
        """模态显示于全局坐标 pos，返回选中项 key（None=取消）"""
        self._layout()
        self._result = None
        self.move(*self._clamp(pos.x(), pos.y(), pos))
        self.show()
        self.raise_()
        self.activateWindow()
        # 应用级滤镜：主/子菜单统一接收鼠标路由（Qt.Popup 双窗口捕获冲突的根治）
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
                # 缝隙带（主/子菜单间2px接缝）或菜单外：不扰动 hover，避免闪
                return False
            if tgt.hover_idx != tgt._idx_at(gp):
                ni = tgt._idx_at(gp)
                if ni < 0 and tgt.hover_idx >= 0:
                    # v68: pad边条/分隔线带不扰动当前hover（高亮保持），
                    # 避免穿越间隙时高亮闪失、且杜绝任何连带关闭路径
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
                    self.close_all()  # 菜单外点击 = 取消（缝隙带点击不关）
        elif t == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
            self.close_all()
        return False

    # ---- 子菜单 ----
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
            # v68: 只有hover落到"另一个明确条目"才关子菜单。hover=-1（pad边条/
            # 分隔线）保持子菜单——进入子菜单的必经之路是主菜单右侧8px pad带，
            # 旧逻辑hover=-1即关，鼠标慢速穿越必收（"有时自动收起"根因）。
            self._close_submenu()

    def _close_submenu(self):
        if self.sub_open is not None:
            self.sub_open.close_all()
            self.sub_open = None

    def close_all(self):
        self._close_submenu()
        self.close()

    # ---- 交互 ----
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
            return  # 子菜单项由 hover 展开
        self.root._result = it[1]
        self.root.close_all()

    def closeEvent(self, e):
        self._close_submenu()
        if self._loop is not None:
            self._loop.quit()
        super().closeEvent(e)

    # ---- 绘制 ----
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
                p.drawText(r.adjusted(-14, 0, -6, 0), Qt.AlignVCenter | Qt.AlignRight, '▶')
        p.end()

# ═══════════════════════════════════════════════════════════
#  v24: LEG_RIG 清空 —— 逐帧视觉判定证明:
#  1) walk 的 v13 帧本身自带真实交叉步态(前后腿角色逐帧互换、完整walk cycle)，
#     切腿钟摆把腿对切成刚性整块同步摆动，反而把交叉步态破坏成"四条腿一起摇摆"。
#  2) run 的旧帧腿部完全冻结(8帧同一伸展姿势)，rig只能造成成对摇摆。
#  正确路线: walk纯帧播放; run用Agnes重新生成真实伸缩循环视频后抽帧(见agnes_test)。
#  历史校准几何备份在 test_p2_rigcal_v13.py 输出中，如需再启用rig可参考。
# ═══════════════════════════════════════════════════════════
LEG_RIG = {
    # v24: 空——纯帧播放。walk帧自带交叉步态；run帧重新生成后同样纯帧播放。
}
RIG_BODY_OVERLAP = 12  # 身体块向下越过切线的行数（覆盖接缝）——v19: 4→12，腿旋转时腹下不露洞
RIG_LEG_TOP = 8        # 腿块从切线上方N行开始（与身体重叠）——v19: 2→8 加深重叠
RIG_FADE = 12          # 腿块顶部N行alpha线性渐隐（接缝融合）——v19: 6→12 消除硬切线


def _approach(v, target, rate, dt):
    """将v以rate的速率平滑趋近target（用于速度缓动）"""
    if v < target:
        return min(v + rate * dt, target)
    return max(v - rate * dt, target)


# ═══════════════════════════════════════════════════════════
#  精灵库 — 加载/缩放/镜像预处理
# ═══════════════════════════════════════════════════════════
_BODY_BOTTOM_CACHE = {}   # v66: cacheKey→底缘行（像素扫描结果缓存）
_BODY_BOTTOM_CACHE2 = {}  # v66: cacheKey→内容底边行（lift扫描缓存）


def _crash_log(tag):
    """v69-fix: QThread 未捕获异常在 C++ 层 std::terminate——无 traceback/无事件日志/
    无 crash.log，进程静默死亡（"执行动作后自动关闭"根因）。此函数供线程 run() 的
    兜底 except 写日志，死亡降级为"该动作空白但进程存活"。"""
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


_crash_fh = None  # faulthandler 文件句柄全局持有（防GC关闭）


class _LoadThread(QThread):
    """v48: 后台重建精灵——主线程同步load()会卡死UI（579帧×纯Python像素扫描）。
    线程内构建完整bank数据，finished后主线程原子swap，渲染期间不半态。"""
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
            # v69-fix: QThread未捕获异常=std::terminate=进程静默死亡（无crash.log/
            # 无事件日志/无traceback，"执行动作后自动关闭"根因之一）。捕获后记日志降级。
            _crash_log('LoadThread')
            self.result = None


class _StateLoadThread(QThread):
    """v64: 懒加载单状态——后台构建该状态帧表，finished后主线程写回bank。"""
    def __init__(self, bank, state):
        super().__init__()
        self.bank, self.state = bank, state
        self.imgs = None
        self.lift = None

    def run(self):
        try:
            self.imgs, self.lift = self.bank._build_state(self.state)
        except Exception:
            # v69-fix: 同上——懒加载线程异常不再杀死进程，记日志降级（该动作空白但存活）
            _crash_log(f'StateLoadThread[{self.state}]')
            self.imgs, self.lift = None, None


class SpriteBank:
    # v64: tight画布状态（assets由rebake_v64.py重烘焙：去空白边+质心居中+脚底锚定，
    # calm六态基准统一560）。walk=认可版保持1024²方画布原路径。
    TIGHT = {'idle', 'run', 'eat', 'bark', 'sleep', 'sit', 'lick', 'happy',
             'roll', 'dance', 'stretch', 'beg', 'bath', 'surprised',
             'play_dead', 'pet'}
    # v64: 一次性/低频状态懒加载——启动不预载，首次set_state触发后台异步装载，
    # 常驻集=交互高频七态，内存峰值大幅下降。
    # v67: dance/beg/bath 移入懒集（常驻-28MB纹理），首次触发走同步快路径。
    LAZY = {'happy', 'roll', 'stretch', 'pet', 'play_dead', 'surprised',
            'sleep', 'dance', 'beg', 'bath'}
    ASSET_SCALE = 1.05  # 纹理长边=屏上设备像素长边×1.05（1:1锐度+微余量，内存最小化）

    def __init__(self):
        self.frames = {}     # state -> [QImage正常]
        self.frames_m = {}   # state -> [QImage镜像]
        self.geo = {}        # v64: state -> (源宽, 源高) 首帧尺寸(tight恒定)
        self.alias = {}      # v64: state -> 帧表所有者(potty→sit等，去重不双载)
        self._lazy_threads = {}
        # 腿部装配部件：state -> dict(body/front/rear 各 [QImage正常, QImage镜像])
        self.rig_parts = {}
        self.rig_parts_m = {}
        self.lift_map = {}   # state -> [每帧离地高度 0..1]（跳跃弧线联动阴影）

    # v73: 主体视觉尺寸补偿——tight路径按画布长边缩放，视频原生取景小的状态
    # (roll躺侧/378, dance直立窄身, pet含手) 屏上主体会明显小于idle(540)。
    # 系数按 bbox/canvas 占比向idle对齐标定（用户肉眼验收后微调）。
    SIZE_COMP = {'roll': 1.42}   # v75: roll侧躺bbox高仅idle的65%→放大; pet/dance高已=idle基线(543/545/542)不放大

    def _state_draw(self, state):
        """v64: 每状态按需分辨率。旧版统一draw=500(dpr2)——方画布空白也占长边，
        纹理长边可达屏上需求2倍，内存∝draw²爆炸。改为按tight长边占比分配：
        draw_s = draw × max(w,h)/1024 × ASSET_SCALE，钳制[96,1024]。
        v73: 乘SIZE_COMP保证放大后纹理分辨率不糊。"""
        draw = getattr(self, 'draw_size', DRAW_SIZE)
        if state in self.TIGHT:
            w, h = self.geo.get(state, (1024, 1024))
            return max(96, min(1024, int(round(draw * max(w, h) / 1024.0
                                               * self.ASSET_SCALE
                                               * self.SIZE_COMP.get(state, 1.0)))))
        return min(draw, 1024)

    def load(self):
        base = asset_path()
        # ── v64 几何表：读每状态首帧尺寸（tight资产同状态尺寸恒定）──
        for state, (prefix, _c, _f, _l, _i) in ANIMS.items():
            if state in self.geo or state in self.alias:
                continue
            for ext in ('webp', 'png'):
                fn = os.path.join(base, f'{prefix}_00.{ext}')
                if os.path.exists(fn):
                    r = QImageReader(fn)
                    sz = r.size()
                    if sz.isValid():
                        self.geo[state] = (sz.width(), sz.height())
                    break
            self.geo.setdefault(state, (1024, 1024))
        # ── v64 别名表：同prefix状态共享帧列表（potty→sit、potty_run→run）──
        for state, (prefix, _c, _f, _l, _i) in ANIMS.items():
            owner = next((s2 for s2, (p2, _c2, _f2, _l2, _i2) in ANIMS.items()
                          if p2 == prefix), None)
            if owner and owner != state:
                self.alias[state] = owner
                self.geo.setdefault(state, self.geo.get(owner, (1024, 1024)))
        # ── 装载：别名指向所有者列表；懒状态占位空表首次触发时装载 ──
        # v67 启动快路径：FAST_BOOT 四态主线程同步限帧装载（首屏<300ms），
        # 其余常驻态由调用方后台全量构建后 swap 补装。
        fast = getattr(self, 'fast_boot', False)
        for state in ANIMS:
            if state in self.alias:
                owner = self.alias[state]
                self.frames[state] = self.frames[owner]
                self.frames_m[state] = self.frames_m[owner]
                self.lift_map[state] = self.lift_map[owner]
            elif state in self.LAZY:
                self.frames[state] = []
                self.frames_m[state] = []
                self.lift_map[state] = []
            elif fast:
                # v67: 全部常驻态限6帧同步装载（≈30帧<1s，首屏零空白），
                # 完整帧表由后台 _LoadThread swap 补齐。
                self._load_state(state, 6)
            else:
                self._load_state(state)
        # v19: 逐帧切腿——run素材含gallop跳跃（逐帧body_bot位移达31px），
        # 固定切线(只用第0帧)会让跳跃帧腿块错位。每帧按自身身体底缘切割，
        # 既保留帧内gallop起伏，又保证切线始终贴合身体。
        # potty_run 复用 run 帧，同样装配
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
                    cut = max(40, min(240, bb - 8))   # 切线=身体底缘上方8行
                g2 = dict(geo, cut_row=cut,
                          front_hip=(geo['front_hip'][0], cut + 1),
                          rear_hip=(geo['rear_hip'][0], cut + 1))
                parts.append(self._cut_rig(img, g2, mirrored=False))
                parts_m.append(self._cut_rig(img_m, g2, mirrored=True))
            self.rig_parts[state] = parts
            self.rig_parts_m[state] = parts_m

    def _sync_first_frame(self, state):
        """v67: 懒状态首帧同步快路径——后台全量装载完成前先装1帧立即显示，
        根治动作触发"卡顿+空白画面"（旧版异步装载期间get()返回空图=空白）。
        全量线程完成后 _on_lazy_done 原子覆盖为完整帧表。"""
        owner = self.alias.get(state, state)
        if owner not in self.LAZY:
            return
        if self.frames.get(owner) or owner in self._lazy_threads:
            return
        try:
            imgs, lift = self._build_state(owner, 1)
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
        """v64: 懒状态首次触发→后台异步装载（不阻塞渲染；装载期间get()返回空图跳过绘制）
        v67: 先同步装首帧（<80ms）保证立即有画面，后台线程随后全量覆盖。"""
        if state not in self.LAZY or self.frames.get(state):
            return
        if state in self._lazy_threads:
            return
        self._sync_first_frame(state)
        t = _StateLoadThread(self, state)
        self._lazy_threads[state] = t
        t.finished.connect(lambda s=state, th=t: self._on_lazy_done(s, th))
        t.start()

    def _on_lazy_done(self, state, t):
        self._lazy_threads.pop(state, None)
        if t.imgs is not None:
            self.frames[state] = t.imgs
            self.frames_m[state] = [None] * len(t.imgs)
            self.lift_map[state] = t.lift
            # v67: 全量帧表替换首帧快路径后，当前帧索引可能越界（首帧bank长度1），
            # 通知窗口复位动画相位避免 IndexError/卡帧。
            cb = getattr(self, 'on_state_reloaded', None)
            if cb:
                cb(state)
        t.deleteLater()

    def _load_state(self, state, frame_limit=None):
        imgs, lift = self._build_state(state, frame_limit)
        self.frames[state] = imgs
        self.frames_m[state] = [None] * len(imgs)
        self.lift_map[state] = lift
        # v66 LRU: 记录装载顺序（供卸载最久未用的懒状态）
        self._loaded_order = getattr(self, '_loaded_order', [])
        if state in self.LAZY and state not in self._loaded_order:
            self._loaded_order.append(state)

    def unload_idle_lazy(self, active_state, keep=4):
        """v66: 内存回收——已装载的懒状态超出 keep 个且非当前态时，
        卸载最久未触发的（frames/frames_m/lift 清空回懒态占位）。
        别名态(potty→sit)与当前态、常驻态不卸。返回卸载数。"""
        order = getattr(self, '_loaded_order', [])
        n = 0
        for st in list(order):
            if len(order) - n <= keep:
                break
            if st == active_state or not self.frames.get(st):
                continue
            # 有别名态指向它→不卸
            if any(self.alias.get(s2) == st for s2 in self.alias):
                continue
            self.frames[st] = []
            self.frames_m[st] = []
            self.lift_map[st] = []
            order.remove(st)
            n += 1
        return n

    def _build_state(self, state, frame_limit=None):
        """v64: 单状态帧表构建。tight态按原比例缩放到按需分辨率（长边=draw_s）；
        方画布态(walk认可版)走旧路径(scaled方框+质心居中)。
        v67: frame_limit——只构建前N帧（启动快路径/懒状态首帧同步快路径），
        调用方负责后续全量补装。"""
        base = asset_path()
        prefix, count, _f, _l, _i = ANIMS[state]
        tight = state in self.TIGHT
        draw = self._state_draw(state)
        if frame_limit:
            count = min(count, frame_limit)
        imgs = []
        for i in range(count):
            fn = os.path.join(base, f'{prefix}_{i:02d}.webp')
            if not os.path.exists(fn):
                fn = os.path.join(base, f'{prefix}_{i:02d}.png')
            img = QImage(fn)
            if img.isNull():
                continue
            img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
            if tight:
                w, h = img.width(), img.height()
                sc = draw / float(max(w, h))
                img = img.scaled(max(2, int(round(w * sc))),
                                 max(2, int(round(h * sc))),
                                 Qt.KeepAspectRatio, Qt.SmoothTransformation)
            else:
                # 缩放到目标尺寸（双线性平滑）
                img = img.scaled(draw, draw,
                                  Qt.KeepAspectRatio, Qt.SmoothTransformation)
            imgs.append(img)
        if not tight and imgs:
            # v49: 镜像懒生成——get()首次请求时按需镜像已居中的draw×draw画布
            # （居中天然对称，无shift误差）。
            imgs, _sh = self._center_frames(imgs)
        # ── 每帧离地高度：内容包围盒底边相对全序列最大底边的抬升（归一化0..1）──
        # 纯Python抽样扫描：从底向上逐行、每8列取一点（脚底通常前几行即命中）
        # v66: cacheKey缓存底边（动作重复触发/zoom重建不重扫，消除触发CPU尖峰）
        bottoms = []
        for im in imgs:
            key = im.cacheKey()
            if key in _BODY_BOTTOM_CACHE2:
                bottoms.append(_BODY_BOTTOM_CACHE2[key])
                continue
            buf = im.constBits()
            buf.setsize(im.byteCount())
            data = bytes(buf)   # bytes索引返回int，可直接比较
            w4 = im.width() * 4
            bpl = im.bytesPerLine()
            cols = range(0, w4, 32)   # 每8列采样alpha通道
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
            # 阴影闪烁根因：腿姿态/呼吸引起的底边小幅抖动(<30px)不是真跳跃，
            # 旧代码用 max(6.0, var) 归一化会把12px抬腿放大成100%离地→阴影每步收缩45%。
            # 变差<30px 视为贴地，lift恒为0；仅真跳跃状态(run/jump/stretch等)保留阴影联动。
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
        """内容底缘上方第一个'宽行'(>62%最大行宽)的行号=身体底缘；无内容返回None。
        v66: cacheKey缓存（同图不重扫，zoom重建/重复装配省CPU）。"""
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

    @staticmethod
    def _content_centroid_x(img):
        """内容(alpha>24)的水平质心x；无内容返回None
        v48: 4x降采样（旧逐像素纯Python扫描占load()70%耗时，2.5x缩放时20s）。
        均匀降采样质心误差<2px，shift取int(round)后输出不变。"""
        w, h = img.width(), img.height()
        buf = img.constBits()
        buf.setsize(img.byteCount())
        data = bytes(buf)
        bpl = img.bytesPerLine()
        sum_x, cnt = 0.0, 0
        for y in range(0, h, 4):
            rowbase = y * bpl + 3  # ARGB32 的 alpha 通道
            for x in range(0, w, 4):
                if data[rowbase + x * 4] > 24:
                    sum_x += x
                    cnt += 1
        return sum_x / cnt if cnt else None

    def _center_frames(self, imgs, shift=None):
        """v11 帧水平居中：整序列共享偏移，根治'超出边框'。
        根因：walk帧内容贴素材左缘(左边距=0)、质心偏-44px，镜像后狗头顶窗口边缘；
        且帧间质心漂移导致左右晃动。用全序列平均质心做统一平移——
        既让狗在窗口内居中，又消除帧间水平抖动。v25: 按当前缩放尺寸绘制。
        v48: shift可外部指定(镜像帧公式推导)，返回(out, shift)供调用方推导镜像偏移。"""
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
            canvas = QImage(draw, draw, QImage.Format_ARGB32)
            canvas.fill(Qt.transparent)
            p = QPainter(canvas)
            p.drawImage(shift, 0, im)
            p.end()
            out.append(canvas)
        return out, shift

    def _cut_rig(self, img, geo, mirrored=False):
        """把精灵切成 身体/前腿/后腿 三块（带接缝渐隐）
        mirrored=True 时输入为镜像图：分割线镜像，部件按解剖学归属命名"""
        # 规范化到draw_size画布(水平居中/底部对齐)，与离线烘焙几何严格对齐
        draw = self.draw_size
        canvas = QImage(draw, draw, QImage.Format_ARGB32)
        canvas.fill(Qt.transparent)
        cp = QPainter(canvas)
        cp.drawImage((draw - img.width()) // 2,
                     draw - img.height(), img)
        cp.end()
        img = canvas

        w, h = img.width(), img.height()
        cut = geo['cut_row']
        split = geo['split_x'] if not mirrored else w - geo['split_x']
        # 身体块：完整宽度，向下越过切线RIG_BODY_OVERLAP行（覆盖髋部接缝）
        body = img.copy(0, 0, w, min(h, cut + RIG_BODY_OVERLAP))
        # 腿块：从切线上方RIG_LEG_TOP行开始（与身体重叠，旋转时不漏底）
        leg_y0 = max(0, cut - RIG_LEG_TOP)
        leg_h = h - leg_y0
        left = img.copy(0, leg_y0, split, leg_h)
        right = img.copy(split, leg_y0, w - split, leg_h)
        if mirrored:
            # 镜像后解剖学前腿在右侧
            front, front_x0 = right, split
            rear, rear_x0 = left, 0
        else:
            front, front_x0 = left, 0
            rear, rear_x0 = right, split
        # 腿块顶部渐隐（接缝融合）：DestinationIn用alpha渐变蒙版
        for part in (front, rear):
            mp = QPainter(part)
            mp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            grad = QLinearGradient(0, 0, 0, RIG_FADE)
            grad.setColorAt(0.0, QColor(0, 0, 0, 0))
            grad.setColorAt(1.0, QColor(0, 0, 0, 255))
            mp.fillRect(0, 0, part.width(), RIG_FADE, QBrush(grad))
            mp.end()
        # 髋关节枢轴：转换到各腿块的局部坐标
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
        state = self.alias.get(state, state)   # v64: 别名解析(potty→sit)，懒owner安全
        if flipped:
            bank = self.frames_m[state]
            i = idx % len(bank) if bank else 0
            if not bank or bank[i] is None:
                src = self.frames.get(state) or []
                if not src:
                    return QImage()   # v64懒加载未完成→空图跳过绘制
                # v49镜像懒生成：首次请求才镜像，内存减半
                bank[i] = src[i].mirrored(True, False)
            return bank[i]
        bank = self.frames[state]
        if not bank:
            return QImage()           # v64懒加载未完成→空图跳过绘制
        return bank[idx % len(bank)]


# ═══════════════════════════════════════════════════════════
#  粒子系统
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
                # 气泡文字（如"汪!"）
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
                # 小尾巴
                path = QPainterPath()
                path.moveTo(x - 4, by + bh - 1)
                path.lineTo(x, by + bh + 6)
                path.lineTo(x + 5, by + bh - 1)
                painter.drawPath(path)
                painter.setPen(QColor(70, 80, 100, int(alpha * 255)))
                painter.drawText(QPointF(x - tw / 2, by + 18), text)


# ═══════════════════════════════════════════════════════════
#  物理系统
# ═══════════════════════════════════════════════════════════
class Physics:
    def __init__(self):
        self.vx = 0.0
        self.vy = 0.0
        self.active = False
        self.gravity = 1600.0
        self.restitution = 0.38
        self.squash = 0.0   # 落地挤压计时

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

        # 地面
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
        # 左右墙
        if x < screen_l:
            x = screen_l
            self.vx = -self.vx * 0.5
        elif x > screen_r:
            x = screen_r
            self.vx = -self.vx * 0.5
        # 天花板：抛出后不再冲出屏幕顶部（旧代码无上边界→宠物飞出可视区域）
        if y < 0:
            y = 0
            if self.vy < 0:
                self.vy = -self.vy * 0.35

        win.move(int(x), int(y))
        self.squash = max(0, self.squash - dt * 4)
        return bounced


# ═══════════════════════════════════════════════════════════
#  主窗口
# ═══════════════════════════════════════════════════════════
WINDOW_TITLE = PET_NAME_ASCII + '_MainWindow'  # 固定窗口标题：供重复启动的新实例FindWindow定位并激活（从CONFIG派生，换宠物无需改）


class PetWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        # v25 (P1): 根治"点击宠物外区域宠物消失"——
        # 旧代码用 Qt.Tool：Windows下Tool窗口属于"工具浮窗"，其他应用激活时系统会隐藏它。
        # 改为普通 Qt.Window + WS_EX_NOACTIVATE：窗口永不抢占焦点、不抢前台，
        # 但属于独立顶层窗口，失焦/切走都不会被系统隐藏。
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        # v25 (P9): 读取持久化缩放比例（默认1.0）
        self.zoom = load_zoom()
        self.setFixedSize(int(CANVAS * self.zoom), int(CANVAS * self.zoom))

        self.bank = SpriteBank()
        # v2 高分辨率: 纹理尺寸=逻辑尺寸×dpr，Retina上设备像素1:1（不再2倍放大模糊）
        self.bank.draw_size = int(DRAW_SIZE * self.zoom * _target_dpr(self))
        # v67: 启动快路径——主线程只同步装 FAST_BOOT 四态限帧表（<300ms首屏可见），
        # 完整常驻集后台构建后原子swap（旧版同步全量=800+帧解码，首屏卡顿+空白）。
        self.bank.fast_boot = True
        self.bank.load()
        self.bank.on_state_reloaded = self._on_state_reloaded
        self._fullbank_thread = _LoadThread(self.bank.draw_size)
        self._fullbank_thread.finished.connect(self._on_fullbank_loaded)
        self._fullbank_thread.start()
        self.particles = ParticleSystem()
        self.physics = Physics()
        # Windows原生扩展样式：宠物窗口不激活、不抢焦点（Tool行为的手感，无Tool的消失bug）
        if sys.platform == 'win32':
            try:
                import ctypes
                GWL_EXSTYLE = -20
                WS_EX_NOACTIVATE = 0x08000000
                WS_EX_TOOLWINDOW = 0x00000080  # 不占任务栏按钮（原Qt.Tool的手感）
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
        self.facing = 1          # 1=右 -1=左（素材朝左，右移时镜像）
        self.flipped = False

        # 模式
        self.mode = 'taskbar'    # taskbar / desktop / tease
        self.roam_target = None
        self.tease_last_cursor = None

        # 属性
        self.fullness = 80.0
        self.happiness = 70.0
        self.energy = 90.0
        self.potty_need = 0.0

        # AI
        self.ai_timer = random.uniform(3, 7)
        self.walk_dir = random.choice([-1, 1])
        self.state_duration = {}  # 限时状态

        # 拖拽
        self.dragging = False
        self.drag_off = QPoint()
        self.mouse_hist = []
        self.throw_vel = (0, 0)

        # 渲染变换 & 运动状态
        self.roll_angle = 0.0
        self.vel_x = 0.0        # 当前水平速度 px/s（缓动）
        self.move_acc = 0.0     # 亚像素累积器
        self.pop_t = 0.0        # 状态切入弹簧
        self.antic_t = 0.0      # 起步预备下蹲
        self.settle_t = 0.0     # 停止缓冲挤压
        self.turn_phase = None  # 转身动画 0..1
        self.turn_flipped = False
        self.turn_new_facing = 1
        self.smooth_air = 0.0   # 平滑后的离地高度（防止阴影逐帧跳动闪烁）
        self.micro = None       # 待机微动作（歪头/抖动/小跳）
        self.sleep_twitch_t = 0.0
        self.sleep_twitch_next = random.uniform(5, 9)

        # 腿部装配动画相位（连续累加器，不受60fps整帧限制）
        self.leg_phase = 0.0    # 步态相位 [0, 2π)
        self.leg_amp = 0.0      # 摆幅系数（起步缓入，停止缓出）
        self._last_paint_dt = time.perf_counter()
        self._tick_cur = 16     # v66: 当前定时器间隔（自适应）

        # 初始位置：屏幕底部（按缩放窗口尺寸定位）
        sg = QApplication.primaryScreen().geometry()
        self.floor_y = sg.bottom() - int(CANVAS * self.zoom) - 45
        self.move(sg.center().x() - int(CANVAS * self.zoom) // 2, self.floor_y)

        self.last_t = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)  # Windows默认定时器抖动15-31ms，精确模式减少帧间隔波动
        self.timer.timeout.connect(self.game_loop)
        self.timer.start(16)
        self.show()

        # v25 (P1): 可见性守护——无论什么原因窗口被隐藏/最小化，2秒内强制恢复。
        # 宠物常驻桌面：只有右键菜单"退出"才能真正关闭。
        self._vis_timer = QTimer(self)
        self._vis_timer.timeout.connect(self._ensure_visible)
        self._vis_timer.start(2000)

    # ─────────── v25 (P1/P9): 常驻守护 & 缩放 ───────────
    def _ensure_visible(self):
        """窗口不可见/被最小化时强制恢复（右键"退出"是唯一关闭途径）"""
        if not self.isVisible() or self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
            self.show()

    def changeEvent(self, event):
        """拦截外部最小化（如Win+D/任务栏"显示桌面"会短暂隐藏所有窗口），保持常驻"""
        if event.type() == event.WindowStateChange and self.isMinimized():
            QTimer.singleShot(0, self._ensure_visible)
        super().changeEvent(event)

    def set_zoom(self, new_zoom):
        """v25 (P9): 运行时切换缩放——重建精灵+调整窗口+底部锚定，并持久化
        v48: 重建改后台线程（旧版主线程同步load()=579帧重载+像素扫描，卡死UI）。
        加载期间旧精灵由paintEvent顶层scale(zoom)自动缩放绘制，完成后原子swap。"""
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
        # 以窗口中心为锚点缩放，并钳制在屏幕内
        nx = self.x() + old_w // 2 - cw // 2
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
        """后台精灵构建完成——仅最新一次生效，原子替换bank，UI全程不阻塞"""
        t = self.sender()
        try:
            self._pending_loads.remove(t)
        except (ValueError, AttributeError):
            pass
        if t._seq == getattr(self, '_load_seq', 0) and t.result is not None:
            self.bank = t.result
            self.bank.on_state_reloaded = self._on_state_reloaded
            self.update()
        t.deleteLater()

    def _on_fullbank_loaded(self):
        """v67: 后台完整常驻集构建完成→原子swap。懒状态已装的首帧表保留
        （full bank 的懒集是空占位，swap 后 _loaded_order 保留、frames 保留）。"""
        t = self._fullbank_thread
        self._fullbank_thread = None
        if t.result is None:
            t.deleteLater()
            return
        new = t.result
        # 保留懒状态已装载的帧表（启动后用户触发过的动作不丢）
        for st, fr in self.bank.frames.items():
            if fr and st in new.LAZY:
                new.frames[st] = fr
                new.frames_m[st] = self.bank.frames_m.get(st) or [None] * len(fr)
                new.lift_map[st] = self.bank.lift_map.get(st) or []
        new._loaded_order = list(getattr(self.bank, '_loaded_order', []))
        new.on_state_reloaded = self._on_state_reloaded
        self.bank = new
        self.update()
        t.deleteLater()

    def _on_state_reloaded(self, state):
        """v67: 懒状态全量帧表覆盖首帧快路径后复位动画相位，防帧索引越界。"""
        owner = self.bank.alias.get(state, state)
        if self.bank.alias.get(self.state, self.state) == owner:
            bank = self.bank.frames.get(owner) or []
            if bank and self.frame_idx >= len(bank):
                self.frame_idx = 0
                self.anim_elapsed = 0.0
        self.update()

    # ─────────── 状态切换 ───────────
    def set_state(self, s, duration=None):
        if s not in ANIMS:
            return
        self.bank.ensure_state(s)   # v64: 懒状态首次触发→后台异步装载
        # v67: 懒状态首帧同步快路径——ensure_state 的后台线程需0.5-2s才完成，
        # 期间旧代码get()返回空图=空白画面。先同步装1帧(<80ms)立即显示。
        if s in self.bank.LAZY:
            self.bank._sync_first_frame(s)
        prev = self.state
        # 同状态重入（AI续走）：保持步态帧连续，不重置动画相位——
        # 否则每次AI重新决策都会把frame_idx硬切回0，步态周期性卡顿
        same_move = (s == prev and s in ('walk', 'run', 'potty_run'))
        self.state = s
        self.state_started = time.perf_counter()
        if not same_move:
            self.anim_elapsed = 0.0
            self.frame_idx = 0
        self.roll_angle = 0.0
        self.pop_t = 0.0 if same_move else 0.16
        # 起步预备动作：起跑前先下蹲蓄力
        if s in ('walk', 'run', 'potty_run') and prev not in ('walk', 'run', 'potty_run'):
            self.antic_t = 0.18
        # 停止缓冲：急停时身体前倾挤压
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
        # v66: LRU touch（当前懒状态移到队尾）+ 超量懒状态卸载回收内存
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

    # ─────────── 运动/缓动助手 ───────────
    def _integrate_vel(self, dt, target, accel, decel):
        """速度缓动趋近目标，亚像素积分移动窗口（消除抖动与滑步）"""
        rate = accel if abs(target) > 0.5 else decel
        self.vel_x = _approach(self.vel_x, target, rate, dt)
        self.move_acc += self.vel_x * dt
        step = int(self.move_acc)
        if step:
            self.move_acc -= step
            nx = self.x() + step
            # v10 跳出边框根治：移动一律钳制在屏幕内。
            # 旧代码逗弄模式追鼠标无边界→狗追到屏幕外，头/尾被屏幕边缘裁掉。
            sg = QApplication.primaryScreen().geometry()
            lo, hi = sg.left(), sg.right() - self.width()
            if nx < lo:
                nx = lo; self.vel_x = max(0.0, self.vel_x); self.move_acc = 0.0
            elif nx > hi:
                nx = hi; self.vel_x = min(0.0, self.vel_x); self.move_acc = 0.0
            self.move(nx, self.y())

    def _start_turn(self, new_facing):
        """启动转身动画（减速→转身→再加速，而非瞬间翻转）"""
        if self.turn_phase is not None or new_facing == self.facing:
            return
        self.turn_phase = 0.0
        self.turn_new_facing = new_facing

    def _update_turn(self, dt):
        if self.turn_phase is None:
            return
        self.turn_phase += dt / 0.22  # v19: 0.45→0.22 竞品式快速转身（纯镜像翻转必须快才自然，慢速+无压缩会显得呆滞）
        if self.turn_phase >= 0.5 and not self.turn_flipped:
            self.turn_flipped = True
            self.facing = self.turn_new_facing
            self.flipped = self.facing < 0
        if self.turn_phase >= 1.0:
            self.turn_phase = None
            self.turn_flipped = False

    def turn_scale(self):
        """v19已废弃：恒返回1.0。
        历史：v11用X轴压缩(max 0.35)模拟转身，被用户两次点名批评为"卡片翻转"。
        现改为竞品式纯镜像翻转——_update_turn在phase=0.5时直接切换flipped，
        全程无任何X轴缩放，配合0.22s快速转身，观感是狗利落地掉头"""
        return 1.0

    def _update_micro(self, dt):
        """待机微动作：偶尔歪头/抖毛/小跳，避免木头人站桩"""
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

    # ─────────── 主循环 ───────────
    def game_loop(self):
        now = time.perf_counter()
        dt = min(now - self.last_t, 0.05)
        self.last_t = now

        # 帧推进（步态帧与实际速度同步，防止滑步：速度越慢脚步帧越慢）
        st_for_frame = self.state
        if st_for_frame in ('walk', 'run', 'potty_run'):
            cruise = 150.0 if st_for_frame != 'walk' else 65.0
            # 下限0.45：转身减速时动画不再冻结（旧0.12导致0.3秒卡死感）
            frame_speed = max(0.45, min(1.0, abs(self.vel_x) / cruise))
        else:
            frame_speed = 1.0
        self.anim_elapsed += dt * 1000 * frame_speed
        prefix, count, frame_ms, loop, intro = ANIMS[self.state]
        raw_idx = int(self.anim_elapsed / frame_ms)
        if intro > 0 and loop:
            # intro段（坐下/趴下）只播一次，之后循环主体段，避免反复坐下起立
            if raw_idx < intro:
                self.frame_idx = raw_idx
            else:
                body_len = count - intro
                self.frame_idx = intro + ((raw_idx - intro) % body_len)
        else:
            # 循环动画取模，一次性动画（happy/play_dead）钳制在末帧
            self.frame_idx = raw_idx % count if loop else min(raw_idx, count - 1)

        # 腿部装配：步态相位连续累加，频率与实际速度成正比（防滑步）
        if self.state in ('walk', 'run', 'potty_run'):
            speed_norm = min(1.0, abs(self.vel_x) / (300.0 if self.state != 'walk' else 130.0))
            freq = 5.0 + 9.0 * speed_norm          # rad/s（步频随速度增加）
            self.leg_phase = (self.leg_phase + dt * freq) % (2 * math.pi)
            self.leg_amp = min(1.0, self.leg_amp + dt * 6.0)   # 起步缓入
        else:
            self.leg_amp = max(0.0, self.leg_amp - dt * 8.0)   # 停止缓出

        # 运动/过渡计时器
        self.pop_t = max(0.0, self.pop_t - dt)
        self.antic_t = max(0.0, self.antic_t - dt)
        self.settle_t = max(0.0, self.settle_t - dt)
        self._update_turn(dt)
        self._update_micro(dt)

        # 非移动状态的速度衰减（急停后的滑步缓冲效果）
        if (self.state not in ('walk', 'run', 'potty_run')
                and not self.physics.active and not self.dragging):
            if abs(self.vel_x) > 2:
                self._integrate_vel(dt, 0.0, 0.0, 2000.0)
            else:
                self.vel_x = 0.0
        # 睡觉时偶尔蹬腿抽搐
        if self.state == 'sleep':
            self.sleep_twitch_next -= dt
            if self.sleep_twitch_next <= 0:
                self.sleep_twitch_t = 1.0
                self.sleep_twitch_next = random.uniform(5, 10)
            self.sleep_twitch_t = max(0.0, self.sleep_twitch_t - dt * 2.5)
        # 离地高度平滑（EMA ~90ms）：run等状态帧间底边跳动不再直接驱动阴影尺寸
        lift_seq = self.bank.lift_map.get(
            self.bank.alias.get(self.state, self.state))
        if lift_seq:
            raw_air = lift_seq[self.frame_idx % len(lift_seq)]
        else:
            raw_air = 0.0
        self.smooth_air += (raw_air - self.smooth_air) * min(1.0, dt / 0.09)
        self.update_ai(dt)
        impact = self.physics.update(dt, self, self.floor_y, 0,
                                      QApplication.primaryScreen().geometry().right() - self.width())
        if impact > 200:
            self.particles.emit(ParticleSystem.DUST, CANVAS / 2, CANVAS - GROUND_PAD, 4)

        self.particles.update(dt)
        self.update_stats(dt)
        self.emit_state_particles(dt)
        # ── v66 自适应 tick：静态状态降帧省CPU，动作/过渡/粒子活跃保持16ms ──
        # 源动画均24fps原生(frame_ms≈42-114)，16ms tick重绘一半以上是无效帧。
        # 静态期 tick=源帧率（源动画本身20fps左右，更高=重绘同一帧纯耗CPU）；
        # 动作/过渡/粒子/物理/拖拽活跃期=16ms，保证动作质量不掉帧。
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
        # v66: 静态且帧未变→跳过重绘（透明窗无变化=零绘制CPU）
        if (active or moving
                or getattr(self, '_last_drawn', None) != (self.state, self.frame_idx, self.flipped)):
            self.update()

    # ─────────── 行为AI ───────────
    def update_ai(self, dt):
        st = self.state
        st_time = self.state_time()
        sg = QApplication.primaryScreen().geometry()

        # 限时状态结束
        if st in self.state_duration and st_time > self.state_duration[st]:
            del self.state_duration[st]
            # v10: 补上'eat'——喂食(duration=6.56)到期后旧代码不转idle，
            #      狗一直循环吃直到ai_timer偶然到期(最长多卡11秒)
            if st in ('happy', 'roll', 'dance', 'bark', 'lick', 'stretch', 'beg', 'bath', 'eat'):
                self.set_state('idle')
                return

        if self.dragging:
            return

        # ── 逗弄模式：追鼠标（缓动速度+转身动画）──
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
                    # 靠近光标时缓出减速，距离越远跑得越快
                    target = new_facing * min(165.0, 35.0 + abs(dx) * 0.75)
                    self._integrate_vel(dt, target, 900.0, 1400.0)
            else:
                self._integrate_vel(dt, 0.0, 0.0, 2400.0)
                if st == 'run':
                    self.set_state('idle')
            # 靠近鼠标时冒爱心
            dist = math.hypot(cursor.x() - cx, cursor.y() - (self.y() + self.height() // 2))
            if dist < 150 and random.random() < dt * 2.5:
                self.particles.emit(ParticleSystem.HEART, CANVAS / 2, 80, 1)
            return

        # ── 物理运动中 ──
        if self.physics.active:
            if st != 'surprised':
                self.set_state('surprised')
            return
        if st == 'surprised':
            self.set_state('idle')
            return

        # ── 如厕 ──
        if self.potty_need >= 100 and st not in ('potty_run', 'potty'):
            self.set_state('potty_run')
            edge = random.choice([30, sg.right() - self.width() - 30])
            self.roam_target = edge
            self.say('内急...')
            return

        if st == 'potty_run':
            tx = self.roam_target
            if tx is None:
                # 防御：无目标点时就近选屏幕边缘，避免 None 运算崩溃
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
                self.say('舒服~')
            return

        # ── 睡觉 ──
        if st == 'sleep':
            if (st_time > 10 and self.energy >= 95) or st_time > 40:
                self.set_state('idle')
                self.say('睡醒了!')
            return

        if self.energy < 15 and st == 'idle' and random.random() < dt * 0.5:
            self.set_state('sleep')
            self.say('困了...')
            return

        # ── 自动行为计时器 ──
        self.ai_timer -= dt
        if self.ai_timer > 0:
            # 行走状态持续移动（速度px/s，带缓动）
            if st == 'walk':
                self._do_walk(65.0, dt)
            elif st == 'run':
                self._do_walk(145.0, dt)
            return

        self.ai_timer = random.uniform(4, 11)

        # v10 动作中断根治：限时动作（跳舞/打滚/舔毛/作揖/洗澡/开心跳等）播放期间
        #      不允许AI换动作——旧代码ai_timer(4-11s)可能短于表演时长(dance 7.26s)，
        #      表演中途就被AI强行切走，观感=动作做一半被中断。
        #      到期后由上方"限时状态结束"分支统一转idle，再走正常决策。
        if st in self.state_duration:
            return

        # 选择下一个行为
        r = random.random()
        if self.mode == 'taskbar':
            if r < 0.42:
                self.set_state('walk')
                sg2 = QApplication.primaryScreen().geometry()
                # 贴墙时强制朝空旷一侧走
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
                self.set_state('happy', duration=5.1)
            elif r < 0.66:
                self.set_state('bark', duration=5.1)
            elif r < 0.76:
                self.set_state('lick', duration=4.0)
            elif r < 0.84:
                self.set_state('roll', duration=5.1)
            elif r < 0.92:
                self.set_state('dance', duration=10.3)
            else:
                self.set_state('idle')
        else:  # desktop
            if r < 0.5:
                self.set_state('walk')
                self.roam_target = random.randint(30, sg.right() - self.width() - 30)
            elif r < 0.62:
                self.set_state('happy', duration=5.1)
            elif r < 0.74:
                self.set_state('lick', duration=4.0)
            elif r < 0.84:
                self.set_state('roll', duration=5.1)
            else:
                self.set_state('idle')

    def _do_walk(self, speed, dt):
        sg = QApplication.primaryScreen().geometry()
        if self.mode == 'desktop' and self.roam_target is not None:
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
            # 接近目标时缓出减速（ease-out 靠站）
            cruise = speed
            near_speed = min(cruise, max(22.0, abs(dist) * 1.0))
            self._integrate_vel(dt, new_facing * near_speed, 380.0, 700.0)
        else:
            # 任务栏漫步：边界折返（带转身动画）
            if self.turn_phase is not None:
                self._integrate_vel(dt, 0.0, 0.0, 2600.0)
            else:
                self._integrate_vel(dt, self.walk_dir * speed, 380.0, 700.0)
            x = self.x()
            if x <= 0 and self.walk_dir < 0:
                self.walk_dir = 1
                self._start_turn(1)
                self.ai_timer = 0.0   # 贴墙后立即重新决策，避免撞墙呆站
            elif x >= sg.right() - self.width() and self.walk_dir > 0:
                self.walk_dir = -1
                self._start_turn(-1)
                self.ai_timer = 0.0
            x = max(0, min(self.x(), sg.right() - self.width()))
            if x != self.x():
                self.move(x, self.y())

    # ─────────── 属性 ───────────
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

    # ─────────── 绘制（核心：混合渲染） ───────────
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        # v25 (P9): 统一缩放——全部绘制逻辑保持CANVAS=320逻辑坐标系，
        # 一次scale让精灵(已按zoom预渲染)/粒子/气泡同步缩放
        painter.scale(self.zoom, self.zoom)

        now = time.perf_counter()
        t = now - self.state_started
        dx = CANVAS / 2
        dy = CANVAS - GROUND_PAD  # 脚底锚点

        # ── 计算实时变换 ──
        bob = 0.0          # 垂直浮动
        rot = 0.0          # 旋转（度）
        sx, sy = 1.0, 1.0  # 缩放
        st = self.state
        speed_ratio = 1.0  # 速度占巡航速度的比例（调节步幅幅度）

        if st == 'idle' or st == 'sit':
            # v7: 3D待机动画自带呼吸起伏，程序化浮动已移除（避免"动图悬浮感"）
            pass
        elif st == 'sleep':
            # v7.1: 趴卧帧自带呼吸起伏，不再程序化浮动（避免悬浮感）；保留蹬腿抽搐点缀
            if self.sleep_twitch_t > 0:
                tw = self.sleep_twitch_t
                rot += math.sin(tw * 22) * 1.5 * tw
        elif st in ('walk', 'run', 'potty_run'):
            # v7: 3D步态动画自带弹跳与真实腿部摆动，程序化只保留速度前倾
            rot = max(-3.5, min(3.5, self.vel_x * 0.011))
        elif st == 'happy':
            # v7: Jump_ToIdle动画自带完整跳跃弧线（离地→落地），不再程序化叠加跳跃
            pass
        elif st == 'roll':
            # v7.1: 真3D翻滚已烘焙进帧（Body绕前后轴360°），不再程序化旋转整图
            bob = -3
        elif st == 'dance':
            # v7.1: dance真动画（后腿直立+前爪挥舞）已烘焙进帧，不再叠加程序化旋转浮动
            pass
        elif st == 'eat':
            # v7: Eating动画自带完整低头进食动作，不再叠加程序化晃动
            pass
        elif st == 'bark':
            # v7: Attack动画自带扑咬动作，不再叠加后坐力
            pass
        elif st in ('bath', 'surprised', 'stretch', 'beg', 'lick', 'sit', 'sleep'):
            # v7.1: 真3D动画（甩水/惊跳/伸懒腰/乞食/舔毛/坐下/睡觉）已烘焙进帧
            pass

        # ── 起步预备动作（下蹲蓄力）──
        if self.antic_t > 0:
            p = self.antic_t / 0.18
            sy *= 1.0 - 0.10 * p
            sx *= 1.0 + 0.07 * p
            rot -= self.facing * 3.0 * p
            bob += 2.0 * p

        # ── 急停缓冲（前倾挤压）──
        if self.settle_t > 0:
            p = self.settle_t / 0.28
            rot += self.facing * 4.5 * p
            sy *= 1.0 - 0.05 * p

        # ── 状态切入弹簧（轻微过冲）──
        if self.pop_t > 0:
            p = self.pop_t / 0.16
            o = math.sin(p * math.pi) * 0.03  # v19: 0.07→0.03 压低入场弹簧过冲，避免跳跃帧头顶被推近窗口上沿(P1)
            sx *= 1.0 + o * 0.6
            sy *= 1.0 + o

        # ── v19: 转身X轴压缩已彻底移除——改为竞品(Deskpet Dog)式纯镜像翻转。
        # 用户两次点名批评X轴压扁为"卡片翻转"；turn_scale()已废弃(恒返回1.0) ──

        # ── 待机微动作 ──
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

        # ── 落地挤压（物理）──
        if self.physics.squash > 0:
            sq = self.physics.squash
            sx *= 1.0 + sq * 0.18
            sy *= 1.0 - sq * 0.22

        # ── 拖拽倾斜 ──
        if self.dragging and len(self.mouse_hist) >= 2:
            (t0, x0, _), (t1, x1, _) = self.mouse_hist[0], self.mouse_hist[-1]
            if t1 > t0:
                vx = (x1 - x0) / (t1 - t0)
                rot += max(-8, min(8, vx * 0.012))  # ±8°内不超出窗口余量，避免旋转裁切

        # ── 图像获取（v25 P2: 动态投影已删除——用户明确要求去掉所有底部影子）──
        img = self.bank.get(self.state, self.frame_idx, self.flipped)
        if img.isNull():
            painter.end()
            return

        # ── 应用变换绘制 ──
        painter.save()
        painter.translate(dx, dy + bob)
        if rot:
            painter.rotate(rot)
        painter.scale(sx, sy)

        # v64: 脚底锚定比例绘制——tight资产按帧自身w/h等比绘制（画布高=union高，
        # 帧内无脉动；calm六态基准统一，状态切换无跳变）。
        # k换算使屏上逻辑尺寸与v63方画布路径逐像素等价：
        #   tight: 纹理长边=draw×max(w,h)/1024×1.05 → k=DRAW_SIZE/(draw×1.05)，
        #          屏上高=纹理高×k=h/1024×DRAW_SIZE（1.05纹理过采样不影响几何）
        #   方画布(walk认可版): k=DRAW_SIZE/draw，与v63的DRAW_SIZE方rect完全一致
        _owner = self.bank.alias.get(self.state, self.state)
        if _owner in self.bank.TIGHT:
            k = DRAW_SIZE / (self.bank.draw_size * self.bank.ASSET_SCALE)
        else:
            k = DRAW_SIZE / max(96, min(self.bank.draw_size, 1024))
        # v73: 主体视觉尺寸补偿（见 SpriteBank.SIZE_COMP 注释）
        k *= self.bank.SIZE_COMP.get(_owner, 1.0)
        _iw, _ih = img.width(), img.height()
        draw_rect = QRectF(-_iw * k / 2, -_ih * k + GROUND_PAD, _iw * k, _ih * k)
        # ── 腿部装配渲染（Paper-Doll Rig）：真实迈步摆动 ──
        # v19: 素材腿部冻结，运行时把精灵拆成 后腿→身体→前腿 三层，
        # 绕髋关节钟摆摆动产生真实步态。rig为逐帧列表（跟随frame_idx）。
        rig_list = (self.bank.rig_parts_m if self.flipped
                    else self.bank.rig_parts).get(st)
        rig = rig_list[self.frame_idx % len(rig_list)] if rig_list else None
        if rig is not None and self.leg_amp > 0.01:
            top_y = -DRAW_SIZE + GROUND_PAD
            amp = rig['amp_deg'] * self.leg_amp
            swing_f = math.sin(self.leg_phase) * amp   # 前腿
            swing_r = -swing_f                          # 后腿反相（小跑步态）
            # 1) 后腿（最先画，位于身体后方）
            rp, (rpx, rpy) = rig['rear'], rig['rear_pivot']
            painter.save()
            painter.translate(rig['rear_x0'] - DRAW_SIZE / 2 + rpx,
                              top_y + rig['leg_y0'] + rpy)
            painter.rotate(swing_r)
            painter.drawImage(QRectF(-rpx, -rpy, rp.width(), rp.height()), rp)
            painter.restore()
            # 2) 身体（覆盖髋部接缝）
            body = rig['body']
            painter.drawImage(QRectF(-DRAW_SIZE / 2, top_y,
                                     DRAW_SIZE, body.height()), body)
            # 3) 前腿（最后画，位于身体前方）
            fp, (fpx, fpy) = rig['front'], rig['front_pivot']
            painter.save()
            painter.translate(rig['front_x0'] - DRAW_SIZE / 2 + fpx,
                              top_y + rig['leg_y0'] + fpy)
            painter.rotate(swing_f)
            painter.drawImage(QRectF(-fpx, -fpy, fp.width(), fp.height()), fp)
            painter.restore()
        else:
            painter.drawImage(draw_rect, img)

        # ── 呼吸层叠加：v7已禁用 ──
        # 3D骨骼动画自带真实胸腔起伏，旧2D素材的胸部区域坐标对3D模型错位，
        # 叠加反而产生贴图撕裂感。此处保留注释说明移除原因。

        painter.restore()

        # ── 粒子 ──
        self.particles.draw(painter)
        self._last_drawn = (self.state, self.frame_idx, self.flipped)  # v66 跳绘标记
        painter.end()

    # ─────────── 交互 ───────────
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
                self.say('抓到我了!')
            else:
                self.set_state('surprised')

    def mouseMoveEvent(self, event):
        if self.dragging:
            now = time.perf_counter()
            gp = event.globalPos()
            self.mouse_hist.append((now, gp.x(), gp.y()))
            self.mouse_hist = [h for h in self.mouse_hist if now - h[0] < 0.12]
            # 拖拽限制在屏幕内：旧代码可拖出屏幕→头/尾被屏幕边缘裁掉
            sg = QApplication.primaryScreen().geometry()
            nx = max(0, min(gp.x() - self.drag_off.x(), sg.right() - self.width()))
            ny = max(0, min(gp.y() - self.drag_off.y(), sg.bottom() - self.height()))
            self.move(nx, ny)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.dragging:
            self.dragging = False
            # 计算抛掷速度
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
        # 各绝活时长对齐循环周期整数倍（happy为一次性），避免结束中途硬切
        self.set_state(trick, duration={'happy': 5.1, 'roll': 5.1,
                                        'dance': 10.3, 'bark': 5.1}[trick])
        self.happiness = min(100, self.happiness + 6)

    def contextMenuEvent(self, event):
        # v67: 自绘圆角菜单——macOS 下 QMenu+border-radius 圆角外渲染白底，
        # QPainterPath 自绘 popup 与主窗口同机制，Windows/macOS 像素级一致。
        menu = RoundedMenu(self)

        tease_key = 'tease'
        menu.add_item(tease_key, '🐾 退出逗弄' if self.mode == 'tease' else '🐾 逗逗我')
        menu.add_sep()
        menu.add_item('feed', '🍖 喂食')
        menu.add_item('pet', '🤚 摸摸头')
        menu.add_sep()
        trick_menu = RoundedMenu(self)
        trick_menu.add_item('happy', '开心跳跃')
        trick_menu.add_item('roll', '打滚')
        trick_menu.add_item('dance', '跳舞')
        trick_menu.add_item('bark', '叫一声')
        trick_menu.add_item('lick', '舔毛')
        trick_menu.add_item('beg', '作揖')
        trick_menu.add_item('bath', '洗澡')
        menu.add_sub('🎪 表演', trick_menu)
        menu.add_sep()
        size_menu = RoundedMenu(self)
        size_menu.add_item('zoom_up', '➕ 放大')
        size_menu.add_item('zoom_down', '➖ 缩小')
        size_menu.add_item('zoom_reset', '↩ 重置')
        menu.add_sub('🔍 大小', size_menu)
        menu.add_sep()
        mode_menu = RoundedMenu(self)
        mode_menu.add_item('mode_taskbar', '任务栏漫步')
        mode_menu.add_item('mode_desktop', '桌面漫游')
        menu.add_sub('📍 模式', mode_menu)
        menu.add_sep()
        menu.add_item('sleep', '💤 去睡觉')
        menu.add_item('stats', '📊 查看状态')
        menu.add_sep()
        menu.add_item('quit', '❌ 退出')

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
                self.say('来抓我呀!')
        elif action == 'feed':
            self.set_state('eat', duration=6.56)
            self.fullness = min(100, self.fullness + 20)
            self.happiness = min(100, self.happiness + 5)
        elif action == 'pet':
            self.happiness = min(100, self.happiness + 10)
            # v57: 摸摸头=独立pet互动(人手抚摸+小狗享受)，与舔毛lick区分
            self.set_state('pet', duration=4.6)
        elif action == 'happy':
            self.set_state('happy', duration=5.1)
        elif action == 'roll':
            self.set_state('roll', duration=5.1)
        elif action == 'dance':
            self.set_state('dance', duration=10.3)
        elif action == 'bark':
            self.set_state('bark', duration=5.1)
        elif action == 'lick':
            self.set_state('lick', duration=4.0)
        elif action == 'beg':
            self.set_state('beg', duration=5.1)
        elif action == 'bath':
            self.set_state('bath', duration=10.3)
        elif action == 'mode_taskbar':
            self.mode = 'taskbar'
            sg = QApplication.primaryScreen().geometry()
            self.floor_y = sg.bottom() - self.height() - 45
            self.move(self.x(), self.floor_y)
            self.set_state('idle')
        elif action == 'mode_desktop':
            self.mode = 'desktop'
            self.set_state('idle')
            self.say('自由啦!')
        elif action == 'zoom_up':
            self.set_zoom(self.zoom + ZOOM_STEP)
            self.say(f'大小 {self.zoom:.2f}x')
        elif action == 'zoom_down':
            self.set_zoom(self.zoom - ZOOM_STEP)
            self.say(f'大小 {self.zoom:.2f}x')
        elif action == 'zoom_reset':
            self.set_zoom(ZOOM_DEFAULT)
            self.say('恢复默认大小')
        elif action == 'sleep':
            self.set_state('sleep')
        elif action == 'stats':
            self.say(f'饱食{int(self.fullness)} 开心{int(self.happiness)} '
                      f'精力{int(self.energy)}')
            self.particles.emit(ParticleSystem.SPARKLE, CANVAS / 2, 70, 4)
        elif action == 'quit':
            QApplication.quit()


def _install_excepthook():
    """打包后（console=False）没有stderr，异常必须写日志，否则静默死亡"""
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


_pet_window = None  # 必须全局持有引用，防止窗口被GC销毁
_singleton_mutex = None  # 必须全局持有，防止互斥锁被GC提前释放


def _acquire_single_instance():
    """Windows命名互斥锁：防止用户双击多次导致多只金毛犬/僵尸进程"""
    if sys.platform != 'win32':
        return True
    import ctypes
    kernel32 = ctypes.windll.kernel32
    global _singleton_mutex
    _singleton_mutex = kernel32.CreateMutexW(None, False, PET_NAME_ASCII + '_V1_Singleton')
    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return False  # 已有实例在运行
    return True


def _find_existing_window():
    """枚举顶层窗口找宠物窗口：优先精确标题，其次匹配历史版本标题前缀。
    （旧版本EXE的窗口标题是PyInstaller按EXE名设置的"金毛犬桌面宠物vN"）"""
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
            if buf.value.startswith(PET_NAME):  # 从CONFIG派生：匹配本宠物EXE窗口标题前缀
                found.append(hwnd)
        return True

    user32.EnumWindows(_cb, 0)
    return found[0] if found else 0


def _activate_existing_instance():
    """已有实例在运行时：把它的窗口带到前台，让用户看到"宠物已在运行"。
    旧版直接静默退出 → 用户双击毫无反馈，以为程序坏了。"""
    if sys.platform != 'win32':
        return
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = _find_existing_window()
    if not hwnd:
        return
    SW_RESTORE = 9          # 若被最小化则还原
    SW_SHOWNOACTIVATE = 4   # 显示但不抢焦点（宠物窗口本来就不激活）
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
    # 置顶窗口（WindowStaysOnTopHint）可能被其他置顶窗口压住，
    # SetForegroundWindow 对非前台进程受限，用 AttachThreadInput 提权
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
    """v66-fix: 用 SendMessageTimeout(SMTO_ABORTIFHUNG) 探测旧实例消息队列是否存活。
    旧实例事件循环卡死（僵尸）时该调用立即失败返回，不会阻塞本进程。"""
    import ctypes
    SMTO_ABORTIFHUNG = 0x0002
    result = ctypes.c_long()
    ok = ctypes.windll.user32.SendMessageTimeoutW(
        int(hwnd), 0x0000, 0, 0, SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(result))
    return bool(ok)


def _kill_process_of_hwnd(hwnd):
    """v66-fix: 终止僵死旧实例进程（释放单例锁），不碰本进程"""
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
    """v66-fix: 关闭本进程持有的mutex句柄。
    内核mutex对象在所有句柄关闭后才销毁——若不先关自己的首次句柄，
    杀死旧进程后第二次CreateMutexW仍返回ALREADY_EXISTS（误判接管失败）。"""
    global _singleton_mutex
    if _singleton_mutex:
        import ctypes
        ctypes.windll.kernel32.CloseHandle(_singleton_mutex)
        _singleton_mutex = None


def main():
    global _pet_window
    _install_excepthook()
    # v69-fix: C 级崩溃（Qt C++ abort/段错误/栈溢出）不经过 excepthook、不留任何日志，
    # 进程"静默消失"。faulthandler 注册原生信号处理，把 traceback 写进 crash.log，
    # 下次再复现即可定位。句柄全局持有防GC。
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
        # v66-fix: 旧实例存在时先探活——响应正常才"激活已有窗口"；
        # 僵死（事件循环卡死）则终止旧进程接管启动，
        # 根治"新EXE永远只激活僵死旧窗口、用户看到狗不动"的死循环。
        hwnd = _find_existing_window()
        if hwnd and _is_window_responsive(hwnd):
            _activate_existing_instance()
            return
        took_over = False
        if hwnd and _kill_process_of_hwnd(hwnd):
            time.sleep(0.6)  # 等旧进程释放mutex
            _release_singleton_mutex()  # 关本进程句柄，内核对象才销毁
            took_over = _acquire_single_instance()
        if not took_over:
            _activate_existing_instance()
            return
    # 高DPI支持：必须在QApplication创建前设置
    # v49-fix: PassThrough 舍入策略——用监视器真实缩放(如1.5x)，不做整数舍入。
    # 根治 Windows 高缩放下"后缓冲尺寸≠物理窗口尺寸"的合成错位（黑屏/狗碎片）：
    # 默认Round把1.5x舍入成2.0，后缓冲640px被合成进~427px窗口→裁切+偏移。
    # (实测本机不支持SetProcessDpiAwarenessContext，err=87，勿再加原生DPI调用)
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
