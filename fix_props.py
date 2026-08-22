# -*- coding: utf-8 -*-
"""阶段4: 道具 alpha 完整性审计 + 标准化（eat 红碗范式，可参数化到其他高饱和道具）。
背景铁律：rembg 白底 matting 会把白色食物当背景抠掉→碗口透明洞→引擎透明窗口透桌面=道具"消失"；
AI 视频循环边界帧道具整体缩小=道具"时隐时现"。RGB 检查查不到透明洞，必须 alpha 维度审计。

碗口带像素三分（实测结构）：
  A. 红碗自身AA边（R-B>=60，al<250，带顶2行）→ 保红色实化 al=255
  B. 真洞（al<200 非红，可延伸到 ytop+40）→ 棕色 kibble 纹理填充
  C. matting垃圾（al>=200 非红：蓝斑B-R>10 | 亮白lum>170&sat<0.2）→ 填棕
  半透非红(200-254) → 保RGB实化
合成验收图必须用有色背景（白底掩盖透明洞）。fix 后重跑 audit 至全 0。

用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe fix_props.py audit|fix [状态名...]
环境变量: PROP_ASSETS=资产目录 PROP_EXT=png|webp
换道具: 改 prop_mask 颜色签名 + RED_AA 判定（红碗=高饱和红；阈值只认高饱和——毛色 R-G 仅40-60 会淹没统计）。
"""
import os, sys, glob
import numpy as np
from PIL import Image

ASSETS = os.environ.get('PROP_ASSETS', 'assets')
EXT = os.environ.get('PROP_EXT', 'png')   # 部署格式（webp 部署时设 PROP_EXT=webp）
STATES = sys.argv[2:] or ['eat']
KIBBLE = (146, 96, 52)          # 填充纹理基准色（碗口食物棕）
MOUTH_DY0, MOUTH_DY1 = 0, 40   # 碗口全带（含碗沿AA顶+开孔区，实测洞可到 ytop+40）
MOUTH_DX = 5                    # x 内缩（挡碗左右外侧透明缝）
RED_AA = 60                     # R-B>=60 = 红碗自身AA边（保红实化）；<60 = 非红（洞/垃圾）


def prop_mask(a, yb_frac=0.60):
    """高饱和红碗签名。换道具改这里。"""
    R, G, B = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    m = (a[:, :, 3] > 127) & (R > 140) & (R - G > 70) & (R - B > 70)
    m[:int(a.shape[0] * yb_frac), :] = False
    return m


def dil(m, k):
    for _ in range(k):
        m2 = m.copy()
        m2[1:, :] |= m[:-1, :]; m2[:-1, :] |= m[1:, :]
        m2[:, 1:] |= m[:, :-1]; m2[:, :-1] |= m[:, 1:]
        m = m2
    return m


def bowl_geo(a):
    Rm = prop_mask(a)
    n = int(Rm.sum())
    if n == 0:
        return None
    ys, xs = np.where(Rm)
    return Rm, n, int(xs.min()), int(xs.max()), int(ys.min())


def _band_masks(a, geo):
    Rm, n, x0, x1, ytop = geo
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    mouth = (yy >= ytop + MOUTH_DY0) & (yy <= ytop + MOUTH_DY1) & \
            (xx >= x0 + MOUTH_DX) & (xx <= x1 - MOUTH_DX)
    al = a[:, :, 3]
    rgb = a[:, :, :3].astype(int)
    lum = rgb.mean(2)
    sat = (rgb.max(2) - rgb.min(2)) / np.maximum(1, rgb.max(2))
    redaa = mouth & (al > 0) & (al < 250) & (rgb[:, :, 0] - rgb[:, :, 2] >= RED_AA)
    return mouth, al, rgb, lum, sat, redaa


def audit_frame(a):
    g = bowl_geo(a)
    if g is None:
        return dict(count=0, hole=0, semi=0, garb=0)
    mouth, al, rgb, lum, sat, redaa = _band_masks(a, g)
    hole = int((mouth & (al < 200)).sum())
    semi = int((mouth & (al >= 200) & (al < 250) & ~redaa).sum())
    garb = int((mouth & (al >= 200) &
                ((rgb[:, :, 2] - rgb[:, :, 0] > 10) | ((lum > 170) & (sat < 0.2)))).sum())
    return dict(count=g[1], hole=hole, semi=semi, garb=garb)


