# -*- coding: utf-8 -*-
"""v65 重烘焙：修三个用户点名问题（不改引擎几何路径）。
① dance/beg/pet 狗体偏小 → 按状态mult放大（地底锚定，union等比）
   dance/beg: 两腿站高度应≈sit(621)而非≈idle(546) → mult 1.15
   pet: 狗体(排除人手)528.9 vs sit 621.1 → mult 1.17
② bath 泡沫区阴影灰团时隐时现 → 低饱和不透明灰(lum 130-228, sat<0.12)白化为泡沫白
③ eat f00 红碗缺失(循环起点闪空) → 从f01复制碗区(red mask膨胀)
几何沿用 rebake_v64b：质心居中+v63底边距，OUT=assets_v64(覆盖)→deploy转webp。
"""
import glob, os, math
import numpy as np
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, 'frames')
BAK = os.path.join(BASE, 'assets_v63bak')
OUT = os.path.join(BASE, 'assets_v64')

MULT = {'dance': 1.15, 'beg': 1.15, 'pet': 1.17}

ANIMS = {
    'idle': ('idle', 101), 'run': ('run', 15), 'eat': ('eat', 34),
    'bark': ('bark', 57), 'sleep': ('sleep', 51), 'sit': ('sit', 63),
    'lick': ('lick', 54), 'happy': ('happy', 121), 'roll': ('roll', 121),
    'dance': ('dance', 57), 'stretch': ('stretch', 117), 'beg': ('beg', 56),
    'bath': ('bath', 57), 'surprised': ('surprised', 45),
    'play_dead': ('play_dead', 68), 'pet': ('pet', 107),
}
os.makedirs(OUT, exist_ok=True)


def _bbox_arr(a, thresh=24):
    al = a[:, :, 3]
    ys, xs = np.where(al > thresh)
    return xs.min(), ys.min(), xs.max(), ys.max()


def v63_bottom_margin(prefix):
    mx = 0
    for p in sorted(glob.glob(os.path.join(BAK, f'{prefix}_*.webp'))):
        a = np.array(Image.open(p).convert('RGBA'))
        _x0, y0, _x1, y1 = _bbox_arr(a)
        mx = max(mx, y1)
    return 1024 - 1 - mx


def fix_bath_shadows(a):
    """泡沫阴影→泡沫白（v4 纯局部规则，零毛发风险）：
    A. 低饱和浅灰(lum 120-238, sat<0.15, 含半透明) → 白化(灰团/灰帽)
    B. 暗描边(lum<120, sat<0.35)且1px邻接纯白泡沫 → 白化(泡沫描边线；眼鼻不邻接泡沫)
    C. 残余小域(<200px, 不邻接泡沫) → 透明化(浮尘)
    """
    from scipy import ndimage
    rgb = a[:, :, :3].astype(np.int32)
    mx = rgb.max(2)
    mn = rgb.min(2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(1, mx), 0)
    lum = rgb.mean(2)
    anyal = a[:, :, 3] > 10
    foam = anyal & (sat < 0.12) & (lum > 240)
    d = foam.copy()
    d[1:, :] |= foam[:-1, :]
    d[:-1, :] |= foam[1:, :]
    d[:, 1:] |= foam[:, :-1]
    d[:, :-1] |= foam[:, 1:]
    mA = anyal & (sat < 0.15) & (lum >= 90) & (lum < 238)
    mB = anyal & d & (sat < 0.35) & (lum < 120)
    mD = (a[:, :, 3] > 10) & (a[:, :, 3] < 200) & (sat < 0.20) & (lum < 240)
    m = mA | mB
    a[m, 0] = 252
    a[m, 1] = 252
    a[m, 2] = 252
    a[m, 3] = 255
    a[mD & ~m, 3] = 0
    # C 浮尘
    rest = anyal & ~m & (sat < 0.35) & (lum < 238) & ~d
    lab, nl = ndimage.label(rest)
    killed = 0
    if nl:
        for k in range(1, nl + 1):
            comp = lab == k
            if comp.sum() < 200:
                a[comp, 3] = 0
                killed += int(comp.sum())
    return int(m.sum()) + killed


