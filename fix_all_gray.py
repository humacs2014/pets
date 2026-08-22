# -*- coding: utf-8 -*-
"""v74: 全状态灰色 matting 残影统修。
判据 = 低饱和(mx-mn<=18)+中灰(90<=mx<=160)+不透明 → erode2 去边线 → 连通块>=60px
→ 仅修「邻接透明边界」的块（dilate4触及alpha<60）= matting 残留灰边（walk胸口/
run裆部/idle腋下等）；内部阴影（sit嘴周等合法毛发暗部）不邻透明→零误伤。
填充=列向最近合法毛发色（同fix_gray_wedge/fix_run_gray）。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe fix_all_gray.py [state...]
不带参数=全状态。
"""
import glob
import sys
import numpy as np
from PIL import Image
from scipy import ndimage

STATES = ['idle', 'sit', 'eat', 'bark', 'happy', 'roll', 'dance', 'beg',
          'bath', 'lick', 'surprised', 'play_dead', 'sleep', 'stretch',
          'walk', 'run', 'pet']
MAX_SCAN = 160

def erode(m, it=2):
    for _ in range(it):
        m2 = m.copy()
        m2[1:, :] &= m[:-1, :]; m2[:-1, :] &= m[1:, :]
        m2[:, 1:] &= m[:, :-1]; m2[:, :-1] &= m[:, 1:]
        m = m2
    return m

def dilate(m, it=4):
    for _ in range(it):
        m2 = m.copy()
        m2[1:, :] |= m[:-1, :]; m2[:-1, :] |= m[1:, :]
        m2[:, 1:] |= m[:, :-1]; m2[:, :-1] |= m[:, 1:]
        m = m2
    return m

states = sys.argv[1:] or STATES
grand = 0
# 合法毛发填充源 = 橙毛(饱和>30) 或 真白毛(mx>215且mn>200)，
# 排除抗锯齿浅灰边(如200,200,200这类mx>195的低饱和灰)
def good_fur(px):
    if px[3] < 200: return False
    mx = int(max(px[0], px[1], px[2])); mn = int(min(px[0], px[1], px[2]))
    return (mx - mn > 30) or (mx > 215 and mn > 200)
for st in states:
    fs = sorted(glob.glob('assets/%s_*.webp' % st)) + sorted(glob.glob('assets/%s_*.png' % st))
    st_tot = 0; nf = 0
    for f in fs:
        img = Image.open(f).convert('RGBA')
        a = np.array(img)
        rgb = a[..., :3].astype(np.int16); al = a[..., 3]
        mx = rgb.max(-1); mn = rgb.min(-1)
        trans = al < 60
        # v74d: 灰影=低饱和(mx-mn<=20, 85<=mx<=205)厚区。连通块>=400px且
        # 环上不邻深色(黑嘴/黑鼻→自然阴影排除, sit嘴影=0命中)；
        # 内部灰(腿间被填实)与边界灰边统一处理。正常轮廓抗锯齿细线被erode1滤除。
        gray = (mx - mn <= 20) & (mx >= 85) & (mx <= 212) & (al > 150)
        me = erode(gray, 1)
        if not me.any():
            continue
        cand = ndimage.binary_dilation(me, iterations=2) & gray
        dark = mx < 90
        lab, n = ndimage.label(cand)
        m = np.zeros_like(cand)
        for i in range(1, n + 1):
            comp = (lab == i)
            if comp.sum() < 150:   # v74f: 2-3px宽竖条erode后连通域小, 400会漏
                continue
            ring = dilate(comp, 3) & ~comp
            if dark[ring].sum() > 0.03 * ring.sum():
                continue   # 邻黑嘴/黑鼻 = 自然阴影，不修
            m |= comp
        if not m.any():
            continue
        ys, xs = np.where(m)
        h, w = m.shape
        for y, x in zip(ys, xs):
            fill = None
            for dy in range(1, MAX_SCAN):
                yy = y + dy
                if yy >= h: break
                if not m[yy, x] and good_fur(a[yy, x]):
                    fill = a[yy, x, :3]; break
            if fill is None:
                for dy in range(1, MAX_SCAN):
                    yy = y - dy
                    if yy < 0: break
                    if not m[yy, x] and good_fur(a[yy, x]):
                        fill = a[yy, x, :3]; break
            if fill is None:
                for dx in range(1, MAX_SCAN):   # 横向: 水平灰带(腿间/胸前竖条)
                    xx = x + dx
                    if xx >= w: break
                    if not m[y, xx] and good_fur(a[y, xx]):
                        fill = a[y, xx, :3]; break
            if fill is None:
                for dx in range(1, MAX_SCAN):
                    xx = x - dx
                    if xx < 0: break
                    if not m[y, xx] and good_fur(a[y, xx]):
                        fill = a[y, xx, :3]; break
            if fill is None:
                a[y, x, 3] = 0   # 无合法毛源=纯垃圾边，透明收缩比硬填色自然
                continue
            a[y, x, :3] = fill
            a[y, x, 3] = 255
        Image.fromarray(a).save(f)
        st_tot += int(m.sum()); nf += 1
    grand += st_tot
    print(st, 'frames=', nf, 'px=', st_tot)
print('GRAND TOTAL', grand)
