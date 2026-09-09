# -*- coding: utf-8 -*-
"""clean_gray_neighbor.py — 灰色半透明像素：用相邻非灰颜色替换RGB
针对BEN2在背心白色布料区域产生的半透明灰色残留(alpha 129-230, R≈G≈B, lum<150)
策略：检测灰色半透明像素 → 迭代扩散用最近非灰邻居RGB替换 → alpha保留不变
"""
import os, numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(ROOT, 'frames')

def is_gray_mask(arr):
    """检测灰色半透明脏斑：低彩度+半透明+中灰(排除正常米白布料)
    正常背心米白: lum>200, R-B>20
    抠图灰色残留: lum<150, R≈G≈B
    """
    r, g, b, a = arr[:,:,0].astype(int), arr[:,:,1].astype(int), arr[:,:,2].astype(int), arr[:,:,3].astype(int)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    # 原始条件
    base = (a >= 40) & (a <= 230) & ((mx - mn) < 30)
    # 加亮度上限排除正常米白布料(mx<=200)
    return base & (mx <= 200) & (mn >= 80)

def replace_gray_with_neighbor(arr, max_iter=120):
    """用相邻非灰颜色替换灰色像素RGB，迭代扩散"""
    gray = is_gray_mask(arr)
    if not gray.any():
        return arr, 0
    
    result = arr.copy()
    filled = ~gray  # 非灰像素作为种子
    count = int(gray.sum())
    
    for _ in range(max_iter):
        expanded = binary_dilation(filled, iterations=1) & ~filled & gray
        if not expanded.any():
            break
        for ch in range(3):
            ch_data = result[:,:,ch].astype(np.float32)
            padded = np.pad(ch_data, 1, mode='edge')
            padded_mask = np.pad(filled.astype(np.float32), 1, mode='constant')
            neighbor_sum = (padded[:-2,1:-1] * padded_mask[:-2,1:-1] + 
                          padded[2:,1:-1] * padded_mask[2:,1:-1] + 
                          padded[1:-1,:-2] * padded_mask[1:-1,:-2] + 
                          padded[1:-1,2:] * padded_mask[1:-1,2:])
            neighbor_cnt = (padded_mask[:-2,1:-1] + padded_mask[2:,1:-1] + 
                          padded_mask[1:-1,:-2] + padded_mask[1:-1,2:])
            valid = expanded & (neighbor_cnt > 0)
            result[valid, ch] = np.clip(neighbor_sum[valid] / neighbor_cnt[valid], 0, 255).astype(np.uint8)
        filled = filled | expanded
    
    return result, count

# 只跑roll测试
state = 'roll'
print(f'=== {state} 灰色像素邻居替换测试 ===')
total = 0
for i in range(121):
    fn = os.path.join(FRAMES, f'{state}_{i:03d}.png')
    arr = np.array(Image.open(fn).convert('RGBA'))
    arr, n = replace_gray_with_neighbor(arr)
    if n > 0:
        total += n
        Image.fromarray(arr, 'RGBA').save(fn)
    if (i + 1) % 30 == 0:
        print(f'  {i+1}/121', flush=True)

print(f'{state}: 替换了{total}个灰色像素')

# 验证
print(f'\\n=== 替换后验证(关键帧037-039) ===')
for idx in [37, 38, 39]:
    fn = os.path.join(FRAMES, f'{state}_{idx:03d}.png')
    arr = np.array(Image.open(fn).convert('RGBA'))
    remain = is_gray_mask(arr).sum()
    print(f'  roll_{idx:03d}: 剩余灰色像素={remain}')

# 全帧验证
total_remain = 0
for i in range(121):
    arr = np.array(Image.open(f'frames/{state}_{i:03d}.png').convert('RGBA'))
    total_remain += is_gray_mask(arr).sum()
print(f'  全帧剩余: {total_remain}')
print('DONE')
