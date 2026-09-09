# -*- coding: utf-8 -*-
"""bath_walk_cutout.py — bath混合抠图 + walk rembg抠图（u2net更快）
bath: 白底抠图(保留浴盆) + rembg u2net前景mask OR合并(保留泡沫)
walk: rembg u2net标准抠图
"""
import os, numpy as np
from PIL import Image
import rembg

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(ROOT, 'frames')

# 使用u2net（更小更快，CPU也能跑）
session = rembg.new_session('u2net')

# ═══════ bath混合抠图 ═══════
RAW_BATH = os.path.join(ROOT, 'raw_frames', 'bath')
print('=== bath hybrid cutout (white_bg + rembg u2net) ===')
total = 0
for i in range(121):
    raw_fn = os.path.join(RAW_BATH, f'frame_{i+1:04d}.png')
    out_fn = os.path.join(FRAMES, f'bath_{i:03d}.png')
    if not os.path.exists(raw_fn):
        continue
    raw = np.array(Image.open(raw_fn).convert('RGBA'))
    rgb = raw[:,:,:3].astype(int)
    
    # 1. 白底抠图前景mask (均值>230 + 最低>215 = 背景)
    ch_mean = (rgb[:,:,0] + rgb[:,:,1] + rgb[:,:,2]) // 3
    ch_min = np.minimum(rgb[:,:,0], np.minimum(rgb[:,:,1], rgb[:,:,2]))
    white_fg = ~((ch_mean >= 230) & (ch_min >= 215))
    
    # 2. rembg前景mask
    raw_rgb = Image.fromarray(raw[:,:,:3])
    rembg_result = rembg.remove(raw_rgb, session=session)
    rembg_alpha = np.array(rembg_result.convert('RGBA'))[:,:,3]
    rembg_fg = rembg_alpha > 128
    
    # 3. OR合并
    fg = white_fg | rembg_fg
    
    result = np.zeros_like(raw)
    result[:,:,:3] = raw[:,:,:3]
    result[:,:,3] = np.where(fg, 255, 0).astype(np.uint8)
    
    Image.fromarray(result, 'RGBA').save(out_fn)
    total += 1
    if (i+1) % 30 == 0:
        print(f'  {i+1}/121', flush=True)
print(f'bath: {total}帧完成')

# ═══════ walk rembg抠图 ═══════
RAW_WALK = os.path.join(ROOT, 'raw_frames', 'walk')
print('=== walk rembg cutout (u2net) ===')
total = 0
for i in range(121):
    raw_fn = os.path.join(RAW_WALK, f'frame_{i+1:04d}.png')
    out_fn = os.path.join(FRAMES, f'walk_{i:03d}.png')
    if not os.path.exists(raw_fn):
        continue
    raw = np.array(Image.open(raw_fn).convert('RGBA'))
    raw_rgb = Image.fromarray(raw[:,:,:3])
    result_pil = rembg.remove(raw_rgb, session=session)
    result = np.array(result_pil.convert('RGBA'))
    # alpha二值化
    alpha = result[:,:,3].copy()
    alpha[alpha > 128] = 255
    alpha[alpha <= 128] = 0
    result[:,:,3] = alpha
    bg = alpha == 0
    for ch in range(3):
        result[bg, ch] = 0
    Image.fromarray(result, 'RGBA').save(out_fn)
    total += 1
    if (i+1) % 30 == 0:
        print(f'  {i+1}/121', flush=True)
print(f'walk: {total}帧完成')

print('BATH_WALK_CUTOUT_DONE')
