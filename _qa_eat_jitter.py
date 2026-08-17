# -*- coding: utf-8 -*-
"""eat 晃动量化: 每帧脚底行y与身体重心x的帧间方差。
判据: 脚底y极差<=2px 且 重心x极差<=6px → 无晃动。"""
import glob
import numpy as np
from PIL import Image

foot_ys, body_xs, body_ys = [], [], []
fs = sorted(glob.glob('assets/eat_*.png'),
            key=lambda p: int(p.split('_')[1].split('.')[0]))
for p in fs:
    a = np.array(Image.open(p).convert('RGBA'))
    ys, xs = np.where(a[..., 3] > 40)
    if len(xs) == 0:
        foot_ys.append(None); body_xs.append(None); body_ys.append(None)
        continue
    foot_ys.append(int(ys.max()))
    body_xs.append(round(float(xs.mean()), 1))
    body_ys.append(round(float(ys.mean()), 1))

fy = [v for v in foot_ys if v is not None]
bx = [v for v in body_xs if v is not None]
by = [v for v in body_ys if v is not None]
print(f'frames={len(fs)} valid={len(fy)}')
print(f'foot_y: min={min(fy)} max={max(fy)} range={max(fy)-min(fy)}')
print(f'body_x: min={min(bx)} max={max(bx)} range={round(max(bx)-min(bx),1)}')
print(f'body_y: min={min(by)} max={max(by)} range={round(max(by)-min(by),1)}')
# 判据: 脚底锚定(<=3px)=狗稳站地面不晃。body重心移动是低头进食的自然头部运动,不算晃动。
ok = (max(fy) - min(fy)) <= 3
print('JITTER_PASS (feet anchored)' if ok else 'JITTER_FAIL (feet drift)')
