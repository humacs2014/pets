# -*- coding: utf-8 -*-
"""从 eat 视频抽帧+抠图 → clean/c_*.png（未归一化原尺寸mat帧）。
bake_prop.py 的输入：无碗进食帧，保留原始几何供三层烤帧缩放锚定。
husky v47 起该步骤独立于 extract_frames.py（后者做loop/normalize，会丢头下探幅度）。
"""
import os
import numpy as np
from PIL import Image
from extract_frames import cutout_frames, extract, _standing_leg_ok

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, 'clean')
os.makedirs(OUT, exist_ok=True)

fps = extract('eat')
if not fps:
    raise SystemExit('no eat.mp4 frames')
mats = cutout_frames(fps, 'eat_clean')   # 返回 mat 文件路径列表
n_written = 0
for k, p in enumerate(mats):
    im = Image.open(p).convert('RGBA')
    a = np.array(im)
    if a[..., 3].max() < 40:
        continue
    # 2026-08-17: 剔除3/4正面张腿帧(分叉狗)——低头吃食帧非站姿自动豁免
    if not _standing_leg_ok(a[..., 3]):
        print(f'  skip c_{k:03d}: splayed/front-view legs', flush=True)
        continue
    # 2026-08-17 v2: 只保留最大连通域——抠图残留粮渣(实测49/121帧有碎片,
    # 最大3246px=用户截图脚边粮堆)烤进assets成永久粮堆
    from scipy import ndimage
    lab, n = ndimage.label(a[..., 3] > 40)
    if n > 1:
        keep = np.argmax(ndimage.sum(a[..., 3] > 40, lab, range(1, n + 1))) + 1
        a[..., 3] = np.where(lab == keep, a[..., 3], 0)
        im = Image.fromarray(a, 'RGBA')
    im.save(os.path.join(OUT, f'c_{k:03d}.png'))
    n_written += 1
print(f'WROTE {n_written} clean frames → clean/c_*.png')
