# -*- coding: utf-8 -*-
"""阶段5c: alpha=255灰色边缘去污染。
v22i: rembg在alpha=255的边缘像素中保留了原始背景RGB（灰色），
导致透明背景下显示灰色光晕。

策略：
1. 找到alpha=255且RGB灰色的边缘像素
2. 用最近的不透明非灰色邻居的颜色替换

用法: python dehalo_hard.py [state ...]
"""
import sys, os, glob, re
import numpy as np
from PIL import Image
from scipy.ndimage import binary_erosion, binary_dilation, label

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, 'assets')

def natural_sort(l):
    return sorted(l, key=lambda s: [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', s)])

def dehalo_hard(a, grey_lum_lo=140, grey_lum_hi=245, grey_sat_hi=0.18, erode=4):
    """对alpha=255的灰色边缘像素做颜色去污染。
    灰色像素的RGB替换为最近非灰色不透明像素的颜色（迭代扩散）。"""
    al = a[:,:,3]
    rgb = a[:,:,:3].astype(np.float32)
    
    # 识别灰色像素：alpha=255 + lum在灰区 + 低饱和度
    lum = rgb.mean(axis=2)
    mx = rgb.max(axis=2); mn = rgb.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    
    opaque = al == 255
    interior = binary_erosion(opaque, iterations=erode)
    edge = opaque & ~interior
    
    grey_mask = edge & (lum >= grey_lum_lo) & (lum <= grey_lum_hi) & (sat < grey_sat_hi)
    
    if not grey_mask.any():
        return a, 0
    
    # 用迭代扩散替换灰色像素颜色
    # 从非灰色不透明像素开始，每次向外扩展1px填充灰色邻居
    filled = opaque & ~grey_mask  # 非灰色不透明像素作为种子
    result_rgb = rgb.copy()
    
    for iteration in range(erode * 8):
        # 找到filled的1px外邻域中的灰色像素
        expanded = binary_dilation(filled, iterations=1) & ~filled & grey_mask
        if not expanded.any():
            break
        # 用filled邻居的中值RGB填充
        for ch in range(3):
            ch_data = result_rgb[:,:,ch]
            # 4-邻居均值
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
    result = a.copy()
    result[:,:,:3] = result_rgb.astype(np.uint8)
    return result, grey_count


if __name__ == '__main__':
    states = sys.argv[1:] or ['idle', 'walk', 'roll']
    
    for st in states:
        fps = natural_sort(glob.glob(os.path.join(ASSETS, f'{st}_*.webp')))
        if not fps:
            print(f'{st}: no assets found')
            continue
        
        total_grey = 0
        for i, fp in enumerate(fps):
            im = Image.open(fp).convert('RGBA')
            a = np.asarray(im).copy()
            out, grey_count = dehalo_hard(a)
            total_grey += grey_count
            if grey_count > 0:
                Image.fromarray(out, 'RGBA').save(fp)
            if (i + 1) % 30 == 0:
                print(f'  {st}: {i+1}/{len(fps)} processed', flush=True)
        
        print(f'{st}: {total_grey} grey edge pixels decontaminated across {len(fps)} frames')
    
    print('DEHALO_HARD_DONE')