def fix_eat_bowl(frames):
    """碗尺寸逐帧跳变(循环边界f00/f01/f33碗整体缩小) → 用f20标准碗统一：
    M20 = f20红碗mask + 碗口内食物白(红mask膨胀内) ，闭运算补狗头遮挡缝；
    目标帧先清除自身旧碗(红mask膨胀2)，再贴M20(膨胀1含抗锯齿边)。"""
    h = frames[0].shape[0]
    yb = int(h * 0.60)

    def redmask(a):
        R, G, B = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
        m = (a[:, :, 3] > 127) & (R > 140) & (R - G > 70) & (R - B > 70)
        m[:yb, :] = False
        return m

    def dil(m, k):
        for _ in range(k):
            m2 = m.copy()
            m2[1:, :] |= m[:-1, :]
            m2[:-1, :] |= m[1:, :]
            m2[:, 1:] |= m[:, :-1]
            m2[:, :-1] |= m[:, 1:]
            m = m2
        return m

    f20 = frames[20]
    R20 = redmask(f20)
    rgb = f20[:, :, :3].astype(int)
    sat20 = (rgb.max(2) - rgb.min(2)) / np.maximum(1, rgb.max(2))
    lum20 = rgb.mean(2)
    food = (f20[:, :, 3] > 127) & (sat20 < 0.18) & (lum20 > 190) & dil(R20, 8)
    food[:yb, :] = False
    M20 = dil(R20 | food, 1)
    # 闭运算补狗头遮挡缝(先膨4再蚀4)
    M20c = dil(M20, 4)
    for _ in range(4):
        m2 = M20c.copy()
        m2[1:, :] &= M20c[:-1, :]; m2[:-1, :] &= M20c[1:, :]
        m2[:, 1:] &= M20c[:, :-1]; m2[:, :-1] &= M20c[:, 1:]
        M20c = m2
    M20 = M20c | M20
    pasted = 0
    for i in (0, 1, 33):
        f = frames[i]
        old = dil(redmask(f), 2)
        f[old] = (0, 0, 0, 0)
        f[M20] = f20[M20]
        pasted += int(M20.sum())
    # ── 根因v4(彻底)：原视频matting把碗口白色食物当白背景抠掉→碗口是透明洞，
    # 引擎透明窗口下桌面透出=红碗"消失"。全帧碗口带透明/残白像素补狗粮纹理。
    rng = np.random.RandomState(42)
    yy, xx = np.mgrid[0:frames[0].shape[0], 0:frames[0].shape[1]]
    filled = 0
    for f in frames:
        Rm = redmask(f)
        if int(Rm.sum()) == 0:
            continue
        ys, xs = np.where(Rm)
        x0, x1 = int(xs.min()), int(xs.max())
        ytop = int(ys.min())
        # v7(最终)：碗口矩形带内所有透明洞→狗粮填充。
        y0z, y1z = ytop - 4, ytop + 26
        zone = (yy >= y0z) & (yy <= y1z) & (xx >= x0 + 5) & (xx <= x1 - 5)
        mouth = zone & (yy >= ytop + 2)   # 碗沿以下=碗口开孔区；碗后上沿薄带不碰
        al = f[:, :, 3]
        fill_m = mouth & (al < 200)
        n = int(fill_m.sum())
        if n:
            noise = rng.randint(-14, 15, n)
            for c, kv in enumerate((146, 96, 52)):
                ch = f[:, :, c].astype(int)
                ch[fill_m] = np.clip(kv + noise, 0, 255)
                f[:, :, c] = ch.astype(np.uint8)
            al[fill_m] = 255
            filled += n
        # matting垃圾(蓝斑B-R>10 / 亮白lum>170&sat<0.2)→狗粮填充；黑鼻暗AA保RGB实化
        Rch, Bch = f[:, :, 0].astype(int), f[:, :, 2].astype(int)
        rgb = f[:, :, :3].astype(int)
        lum = rgb.mean(2)
        sat = (rgb.max(2) - rgb.min(2)) / np.maximum(1, rgb.max(2))
        bad = zone & (al >= 200) & ((Bch - Rch > 10) | ((lum > 170) & (sat < 0.2)))
        nb = int(bad.sum())
        if nb:
            noise = rng.randint(-14, 15, nb)
            for c, kv in enumerate((146, 96, 52)):
                ch = f[:, :, c].astype(int)
                ch[bad] = np.clip(kv + noise, 0, 255)
                f[:, :, c] = ch.astype(np.uint8)
            al[bad] = 255
            filled += nb
        semi = zone & (al >= 200) & (al < 255) & ~bad
        al[semi] = 255
        filled += int(semi.sum())
    return pasted, filled


for st, (pf, n) in ANIMS.items():
    paths = [os.path.join(SRC, f'{pf}_{i:02d}.png') for i in range(n)]
    if not os.path.exists(paths[0]):
        print(f'{st:10s} SKIP')
        continue
    frames = [np.array(Image.open(p).convert('RGBA')) for p in paths]

    note = ''
    if st == 'bath':
        tot = sum(fix_bath_shadows(a) for a in frames)
        note = f'shadow_whitened={tot}'
    if st == 'eat':
        note = f'bowl_pasted={fix_eat_bowl(frames)}'

    mult = MULT.get(st, 1.0)

    m_s = v63_bottom_margin(pf)
    # pass1: 每帧bbox + 质心（mult作用于内容，质心=源空间*mult）
    boxes = []
    cx_sum, wsum = 0.0, 0.0
    for a in frames:
        b = _bbox_arr(a)
        boxes.append(b)
        al = a[:, :, 3].astype(np.float64)
        xs_idx = np.arange(a.shape[1])
        cx_sum += (al.sum(axis=0) * xs_idx).sum()
        wsum += al.sum()
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    uw, uh = (x1 - x0 + 1) * mult, (y1 - y0 + 1) * mult
    cx = (cx_sum / wsum - x0) * mult
    cw, ch = uw, uh
    half = int(math.ceil(abs(cx - cw / 2.0))) + 4
    W = int(cw) + 2 * half
    x0u = half - int(round(cx - cw / 2.0))
    pad_b = int(round(m_s))
    H = int(ch) + pad_b
    for i, (a, b) in enumerate(zip(frames, boxes)):
        content = a[b[1]:b[3] + 1, b[0]:b[2] + 1]
        if mult != 1.0:
            im_c = Image.fromarray(content)
            im_c = im_c.resize((max(2, int(round((b[2] - b[0] + 1) * mult))),
                                max(2, int(round((b[3] - b[1] + 1) * mult)))),
                               Image.LANCZOS)
            content = np.array(im_c)
        canvas = np.zeros((H, W, 4), dtype=np.uint8)
        px = x0u + int(round((b[0] - x0) * mult))
        py = int(round((b[1] - y0) * mult))
        canvas[py:py + content.shape[0], px:px + content.shape[1]] = content
        Image.fromarray(canvas).save(
            os.path.join(OUT, os.path.basename(paths[0]).replace('_00.png', f'_{i:02d}.png')))
    print(f'{st:10s} union={int(uw)}x{int(uh)} mult={mult} m_s={m_s} out={W}x{H} {note}')
print('REBAKE_V65_DONE')
