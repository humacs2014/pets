# -*- coding: utf-8 -*-
"""v73: run 裆部/腿间灰色 matting 残影修复（移植 bath fix_gray_wedge v71 范式）。
灰判据 = 低饱和(mx-mn<=18) + 中暗灰(90<=mx<=160) + 不透明(al>200)。
形态过滤 = 仅修「内部致密灰块」：erode(2)后仍存在的连通块（去轮廓抗锯齿细线），
块面积 60..6000 安全门；填充=列向最近合法毛发色（同fix_gray_wedge）。
毛发安全：橙毛/白毛饱和度或亮度均不落在判据内（overlay目视验证过）。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe fix_run_gray.py
"""
import glob
import sys
import numpy as np
from PIL import Image
from scipy import ndimage

MAX_SCAN = 160
HIT_LIMIT_PER_FRAME = 6000   # 安全门：单帧内部灰块超此值=判据异常

def gray_mask(a):
    rgb = a[..., :3].astype(np.int16)
    al = a[..., 3]
    mx = rgb.max(-1); mn = rgb.min(-1)
    return (mx - mn <= 18) & (mx >= 90) & (mx <= 160) & (al > 200)

def erode(m, it=2):
    for _ in range(it):
        m2 = m.copy()
        m2[1:, :] &= m[:-1, :]; m2[:-1, :] &= m[1:, :]
        m2[:, 1:] &= m[:, :-1]; m2[:, :-1] &= m[:, 1:]
        m = m2
    return m

total = 0
for f in sorted(glob.glob('assets/run_*.webp')):
    img = Image.open(f).convert('RGBA')
    a = np.array(img)
    gm = gray_mask(a)
    if not gm.any():
        continue
    core = erode(gm, 2)                      # 去轮廓抗锯齿细线
    lab, n = ndimage.label(core)
    keep = np.zeros_like(core)
    for i in range(1, n + 1):
        ar = int((lab == i).sum())
        if 60 <= ar <= HIT_LIMIT_PER_FRAME:
            keep |= (lab == i)
    if not keep.any():
        continue
    m = ndimage.binary_dilation(keep, iterations=3) & gm   # 恢复完整块边界
    nfix = int(m.sum())
    if nfix > HIT_LIMIT_PER_FRAME:
        print(f'FAIL {f}: {nfix} > limit, abort'); sys.exit(1)
    ys, xs = np.where(m)
    h, w = m.shape
    for y, x in zip(ys, xs):
        fill = None
        for dy in range(1, MAX_SCAN):        # 向下找最近毛发色
            yy = y + dy
            if yy >= h: break
            if not m[yy, x] and a[yy, x, 3] > 200:
                fill = a[yy, x, :3]; break
        if fill is None:                     # 向上兜底
            for dy in range(1, MAX_SCAN):
                yy = y - dy
                if yy < 0: break
                if not m[yy, x] and a[yy, x, 3] > 200:
                    fill = a[yy, x, :3]; break
        if fill is None:
            fill = np.array([230, 170, 110], np.uint8)
        a[y, x, :3] = fill
        a[y, x, 3] = 255
    Image.fromarray(a).save(f)
    total += nfix
    print(f.split('\\')[-1], 'fixed', nfix)
print('TOTAL', total)
