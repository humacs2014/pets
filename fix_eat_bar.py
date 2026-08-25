# -*- coding: utf-8 -*-
"""v79i: eat 长方形条清除（竖直直线检测）。
bar 特征: 右界 xR 在 ≥25 连续行内恒定(竖直边), 且该值 > 上下±60行中位数+10。
碗/耳轮廓为弧线(连续同值行少), 不触发。frames+assets 都擦。"""
import os
import statistics
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))


def clean_arr(a):
    H = a.shape[0]
    xR = np.full(H, -1, int)
    for y in range(H):
        xs = np.nonzero(a[y, :, 3] > 30)[0]
        if len(xs) > 3:
            xR[y] = xs.max()
    # 连续同值(±1) run
    runs = []
    y = 0
    while y < H:
        if xR[y] < 0:
            y += 1
            continue
        v = xR[y]
        y1 = y
        while y1 + 1 < H and xR[y1 + 1] >= 0 and abs(xR[y1 + 1] - v) <= 1:
            y1 += 1
        runs.append((y, y1, v))
        y = y1 + 1
    erased = 0
    for y0, y1, v in runs:
        if y1 - y0 + 1 < 25:
            continue
        win = [xR[t] for t in range(max(0, y0 - 60), min(H, y1 + 61)) if xR[t] > 0]
        ref = statistics.median(win)
        if v - ref <= 10:
            continue
        # bar: 清 [ref+2, v] 仅实像素(>=240), 保头缘半透 fringe
        for y in range(y0, y1 + 1):
            for x in range(int(ref) + 2, xR[y] + 1):
                if a[y, x, 3] >= 240:
                    a[y, x, 3] = 0
                    erased += 1
    return erased


def clean_dir(d, ext):
    tot = 0
    i = 0
    while True:
        p = os.path.join(d, f'eat_{i:02d}.{ext}')
        if not os.path.exists(p):
            break
        im = Image.open(p).convert('RGBA')
        a = np.array(im)
        e = clean_arr(a)
        if e:
            Image.fromarray(a, 'RGBA').save(p)
        tot += e
        i += 1
    return i, tot


for d, ext in ((os.path.join(ROOT, 'frames'), 'png'),
               (os.path.join(ROOT, 'assets'), 'png')):
    n, tot = clean_dir(d, ext)
    print(f'{os.path.basename(d)}: {n} frames, erased={tot}', flush=True)
print('DONE', flush=True)
