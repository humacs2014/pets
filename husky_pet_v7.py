#!/usr/bin/env python3
"""
哈士奇桌面宠物 v6.0 — 混合渲染引擎（竞品同款技术路线）
=========================================================
核心原理（与竞品Deskpet Dog完全一致）：
  1. 原版哈士奇精灵图作为基底（保留原版神韵）
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

from PyQt5.QtWidgets import QApplication, QWidget, QMenu
from PyQt5.QtCore import Qt, QTimer, QPoint, QPointF, QRectF, QRect
from PyQt5.QtGui import (
    QPainter, QPen, QBrush, QColor, QPainterPath, QFont, QFontMetrics,
    QImage, QCursor, QRadialGradient, QLinearGradient
)

# 跨平台中文字体：macOS无微软雅黑，回退到苹方
_UI_FONT = 'PingFang SC' if sys.platform == 'darwin' else 'Microsoft YaHei'


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
    # v8: Agnes AI视频抽帧+乒乓烘焙帧序列。
    #   intro_frames=进入姿态帧数（坐下/躺下），只播一次后循环主体段；
    #   往复动作已烘焙正放+倒放（pingpong），正向循环即无缝。
    'idle':      ('idle',      26, 164, True,  0),
    # v22: walk/run恢复为你认可的v13帧(v11帧walk/run 8帧)——v21误用了v17备份帧
    #      (14/10帧gallop素材+rig钟摆)导致步态观感与认可版不符。
    #      v13字节码实测: ANIMS walk=11帧/run=8帧, LEG_RIG=空字典(纯帧播放无rig)。
    #      帧数必须与assets实际文件数一致，否则frame_idx%count与实际帧数错位→节奏性卡顿
    'walk':      ('walk',      11, 110, True,  0),
    'run':       ('run',       8,  100, True,  0),
    'eat':       ('eat',       20, 164, True,  0),
    'bark':      ('bark',      20, 120, True,  0),
    'sleep':     ('sleep',     48, 110, True,  39),
    'sit':       ('sit',       24, 110, True,  8),
    'lick':      ('lick',      20, 120, True,  0),
    # v21c: happy按v20视频f61-f120重抽26帧(405px站立高+70px跳幅,与其他状态一致),
    #       lift封顶由窗口底边烘焙保证,跳峰不裁切
    'happy':     ('happy',     26, 100, False, 0),
    'roll':      ('roll',      26, 110, True,  0),
    'dance':     ('dance',     22, 110, True,  0),
    'stretch':   ('stretch',   49, 100, False, 0),
    'beg':       ('beg',       20, 120, True,  0),
    'bath':      ('bath',      20, 120, True,  0),
    'surprised': ('surprised', 17, 110, False, 0),
    'play_dead': ('play_dead', 26, 110, False, 0),
    'potty_run': ('run',       8,  100, True,  0),  # v22: 复用run帧，帧数必须与run一致(8)
    'potty':     ('sit',       24, 110, True,  8),
}

# 朝向左的状态（素材本身朝左，向右移动时需镜像）
LEFT_FACING = {'walk', 'run'}

CANVAS = 320          # 窗口尺寸（320>250+挤压/旋转溢出余量，杜绝变换裁切）
DRAW_SIZE = 250       # 精灵绘制尺寸
GROUND_PAD = 14       # 脚底留白

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
class SpriteBank:
    def __init__(self):
        self.frames = {}     # state -> [QImage正常]
        self.frames_m = {}   # state -> [QImage镜像]
        # 腿部装配部件：state -> dict(body/front/rear 各 [QImage正常, QImage镜像])
        self.rig_parts = {}
        self.rig_parts_m = {}
        self.lift_map = {}   # state -> [每帧离地高度 0..1]（跳跃弧线联动阴影）

    def load(self):
        base = asset_path()
        for state, (prefix, count, _, _, _i) in ANIMS.items():
            imgs, imgs_m = [], []
            for i in range(count):
                fn = os.path.join(base, f'{prefix}_{i:02d}.png')
                img = QImage(fn)
                if img.isNull():
                    continue
                img = img.convertToFormat(QImage.Format_ARGB32)
                # 缩放到目标尺寸（双线性平滑）
                img = img.scaled(DRAW_SIZE, DRAW_SIZE,
                                  Qt.KeepAspectRatio, Qt.SmoothTransformation)
                imgs.append(img)
                # 预生成镜像版本
                imgs_m.append(img.mirrored(True, False))
            # v11: 帧水平居中——根治'超出边框'。walk素材内容贴左缘(L=0)、质心偏-44px，
            # 镜像后狗头顶到窗口右缘；帧间质心漂移还导致左右晃动。用全序列平均质心统一平移。
            imgs = self._center_frames(imgs)
            imgs_m = self._center_frames(imgs_m)
            self.frames[state] = imgs
            self.frames_m[state] = imgs_m
            # ── 每帧离地高度：内容包围盒底边相对全序列最大底边的抬升（归一化0..1）──
            # 纯Python抽样扫描：从底向上逐行、每8列取一点（脚底通常前几行即命中）
            bottoms = []
            for im in imgs:
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
                bottoms.append(bottom)
            if bottoms:
                ground = max(bottoms)
                var = ground - min(bottoms)
                # 阴影闪烁根因：腿姿态/呼吸引起的底边小幅抖动(<30px)不是真跳跃，
                # 旧代码用 max(6.0, var) 归一化会把12px抬腿放大成100%离地→阴影每步收缩45%。
                # 变差<30px 视为贴地，lift恒为0；仅真跳跃状态(run/jump/stretch等)保留阴影联动。
                if var < 30:
                    self.lift_map[state] = [0.0 for _ in bottoms]
                else:
                    span = float(var)
                    self.lift_map[state] = [
                        max(0.0, min(1.0, (ground - b) / span)) for b in bottoms]
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

    @staticmethod
    def _body_bottom(img):
        """内容底缘上方第一个'宽行'(>62%最大行宽)的行号=身体底缘；无内容返回None"""
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
            return None
        rows = [y for y in range(h) if row_w[y] > 0]
        bot = rows[-1]
        for y in range(bot, -1, -1):
            if row_w[y] > max_w * 0.62:
                return y
        return bot

    @staticmethod
    def _content_centroid_x(img):
        """内容(alpha>24)的水平质心x；无内容返回None"""
        w, h = img.width(), img.height()
        buf = img.constBits()
        buf.setsize(img.byteCount())
        data = bytes(buf)
        bpl = img.bytesPerLine()
        sum_x, cnt = 0.0, 0
        for y in range(h):
            rowbase = y * bpl + 3  # ARGB32 的 alpha 通道
            for x in range(w):
                if data[rowbase + x * 4] > 24:
                    sum_x += x
                    cnt += 1
        return sum_x / cnt if cnt else None

    @staticmethod
    def _center_frames(imgs):
        """v11 帧水平居中：整序列共享偏移，根治'超出边框'。
        根因：walk帧内容贴素材左缘(左边距=0)、质心偏-44px，镜像后狗头顶窗口边缘；
        且帧间质心漂移导致左右晃动。用全序列平均质心做统一平移——
        既让狗在窗口内居中，又消除帧间水平抖动。"""
        cxs = [c for c in (SpriteBank._content_centroid_x(im) for im in imgs) if c is not None]
        if not cxs:
            return imgs
        shift = int(round(DRAW_SIZE / 2 - sum(cxs) / len(cxs)))
        if shift == 0:
            return imgs
        out = []
        for im in imgs:
            canvas = QImage(DRAW_SIZE, DRAW_SIZE, QImage.Format_ARGB32)
            canvas.fill(Qt.transparent)
            p = QPainter(canvas)
            p.drawImage(shift, 0, im)
            p.end()
            out.append(canvas)
        return out

    @staticmethod
    def _cut_rig(img, geo, mirrored=False):
        """把精灵切成 身体/前腿/后腿 三块（带接缝渐隐）
        mirrored=True 时输入为镜像图：分割线镜像，部件按解剖学归属命名"""
        # 规范化到250x250画布(水平居中/底部对齐)，与离线烘焙几何严格对齐
        canvas = QImage(DRAW_SIZE, DRAW_SIZE, QImage.Format_ARGB32)
        canvas.fill(Qt.transparent)
        cp = QPainter(canvas)
        cp.drawImage((DRAW_SIZE - img.width()) // 2,
                     DRAW_SIZE - img.height(), img)
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
        bank = self.frames_m[state] if flipped else self.frames[state]
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
WINDOW_TITLE = 'HuskyDesktopPet_MainWindow'  # 固定窗口标题：供重复启动的新实例FindWindow定位并激活


class PetWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(CANVAS, CANVAS)

        self.bank = SpriteBank()
        self.bank.load()
        self.particles = ParticleSystem()
        self.physics = Physics()

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

        # 初始位置：屏幕底部
        sg = QApplication.primaryScreen().geometry()
        self.floor_y = sg.bottom() - CANVAS - 45
        self.move(sg.center().x() - CANVAS // 2, self.floor_y)

        self.last_t = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)  # Windows默认定时器抖动15-31ms，精确模式减少帧间隔波动
        self.timer.timeout.connect(self.game_loop)
        self.timer.start(16)
        self.show()

    # ─────────── 状态切换 ───────────
    def set_state(self, s, duration=None):
        if s not in ANIMS:
            return
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
            self.particles.emit(ParticleSystem.BUBBLE, CANVAS / 2, 60, 1, text='汪!')
        elif s == 'happy':
            self.particles.emit(ParticleSystem.HEART, CANVAS / 2, 90, 4)
        elif s == 'eat':
            self.say('好吃!')

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
            lo, hi = sg.left(), sg.right() - CANVAS
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
            self.flipped = self.facing > 0
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
        lift_seq = self.bank.lift_map.get(self.state)
        if lift_seq:
            raw_air = lift_seq[self.frame_idx % len(lift_seq)]
        else:
            raw_air = 0.0
        self.smooth_air += (raw_air - self.smooth_air) * min(1.0, dt / 0.09)
        self.update_ai(dt)
        impact = self.physics.update(dt, self, self.floor_y, 0,
                                      QApplication.primaryScreen().geometry().right() - CANVAS)
        if impact > 200:
            self.particles.emit(ParticleSystem.DUST, CANVAS / 2, CANVAS - GROUND_PAD, 4)

        self.particles.update(dt)
        self.update_stats(dt)
        self.emit_state_particles(dt)
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
            cx = self.x() + CANVAS // 2
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
            dist = math.hypot(cursor.x() - cx, cursor.y() - (self.y() + CANVAS // 2))
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
            edge = random.choice([30, sg.right() - CANVAS - 30])
            self.roam_target = edge
            self.say('内急...')
            return

        if st == 'potty_run':
            tx = self.roam_target
            if tx is None:
                # 防御：无目标点时就近选屏幕边缘，避免 None 运算崩溃
                tx = self.roam_target = random.choice([30, sg.right() - CANVAS - 30])
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
            if self.energy >= 95 or st_time > 40:
                self.set_state('stretch', duration=4.9)
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
                elif self.x() > sg2.right() - CANVAS - 120:
                    self.walk_dir = -1
                else:
                    self.walk_dir = random.choice([-1, 1])
                self._start_turn(self.walk_dir)
                if self.turn_phase is None:
                    self.facing = self.walk_dir
                    self.flipped = self.facing > 0
            elif r < 0.55:
                self.set_state('happy', duration=3.3)
            elif r < 0.66:
                self.set_state('bark', duration=2.4)
            elif r < 0.76:
                self.set_state('lick', duration=4.8)
            elif r < 0.84:
                self.set_state('roll', duration=5.72)
            elif r < 0.92:
                self.set_state('dance', duration=7.26)
            else:
                self.set_state('idle')
        else:  # desktop
            if r < 0.5:
                self.set_state('walk')
                self.roam_target = random.randint(30, sg.right() - CANVAS - 30)
            elif r < 0.62:
                self.set_state('happy', duration=3.3)
            elif r < 0.74:
                self.set_state('lick', duration=4.8)
            elif r < 0.84:
                self.set_state('roll', duration=5.72)
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
            elif x >= sg.right() - CANVAS and self.walk_dir > 0:
                self.walk_dir = -1
                self._start_turn(-1)
                self.ai_timer = 0.0
            x = max(0, min(self.x(), sg.right() - CANVAS))
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

        # ── 动态投影（离地越高影子越小越淡——强化跳跃/悬浮的真实感）──
        img = self.bank.get(self.state, self.frame_idx, self.flipped)
        if img.isNull():
            painter.end()
            return
        # v9: 阴影恒绘制（旧代码拖拽/物理时直接隐藏→"一会儿有一会儿没有"）；
        # 离地高度用game_loop里的平滑值，消除帧间跳动引起的闪烁
        lift_seq = self.bank.lift_map.get(self.state)
        air = self.smooth_air if lift_seq else max(0.0, min(1.0, -bob / 14.0))
        sh_w = DRAW_SIZE * 0.46 * (1.0 - air * 0.45) * sx
        sh_a = int(72 * (1.0 - air * 0.55))
        if self.physics.active or self.dragging:
            sh_a = max(18, sh_a // 2)   # 空中/拖拽时影子变淡但保持可见
        grad = QRadialGradient(dx, CANVAS - 7, sh_w / 2)
        grad.setColorAt(0.0, QColor(30, 30, 45, sh_a))
        grad.setColorAt(0.7, QColor(30, 30, 45, int(sh_a * 0.45)))
        grad.setColorAt(1.0, QColor(30, 30, 45, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(grad))
        painter.drawEllipse(QPointF(dx, CANVAS - 7), sh_w / 2, sh_w * 0.11)

        # ── 应用变换绘制 ──
        painter.save()
        painter.translate(dx, dy + bob)
        if rot:
            painter.rotate(rot)
        painter.scale(sx, sy)

        draw_rect = QRectF(-DRAW_SIZE / 2, -DRAW_SIZE + GROUND_PAD,
                            DRAW_SIZE, DRAW_SIZE)
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
                self.floor_y = sg.bottom() - CANVAS - 45
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
            nx = max(0, min(gp.x() - self.drag_off.x(), sg.right() - CANVAS))
            ny = max(0, min(gp.y() - self.drag_off.y(), sg.bottom() - CANVAS))
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
        self.set_state(trick, duration={'happy': 3.3, 'roll': 5.72,
                                        'dance': 7.26, 'bark': 2.4}[trick])
        self.happiness = min(100, self.happiness + 6)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background:#2b2b3a; color:#e8e8f0; border:1px solid #45455c;
                    border-radius:8px; padding:6px; font-size:13px;
                    font-family:'%s'; }
            QMenu::item { padding:8px 26px; border-radius:5px; }
            QMenu::item:selected { background:#4a4a6e; }
            QMenu::separator { height:1px; background:#45455c; margin:4px 10px; }
        """ % _UI_FONT)

        a_tease = menu.addAction('🐾 退出逗弄' if self.mode == 'tease' else '🐾 逗逗我')
        menu.addSeparator()
        a_feed = menu.addAction('🍖 喂食')
        a_pet = menu.addAction('🤚 摸摸头')
        menu.addSeparator()
        trick_menu = menu.addMenu('🎪 表演')
        t_happy = trick_menu.addAction('开心跳跃')
        t_roll = trick_menu.addAction('打滚')
        t_dance = trick_menu.addAction('跳舞')
        t_bark = trick_menu.addAction('叫一声')
        t_lick = trick_menu.addAction('舔毛')
        t_beg = trick_menu.addAction('作揖')
        t_bath = trick_menu.addAction('洗澡')
        menu.addSeparator()
        mode_menu = menu.addMenu('📍 模式')
        m_taskbar = mode_menu.addAction('任务栏漫步')
        m_desktop = mode_menu.addAction('桌面漫游')
        menu.addSeparator()
        a_sleep = menu.addAction('💤 去睡觉')
        a_stats = menu.addAction('📊 查看状态')
        menu.addSeparator()
        a_quit = menu.addAction('❌ 退出')

        action = menu.exec_(event.globalPos())
        if action is None:
            return

        if action == a_tease:
            if self.mode == 'tease':
                self.mode = 'taskbar'
                sg = QApplication.primaryScreen().geometry()
                self.floor_y = sg.bottom() - CANVAS - 45
                self.set_state('idle')
            else:
                self.mode = 'tease'
                self.set_state('run')
                self.say('来抓我呀!')
        elif action == a_feed:
            self.set_state('eat', duration=6.56)
            self.fullness = min(100, self.fullness + 20)
            self.happiness = min(100, self.happiness + 5)
        elif action == a_pet:
            self.happiness = min(100, self.happiness + 10)
            self.set_state('happy', duration=3.3)
        elif action == t_happy:
            self.set_state('happy', duration=3.3)
        elif action == t_roll:
            self.set_state('roll', duration=5.72)
        elif action == t_dance:
            self.set_state('dance', duration=7.26)
        elif action == t_bark:
            self.set_state('bark', duration=2.4)
        elif action == t_lick:
            self.set_state('lick', duration=4.8)
        elif action == t_beg:
            self.set_state('beg', duration=7.2)
        elif action == t_bath:
            self.set_state('bath', duration=9.6)
        elif action == m_taskbar:
            self.mode = 'taskbar'
            sg = QApplication.primaryScreen().geometry()
            self.floor_y = sg.bottom() - CANVAS - 45
            self.move(self.x(), self.floor_y)
            self.set_state('idle')
        elif action == m_desktop:
            self.mode = 'desktop'
            self.set_state('idle')
            self.say('自由啦!')
        elif action == a_sleep:
            self.set_state('sleep')
        elif action == a_stats:
            self.say(f'饱食{int(self.fullness)} 开心{int(self.happiness)} '
                      f'精力{int(self.energy)}')
            self.particles.emit(ParticleSystem.SPARKLE, CANVAS / 2, 70, 4)
        elif action == a_quit:
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
    """Windows命名互斥锁：防止用户双击多次导致多只哈士奇/僵尸进程"""
    if sys.platform != 'win32':
        return True
    import ctypes
    kernel32 = ctypes.windll.kernel32
    global _singleton_mutex
    _singleton_mutex = kernel32.CreateMutexW(None, False, 'HuskyDesktopPetV7_Singleton')
    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return False  # 已有实例在运行
    return True


def _find_existing_window():
    """枚举顶层窗口找宠物窗口：优先精确标题，其次匹配历史版本标题前缀。
    （旧版本EXE的窗口标题是PyInstaller按EXE名设置的"哈士奇桌面宠物vN"）"""
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
            if buf.value.startswith('哈士奇桌面宠物'):
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


def main():
    global _pet_window
    _install_excepthook()
    if not _acquire_single_instance():
        _activate_existing_instance()  # 不再静默退出：激活已有窗口给用户反馈
        return
    # 高DPI支持：必须在QApplication创建前设置
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    _pet_window = PetWindow()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
