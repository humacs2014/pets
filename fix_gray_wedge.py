# -*- coding: utf-8 -*-
"""修复 bath 帧右侧泡沫-盆沿交界的灰色 matting 楔形残影。
灰色楔形=不透明中性灰块，位于右盆沿下方。用向下采样（第一个非灰不透明像素=盆体蓝）填补。
限定区域：x[550,805], y[585,940]，避免误伤左侧泡沫-毛合法暗缝。
"""
import glob
import numpy as np
from PIL import Image

X0, X1 = 550, 805
Y0, Y1 = 585, 940
MAX_SCAN = 120

def gray_mask(a):
    rgb = a[..., :3].astype(np.int16)
    al = a[..., 3]
    mx = rgb.max(-1)
    mn = rgb.min(-1)
    m = (mx - mn <= 18) & (mx >= 90) & (mx <= 200) & (al > 200)
    region = np.zeros_like(m)
    region[Y0:Y1, X0:X1] = True
    return m & region

def dilate(m, it=1):
    for _ in range(it):
        m2 = m.copy()
        m2[1:, :] |= m[:-1, :]
        m2[:-1, :] |= m[1:, :]
        m2[:, 1:] |= m[:, :-1]
        m2[:, :-1] |= m[:, 1:]
        m = m2
    return m

total = 0
for f in sorted(glob.glob('assets/bath_*.png')):
    img = Image.open(f).convert('RGBA')
    a = np.array(img)
    m = dilate(gray_mask(a), 1)
    n = int(m.sum())
    if n == 0:
        continue
    ys, xs = np.where(m)
    h, w = m.shape
    for y, x in zip(ys, xs):
        fill = None
        for dy in range(1, MAX_SCAN):
            yy = y + dy
            if yy >= h:
                break
            if not m[yy, x] and a[yy, x, 3] > 200:
                fill = a[yy, x, :3]
                break
        if fill is None:
            for dy in range(1, MAX_SCAN):
                yy = y - dy
                if yy < 0:
                    break
                if not m[yy, x] and a[yy, x, 3] > 200:
                    fill = a[yy, x, :3]
                    break
        if fill is None:
            fill = np.array([95, 170, 230], np.uint8)
        a[y, x, :3] = fill
        a[y, x, 3] = 255
    Image.fromarray(a).save(f)
    total += n
    print(f.split('/')[-1].split('\\')[-1], 'fixed', n)
print('TOTAL', total)
