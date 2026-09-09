# -*- coding: utf-8 -*-
"""cutout_walk.py — walk帧rembg抠图（修复只读数组）
"""
import os, numpy as np
from PIL import Image
import rembg

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw_frames', 'walk')
FRAMES = os.path.join(ROOT, 'frames')

session = rembg.new_session('isnet-general-use')
total = 0
for i in range(121):
    raw_fn = os.path.join(RAW, f'frame_{i+1:04d}.png')
    out_fn = os.path.join(FRAMES, f'walk_{i:03d}.png')
    if not os.path.exists(raw_fn):
        continue
    raw = np.array(Image.open(raw_fn).convert('RGBA'))
    # rembg抠图 — 用PIL中转避免只读数组问题
    raw_rgb = Image.fromarray(raw[:,:,:3])
    result_pil = rembg.remove(raw_rgb, session=session)
    result = np.array(result_pil.convert('RGBA'))
    # alpha二值化
    alpha = result[:,:,3].copy()
    alpha[alpha > 128] = 255
    alpha[alpha <= 128] = 0
    result[:,:,3] = alpha
    # 背景区RGB清零
    bg = alpha == 0
    for ch in range(3):
        result[bg, ch] = 0
    Image.fromarray(result, 'RGBA').save(out_fn)
    total += 1
    if (i+1) % 30 == 0:
        print(f'  {i+1}/121', flush=True)

print(f'walk: {total}帧抠图完成')
