# -*- coding: utf-8 -*-
"""闪烁量化检测（分离"运动"与"闪烁"，验收门）。
闪烁=同一固定位置亮度反复亮→暗→亮（符号翻转次数高）；
运动=边缘像素整体移动（不在"所有帧都内部"集合里，自动排除）。
用法: python flicker_detect.py [state...]  (不带参数=全状态扫描)
判定: 强闪烁(>=3翻转)像素>0 → 跑 scripts/fix_gray_temporal.py 后重测。
"""
import glob
import os
import sys

import numpy as np
from PIL import Image


def load(pattern):
    fs = sorted(glob.glob(pattern))
    return [np.asarray(Image.open(f).convert('RGBA')) for f in fs]


def flicker_metric(frames, tag):
    n = len(frames)
    H, W = frames[0].shape[:2]
    # 所有帧都不透明的内部像素
    op = np.ones((H, W), bool)
    for a in frames:
        op &= (a[..., 3] == 255)

    gs = np.stack([a[..., :3].mean(2) for a in frames])  # n x H x W
    d = np.diff(gs, axis=0)
    sign = np.sign(d)
    sign[np.abs(d) < 4] = 0  # 忽略小抖动
    flips = (sign[:-1] * sign[1:] < 0).sum(0)
    flips = flips * op
    interior = op.sum()
    hot = (flips >= 3)
    very_hot = (flips >= 5)
    print('%s: n=%d 内部像素=%d 强闪烁(>=3翻转)=%d 极强(>=5)=%d' %
          (tag, n, interior, hot.sum(), very_hot.sum()))
    if very_hot.any():
        ys, xs = np.where(very_hot)
        print('  极强闪烁 bbox: y%d-%d x%d-%d' % (ys.min(), ys.max(), xs.min(), xs.max()))
    return int(hot.sum()), int(very_hot.sum())


if __name__ == '__main__':
    if len(sys.argv) > 1:
        states = sys.argv[1:]
    else:
        seen = set()
        states = []
        for f in glob.glob('assets/*_*'):
            st = os.path.basename(f).rsplit('_', 1)[0]
            if not st.startswith('_') and st not in seen:
                seen.add(st)
                states.append(st)
    total_hot = 0
    for st in states:
        frames = load(f'assets/{st}_*.png') or load(f'assets/{st}_*.webp')
        if not frames:
            print(f'{st}: no frames')
            continue
        h, _ = flicker_metric(frames, st)
        total_hot += h
    print('---')
    if total_hot > 0:
        print(f'FAIL: {total_hot} 强闪烁像素存在 → 跑 fix_gray_temporal.py 后重测')
        sys.exit(1)
    print('PASS: 零强闪烁')
