# -*- coding: utf-8 -*-
"""从 eat 视频抽帧+抠图 → clean/c_*.png（未归一化原尺寸mat帧）。
bake_prop.py 的输入：无碗进食帧，保留原始几何供三层烤帧缩放锚定。
husky v47 起该步骤独立于 extract_frames.py（后者做loop/normalize，会丢头下探幅度）。
"""
import os, subprocess, glob
import numpy as np
from PIL import Image
from extract_frames import cutout_frames, extract

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, 'clean')
os.makedirs(OUT, exist_ok=True)

fps = extract('eat')
if not fps:
    raise SystemExit('no eat.mp4 frames')
mats = cutout_frames(fps, 'eat_clean')
n = 0
for k, m in enumerate(mats):
    a = np.array(m)
    if a[..., 3].max() < 40:
        continue
    m.save(os.path.join(OUT, f'c_{k:03d}.png'))
    n += 1
print(f'WROTE {n} clean frames → clean/c_*.png')
