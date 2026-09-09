# -*- coding: utf-8 -*-
"""bath 专用：泡沫-盆沿交界灰色 matting 楔形残影修复（全自动，v71 范式）。
灰楔形=不透明中性灰块，物理上只出现在泡沫贴着蓝色盆沿的交界处。
自动判据（golden 57帧实测验证，零毛发误伤）：
  灰判据 = 低饱和(mx-mn<=18) + 中灰(90<=mx<=200) + 不透明(al>200)
  限定   = 灰像素必须紧贴蓝色盆体（盆判据 B-R>30 & al>200，dilate 3px）
对照测试：全帧扫描单帧max=1350（全是毛发误伤）；盆沿带单帧max=445（仍含泡沫-狗胸交界合法灰）；
紧贴盆单帧max=34（等效手工标定0-26）。无需手工标定 X0/X1/Y0/Y1。
安全门：单帧命中>2000 = 判据异常，中止报错人工复核。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe fix_gray_wedge.py
"""
import glob
import sys
import numpy as np
from PIL import Image
from scipy import ndimage

MAX_SCAN = 120
HIT_LIMIT_PER_FRAME = 2000   # 安全门（实测合法灰楔形单帧≤34）

def gray_mask(a):
    rgb = a[..., :3].astype(np.int16)
    al = a[..., 3]
    mx = rgb.max(-1)
    mn = rgb.min(-1)
    return (mx - mn <= 18) & (mx >= 90) & (mx <= 200) & (al > 200)

def tub_mask(a):
    rgb = a[..., :3].astype(np.int16)
    al = a[..., 3]
    return (rgb[..., 2] - rgb[..., 0] > 30) & (al > 200)

def dilate(m, it=1):
    for _ in range(it):
        m2 = m.copy()
        m2[1:, :] |= m[:-1, :]; m2[:-1, :] |= m[1:, :]
        m2[:, 1:] |= m[:, :-1]; m2[:, :-1] |= m[:, 1:]
        m = m2
    return m

total = 0
for f in sorted(glob.glob('assets/bath_*.png')):
    img = Image.open(f).convert('RGBA')
    a = np.array(img)
    gm = gray_mask(a)
    if not gm.any():
        continue
    # 灰楔形只出现在泡沫-盆沿交界：灰像素必须紧贴蓝色盆体
    tb = tub_mask(a)
    if not tb.any():
        print(f'SKIP {f}: 未检出蓝色盆体（盆判据 B-R>30 不匹配，检查盆色）')
        continue
    tb_d = ndimage.binary_dilation(tb, iterations=3)
    m = gm & tb_d
    n = int(m.sum())
    if n == 0:
        continue
    if n > HIT_LIMIT_PER_FRAME:
        print(f'FAIL {f}: gray hits {n} > safety limit {HIT_LIMIT_PER_FRAME} '
              f'(判据异常，人工检查该帧)')
        sys.exit(1)
    m = dilate(m, 1)
    n = int(m.sum())
    ys, xs = np.where(m)
    h, w = m.shape
    for y, x in zip(ys, xs):
        fill = None
        for dy in range(1, MAX_SCAN):
            yy = y + dy
            if yy >= h: break
            if not m[yy, x] and a[yy, x, 3] > 200:
                fill = a[yy, x, :3]; break
        if fill is None:
            for dy in range(1, MAX_SCAN):
                yy = y - dy
                if yy < 0: break
                if not m[yy, x] and a[yy, x, 3] > 200:
                    fill = a[yy, x, :3]; break
        if fill is None:
            fill = np.array([95, 170, 230], np.uint8)
        a[y, x, :3] = fill
        a[y, x, 3] = 255
    Image.fromarray(a).save(f)
    total += n
    print(f.split('/')[-1].split('\\')[-1], 'fixed', n)
print('TOTAL', total)
