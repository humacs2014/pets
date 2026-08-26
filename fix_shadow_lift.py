# -*- coding: utf-8 -*-
"""阴影带提亮至局部背景亮度（闪烁根因修复，时序灰二阶段）。

根因链：
1. fix_gray_temporal 白化只去色相（r=g=b=mx），但 mx~191 的中性灰条在 235 白毛上仍是可见暗带；
2. 暗带随步态逐帧漂移（inter/union=0.008）→ 播放时同位置忽有忽无 = 闪烁。

修复：检测"低饱和 + 邻域低饱和 + 比局部背景暗"的像素，按增益（背景亮度-自身亮度）
整体提亮三通道，保留纹理细节（不是抹平）。迭代至收敛。
安全门：棕毛自身 sat>0.45 不触发；棕毛邻域饱和度高不触发；背景用邻域高亮度估计，
提亮只向邻域已有亮度看齐，不产生新的过曝。
链位置：直接作用于当前资产（纯追加，不回滚）；在 fix_gray_temporal 之后。
用法: python fix_shadow_lift.py [state...]  (不带参数=全状态扫描)
"""
import glob
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

MAX_PASSES = 15
CAP = 45


def lift(arr):
    a = arr.astype(np.int32)
    total = 0
    passes = 0
    for _ in range(MAX_PASSES):
        rgb, al = a[..., :3], a[..., 3]
        mx = rgb.max(-1)
        mn = rgb.min(-1)
        sat = (mx - mn).astype(np.float64) / np.maximum(mx, 1)
        sat_img = Image.fromarray((np.clip(sat, 0, 1) * 255).astype(np.uint8))
        nbr_sat = np.asarray(sat_img.filter(ImageFilter.BoxBlur(4))).astype(np.float64) / 255.0
        # 局部背景亮度：邻域最大亮度再取中值（稳健估计白毛水平）
        mx_u8 = Image.fromarray(np.clip(mx, 0, 255).astype(np.uint8))
        bg = np.asarray(mx_u8.filter(ImageFilter.MaxFilter(11))
                        .filter(ImageFilter.MedianFilter(15))).astype(np.float64)
        m = (al > 200) & (sat <= 0.45) & (mx >= 80) & (nbr_sat <= 0.22) & (mx < bg - 6)
        n = int(m.sum())
        passes += 1
        if n == 0:
            break
        ys, xs = np.where(m)
        gain = np.clip(bg[ys, xs] - mx[ys, xs], 0, CAP)
        for c in range(3):
            a[ys, xs, c] = np.clip(a[ys, xs, c] + gain.astype(np.int32), 0, 255)
        total += n
        if n < 200:
            break
    return a.astype(np.uint8), total, passes


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
    for st in states:
        fs = sorted(glob.glob(f'assets/{st}_*.png')) + sorted(glob.glob(f'assets/{st}_*.webp'))
        if not fs:
            print(f'{st}: no frames')
            continue
        tot, maxp = 0, 0
        for f in fs:
            arr = np.asarray(Image.open(f).convert('RGBA'))
            new, n, p = lift(arr)
            Image.fromarray(new, 'RGBA').save(f, quality=95)
            tot += n
            maxp = max(maxp, p)
        print(f'{st}: frames={len(fs)} lifted={tot} max_passes={maxp}', flush=True)
    print('DONE', flush=True)
