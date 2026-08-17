# -*- coding: utf-8 -*-
"""全16状态全帧腿blob审计: 站姿帧下部行带数水平连通块。
正常侧视站立=3-4条腿(4 blob或前后腿贴近合并3); 分叉狗=5+ blob 或 腿跨度过宽。
用法: python _qa_leg_audit.py  -> 打印每状态flag帧 + 生成网格图
"""
import os, glob
import numpy as np
from PIL import Image

ANIMS = {'idle': 101, 'walk': 20, 'run': 15, 'eat': 34, 'bark': 57,
         'sleep': 51, 'sit': 63, 'lick': 54, 'happy': 62, 'roll': 121,
         'dance': 57, 'stretch': 117, 'beg': 56, 'bath': 57,
         'surprised': 45, 'play_dead': 68}

def leg_scan(a):
    """返回 (nblobs, span_ratio, is_standing)。a=RGBA ndarray"""
    al = a[:, :, 3]
    ys, xs = np.where(al > 40)
    if len(xs) == 0:
        return None
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    h = y1 - y0 + 1
    w = x1 - x0 + 1
    # 站姿判定: 内容高>宽*0.75 且下部有细腿结构(腿行最大行宽<体宽70%)
    band_y0 = y0 + int(h * 0.78)
    band_y1 = y0 + int(h * 0.94)
    rows = al[band_y0:band_y1]
    # 每行连通块
    best = 0
    best_span = 0
    for r in rows:
        line = r[x0:x1 + 1] > 127
        if line.sum() < 4:
            continue
        # 连通块
        d = np.diff(line.astype(int))
        starts = np.where(d == 1)[0] + 1
        ends = np.where(d == -1)[0] + 1
        if line[0]:
            starts = np.r_[0, starts]
        if line[-1]:
            ends = np.r_[ends, len(line)]
        blobs = [(s, e) for s, e in zip(starts, ends) if e - s >= 2]
        if len(blobs) > best:
            best = len(blobs)
            best_span = (blobs[-1][1] - blobs[0][0]) / w
    standing = h > w * 0.72
    return best, best_span, standing

print(f'{"state":11s} stand%  flag frames (idx:blobs:span)')
summary = {}
for st, want in ANIMS.items():
    fs = sorted(glob.glob(f'assets/{st}_*.png'),
                key=lambda p: int(os.path.basename(p).rsplit('_', 1)[1].split('.')[0]))
    flags, nst = [], 0
    for i, fp in enumerate(fs):
        r = leg_scan(np.array(Image.open(fp).convert('RGBA')))
        if r is None:
            continue
        nb, span, standing = r
        if standing:
            nst += 1
            if nb >= 5 or (nb >= 4 and span > 0.92):
                flags.append(f'{i}:{nb}:{span:.2f}')
    summary[st] = (len(fs), nst, flags)
    print(f'{st:11s} {nst}/{len(fs):3d}  {", ".join(flags[:14]) if flags else "-"}')
print('LEG_AUDIT_DONE')
