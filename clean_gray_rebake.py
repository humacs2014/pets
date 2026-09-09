# -*- coding: utf-8 -*-
"""clean_gray_semitrans.py — 清理半透明灰色脏斑
对frames/中每帧的灰色半透明像素(低彩度+半透明+中灰)做清理：
1. 灰色半透明像素的alpha清零(变透明)
2. 对alpha=255的灰色边缘做dehalo去污染(复用dehalo_hard逻辑)
3. 输出到frames/原地替换
4. 然后rebake到assets/
"""
import os, sys, numpy as np
from PIL import Image
from scipy.ndimage import binary_erosion, binary_dilation

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(ROOT, 'frames')
ASSETS = os.path.join(ROOT, 'assets')

STATES = ['idle','walk','run','eat','bark','sleep','sit','lick','happy',
          'roll','dance','stretch','beg','bath','surprised','play_dead',
          'pet','kiss','wave','type']

CANVAS_W, CANVAS_H = 1088, 832
TARGET_SUBJECT_H = 680

def clean_semitrans_gray(arr):
    """清理半透明灰色脏斑：alpha清零"""
    r, g, b, a = arr[:,:,0], arr[:,:,1], arr[:,:,2], arr[:,:,3]
    mx = np.maximum(np.maximum(r.astype(int), g.astype(int)), b.astype(int))
    mn = np.minimum(np.minimum(r.astype(int), g.astype(int)), b.astype(int))
    gray_mask = (a >= 40) & (a <= 230) & ((mx - mn) < 30) & (mn >= 80) & (mx <= 220)
    cleaned = arr.copy()
    cleaned[gray_mask, 3] = 0  # alpha清零
    return cleaned, gray_mask.sum()

def dehalo_opaque_gray(arr, erode=4):
    """alpha=255灰色边缘去污染（迭代扩散替换）"""
    al = arr[:,:,3]
    rgb = arr[:,:,:3].astype(np.float32)
    
    lum = rgb.mean(axis=2)
    mx = rgb.max(axis=2); mn = rgb.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    
    opaque = al == 255
    interior = binary_erosion(opaque, iterations=erode)
    edge = opaque & ~interior
    
    grey_mask = edge & (lum >= 140) & (lum <= 245) & (sat < 0.18)
    
    if not grey_mask.any():
        return arr, 0
    
    filled = opaque & ~grey_mask
    result_rgb = rgb.copy()
    
    for iteration in range(erode * 8):
        expanded = binary_dilation(filled, iterations=1) & ~filled & grey_mask
        if not expanded.any():
            break
        for ch in range(3):
            ch_data = result_rgb[:,:,ch]
            padded = np.pad(ch_data, 1, mode='edge')
            padded_mask = np.pad(filled.astype(np.float32), 1, mode='constant')
            neighbor_sum = (padded[:-2,1:-1] * padded_mask[:-2,1:-1] + 
                          padded[2:,1:-1] * padded_mask[2:,1:-1] + 
                          padded[1:-1,:-2] * padded_mask[1:-1,:-2] + 
                          padded[1:-1,2:] * padded_mask[1:-1,2:])
            neighbor_cnt = (padded_mask[:-2,1:-1] + padded_mask[2:,1:-1] + 
                          padded_mask[1:-1,:-2] + padded_mask[1:-1,2:])
            valid = expanded & (neighbor_cnt > 0)
            result_rgb[valid, ch] = (neighbor_sum[valid] / neighbor_cnt[valid])
        filled = filled | expanded
    
    grey_count = grey_mask.sum()
    result = arr.copy()
    result[:,:,:3] = result_rgb.astype(np.uint8)
    return result, grey_count

def rebake_state(state):
    """rebake: 二值化alpha, tight bbox裁剪, 统一680px高度"""
    max_bh = 0
    frames_data = []
    
    for i in range(121):
        fn = os.path.join(FRAMES, f'{state}_{i:03d}.png')
        if not os.path.exists(fn):
            continue
        arr = np.array(Image.open(fn).convert('RGBA'))
        a = arr[:, :, 3]
        a = np.where(a >= 128, 255, 0).astype(np.uint8)
        arr[:, :, 3] = a
        
        mask = a > 10
        if mask.any():
            rows = np.any(mask, axis=1)
            cols = np.any(mask, axis=0)
            y0 = int(np.argmax(rows))
            y1 = int(len(rows) - np.argmax(rows[::-1]))
            x0 = int(np.argmax(cols))
            x1 = int(len(cols) - np.argmax(cols[::-1]))
            bh = y1 - y0
        else:
            y0 = y1 = x0 = x1 = 0
            bh = 0
        
        if bh > max_bh:
            max_bh = bh
        frames_data.append((i, arr, (x0, y0, x1, y1), bh))
    
    if max_bh == 0:
        return 0
    
    scale = TARGET_SUBJECT_H / max_bh
    out_count = 0
    for i, arr, (x0, y0, x1, y1), bh in frames_data:
        canvas = Image.new('RGBA', (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        if bh > 0:
            content = arr[y0:y1, x0:x1].copy()
            content_im = Image.fromarray(content, 'RGBA')
            ch, cw = content.shape[:2]
            new_h = max(2, int(round(ch * scale)))
            new_w = max(2, int(round(cw * scale)))
            content_im = content_im.resize((new_w, new_h), Image.LANCZOS)
            paste_y = CANVAS_H - new_h
            paste_x = (CANVAS_W - new_w) // 2
            canvas.paste(content_im, (paste_x, paste_y), content_im)
        out_fn = os.path.join(ASSETS, f'{state}_{i:03d}.png')
        canvas.save(out_fn)
        out_count += 1
    
    return out_count

# Step 1: 清理frames/中的灰色
print('=== Step 1: 清理半透明灰色 + dehalo ===')
for state in STATES:
    total_semi = 0
    total_halo = 0
    for i in range(121):
        fn = os.path.join(FRAMES, f'{state}_{i:03d}.png')
        if not os.path.exists(fn):
            continue
        arr = np.array(Image.open(fn).convert('RGBA'))
        # 先清半透明灰色
        arr, semi_n = clean_semitrans_gray(arr)
        total_semi += semi_n
        # 再做opaque灰色边缘去污
        arr, halo_n = dehalo_opaque_gray(arr)
        total_halo += halo_n
        Image.fromarray(arr, 'RGBA').save(fn)
    print(f'{state}: 清理半透明灰色={total_semi}, dehalo={total_halo}', flush=True)

# Step 2: rebake
print('\n=== Step 2: rebake ===')
for state in STATES:
    n = rebake_state(state)
    print(f'{state}: {n} frames', flush=True)

print('\nCLEAN_AND_REBAKE_DONE')
