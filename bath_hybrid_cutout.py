# -*- coding: utf-8 -*-
"""bath_hybrid_cutout.py — bath混合抠图
策略：rembg识别前景（包括浴盆+泡沫+狗），白底抠图v3识别白色背景
合并：两者都认为是背景的像素→背景，任一认为是前景→前景
这样：白底抠图保留浴盆（非白色），rembg保留泡沫（前景区域内的白色）
"""
import os, subprocess, numpy as np
from PIL import Image
import rembg

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(ROOT, 'raw_frames', 'bath')
FRAMES = os.path.join(ROOT, 'frames')

session = rembg.new_session('isnet-general-use')
total = 0

for i in range(121):
    raw_fn = os.path.join(RAW_DIR, f'frame_{i+1:04d}.png')
    out_fn = os.path.join(FRAMES, f'bath_{i:03d}.png')
    if not os.path.exists(raw_fn):
        continue
    raw = np.array(Image.open(raw_fn).convert('RGBA'))
    rgb = raw[:,:,:3].astype(int)
    
    # 1. 白底抠图前景mask
    ch_mean = (rgb[:,:,0] + rgb[:,:,1] + rgb[:,:,2]) // 3
    ch_min = np.minimum(rgb[:,:,0], np.minimum(rgb[:,:,1], rgb[:,:,2]))
    white_bg = (ch_mean >= 230) & (ch_min >= 215)
    white_fg = ~white_bg  # 白底抠图认为的前景
    
    # 2. rembg前景mask
    rembg_result = rembg.remove(raw[:,:,:3], session=session)
    rembg_alpha = np.array(rembg_result[:,:,3]) if rembg_result.ndim == 3 else np.array(rembg_result)
    rembg_fg = rembg_alpha > 128
    
    # 3. 合并：任一认为是前景→前景（OR逻辑）
    fg = white_fg | rembg_fg
    
    # 4. 构建结果：保留原始RGB，alpha=255
    result = np.zeros_like(raw)
    result[:,:,:3] = raw[:,:,:3]
    result[:,:,3] = np.where(fg, 255, 0).astype(np.uint8)
    
    Image.fromarray(result, 'RGBA').save(out_fn)
    total += 1
    if (i+1) % 30 == 0:
        print(f'  {i+1}/121', flush=True)

print(f'bath: {total}帧混合抠图完成')
