# -*- coding: utf-8 -*-
"""clean_all_gray_rebake.py — 全量灰色替换+rebake
Step 1: 对frames/全部20个动作做灰色半透明像素替换(邻居扩散)
Step 2: rebake统一680px到assets/
"""
import os, numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(ROOT, 'frames')
ASSETS = os.path.join(ROOT, 'assets')

STATES = ['idle','walk','run','eat','bark','sleep','sit','lick','happy',
          'roll','dance','stretch','beg','bath','surprised','play_dead',
          'pet','kiss','wave','type']

CANVAS_W, CANVAS_H = 1088, 832
TARGET_SUBJECT_H = 680

def is_gray_mask(arr):
    r, g, b, a = arr[:,:,0].astype(int), arr[:,:,1].astype(int), arr[:,:,2].astype(int), arr[:,:,3].astype(int)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    return (a >= 40) & (a <= 230) & ((mx - mn) < 30) & (mx <= 200) & (mn >= 80)

def replace_gray_with_neighbor(arr, max_iter=300):
    gray = is_gray_mask(arr)
    if not gray.any():
        return arr, 0
    result = arr.copy()
    filled = (arr[:,:,3] > 0) & ~gray
    count = int(gray.sum())
    for _ in range(max_iter):
        expanded = binary_dilation(filled, iterations=1) & ~filled & gray
        if not expanded.any():
            break
        for ch in range(3):
            ch_data = result[:,:,ch].astype(np.float32)
            padded = np.pad(ch_data, 1, mode='edge')
            padded_mask = np.pad(filled.astype(np.float32), 1, mode='constant')
            ns = (padded[:-2,1:-1]*padded_mask[:-2,1:-1] + padded[2:,1:-1]*padded_mask[2:,1:-1] +
                  padded[1:-1,:-2]*padded_mask[1:-1,:-2] + padded[1:-1,2:]*padded_mask[1:-1,2:])
            nc = (padded_mask[:-2,1:-1] + padded_mask[2:,1:-1] + padded_mask[1:-1,:-2] + padded_mask[1:-1,2:])
            valid = expanded & (nc > 0)
            result[valid, ch] = np.clip(ns[valid] / nc[valid], 0, 255).astype(np.uint8)
        filled = filled | expanded
    return result, count

def rebake_state(state):
    max_bh = 0
    frames_data = []
    for i in range(121):
        fn = os.path.join(FRAMES, f'{state}_{i:03d}.png')
        if not os.path.exists(fn): continue
        arr = np.array(Image.open(fn).convert('RGBA'))
        a = arr[:,:,3]; a = np.where(a >= 128, 255, 0).astype(np.uint8); arr[:,:,3] = a
        mask = a > 10
        if mask.any():
            rows, cols = np.any(mask, axis=1), np.any(mask, axis=0)
            y0, y1 = int(np.argmax(rows)), int(len(rows) - np.argmax(rows[::-1]))
            x0, x1 = int(np.argmax(cols)), int(len(cols) - np.argmax(cols[::-1]))
            bh = y1 - y0
        else:
            y0=y1=x0=x1=bh=0
        if bh > max_bh: max_bh = bh
        frames_data.append((i, arr, (x0,y0,x1,y1), bh))
    if max_bh == 0: return 0
    scale = TARGET_SUBJECT_H / max_bh
    for i, arr, (x0,y0,x1,y1), bh in frames_data:
        canvas = Image.new('RGBA', (CANVAS_W, CANVAS_H), (0,0,0,0))
        if bh > 0:
            content = arr[y0:y1, x0:x1].copy()
            im = Image.fromarray(content, 'RGBA').resize(
                (max(2, int(round((x1-x0)*scale))), max(2, int(round(bh*scale)))), Image.LANCZOS)
            canvas.paste(im, ((CANVAS_W-im.width)//2, CANVAS_H-im.height), im)
        canvas.save(os.path.join(ASSETS, f'{state}_{i:03d}.png'))
    return len(frames_data)

# Step 1
print('=== Step 1: 灰色替换 ===')
for state in STATES:
    total = 0
    for i in range(121):
        fn = os.path.join(FRAMES, f'{state}_{i:03d}.png')
        if not os.path.exists(fn): continue
        arr = np.array(Image.open(fn).convert('RGBA'))
        arr, n = replace_gray_with_neighbor(arr)
        if n > 0:
            total += n
            Image.fromarray(arr, 'RGBA').save(fn)
    print(f'{state}: 替换{total}px', flush=True)

# Step 2
print('\n=== Step 2: rebake ===')
for state in STATES:
    n = rebake_state(state)
    print(f'{state}: {n} frames', flush=True)

print('\nALL_DONE')