def fix_state(name):
    rng = np.random.RandomState(42)
    paths = sorted(glob.glob(os.path.join(ASSETS, f'{name}_*.{EXT}')))
    frames = [np.array(Image.open(p).convert('RGBA')) for p in paths]
    if not frames:
        print(f'  [skip] {name}: no frames'); return
    h, w = frames[0].shape[:2]
    counts = []
    geos = []
    for f in frames:
        g = bowl_geo(f)
        geos.append(g)
        counts.append(g[1] if g else 0)
    med = int(np.median([c for c in counts if c]))
    ref_i = min(range(2, len(frames) - 2), key=lambda i: abs(counts[i] - med))
    f20 = frames[ref_i]
    R20, n20, x0r, x1r, ytr = geos[ref_i]
    rgb = f20[:, :, :3].astype(int)
    sat20 = (rgb.max(2) - rgb.min(2)) / np.maximum(1, rgb.max(2))
    lum20 = rgb.mean(2)
    food = (f20[:, :, 3] > 127) & (sat20 < 0.18) & (lum20 > 190) & dil(R20, 8)
    M20 = dil(R20 | food, 1)
    M20c = dil(M20, 4)
    for _ in range(4):  # 闭运算补动物遮挡缝
        m2 = M20c.copy()
        m2[1:, :] &= M20c[:-1, :]; m2[:-1, :] &= M20c[1:, :]
        m2[:, 1:] &= M20c[:, :-1]; m2[:, :-1] &= M20c[:, 1:]
        M20c = m2
    M20 = M20c | M20
    pasted = filled = 0
    for i, f in enumerate(frames):
        g = geos[i]
        if g is None:
            continue
        Rm, n, x0, x1, ytop = g
        outlier = abs(n - med) > 0.25 * med
        if i in (0, 1, len(frames) - 1) or outlier:
            old = dil(Rm, 2)
            f[old] = (0, 0, 0, 0)
            f[M20] = f20[M20]
            pasted += int(M20.sum())
            g = bowl_geo(f)
            Rm, n, x0, x1, ytop = g
        mouth, al, rgb, lum, sat, redaa = _band_masks(f, g)
        # A. 红AA实化（保红，仅半透红边）
        redlo = mouth & (al >= 200) & (al < 250) & (rgb[:, :, 0] - rgb[:, :, 2] >= RED_AA)
        al[redlo] = 255
        filled += int(redlo.sum())
        # B. 洞+黑垃圾全填棕（al<200 含 premul 黑残/真洞）
        fill_m = mouth & (al < 200)
        nfill = int(fill_m.sum())
        if nfill:
            noise = rng.randint(-14, 15, nfill)
            for c, kv in enumerate(KIBBLE):
                ch = f[:, :, c].astype(int)
                ch[fill_m] = np.clip(kv + noise, 0, 255)
                f[:, :, c] = ch.astype(np.uint8)
            al[fill_m] = 255
            filled += nfill
        # C. 垃圾填棕
        bad = mouth & (al >= 200) & ((rgb[:, :, 2] - rgb[:, :, 0] > 10) | ((lum > 170) & (sat < 0.2)))
        nbad = int(bad.sum())
        if nbad:
            noise = rng.randint(-14, 15, nbad)
            for c, kv in enumerate(KIBBLE):
                ch = f[:, :, c].astype(int)
                ch[bad] = np.clip(kv + noise, 0, 255)
                f[:, :, c] = ch.astype(np.uint8)
            al[bad] = 255
            filled += nbad
        # 半透非红实化
        semi = mouth & ~redaa & ~bad & (al >= 200) & (al < 255)
        al[semi] = 255
        filled += int(semi.sum())
        Image.fromarray(f).save(paths[i])
    print(f'  {name}: pasted={pasted} filled={filled}')


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'audit'
    bad_total = 0
    for name in STATES:
        paths = sorted(glob.glob(os.path.join(ASSETS, f'{name}_*.{EXT}')))
        if mode == 'fix':
            fix_state(name)
            continue
        worst = dict(hole=0, semi=0, garb=0)
        sizes = []
        for p in paths:
            r = audit_frame(np.array(Image.open(p).convert('RGBA')))
            sizes.append(r['count'])
            for k in worst:
                worst[k] = max(worst[k], r[k])
        sizes = [s for s in sizes if s]
        cv = float(np.std(sizes) / np.mean(sizes)) if sizes else 0
        ok = worst['hole'] == 0 and worst['semi'] == 0 and worst['garb'] == 0 and cv < 0.10
        bad_total += 0 if ok else 1
        print(f'{name:10s} cv={cv:.3f} max hole={worst["hole"]} semi={worst["semi"]} '
              f'garb={worst["garb"]} -> {"PASS" if ok else "FAIL"}')
    if mode == 'audit':
        print('AUDIT_' + ('PASS' if bad_total == 0 else f'FAIL({bad_total})'))


if __name__ == '__main__':
    main()
