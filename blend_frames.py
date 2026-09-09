#!/usr/bin/env python3
"""
帧间加权混合去闪烁 v2：
- walk/idle: 3帧加权 (prev2=0.10, prev1=0.20, curr=0.70)
- roll: 5帧加权 (prev4=0.05, prev3=0.08, prev2=0.12, prev1=0.20, curr=0.55)
  roll闪烁极重，需要更激进的混合。
仅修改RGB，不动alpha。
"""
import glob, numpy as np, re
from PIL import Image
import sys

def _natural_sort(lst):
    """自然排序：walk_02 < walk_10 < walk_100"""
    def key(s):
        return [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', s)]
    return sorted(lst, key=key)

def blend_state(state, weights=None):
    fps = _natural_sort(glob.glob(f'assets/{state}_*'))
    if not fps:
        print(f'No frames for {state}')
        return 0
    
    n = len(fps)
    
    if weights is None:
        if state == 'roll':
            # 5帧加权
            weights = [0.05, 0.08, 0.12, 0.20, 0.55]
        else:
            # 3帧加权
            weights = [0.10, 0.20, 0.70]
    
    n_blend = len(weights)
    print(f'{state}: loading {n} frames, {n_blend}-frame blend weights={weights}...')
    
    frames = []
    for fp in fps:
        img = Image.open(fp).convert('RGBA')
        frames.append(np.array(img, dtype=np.float32))
    
    print(f'{state}: blending...')
    
    fixed = 0
    for i in range(n):
        arr = frames[i].copy()
        alpha = arr[:,:,3].copy()
        rgb = arr[:,:,:3].copy()
        
        # 确定可用的前帧数
        available = min(i + 1, n_blend)
        # 取最后available个权重，重新归一化
        used_weights = weights[n_blend - available:]
        w_sum = sum(used_weights)
        used_weights = [w / w_sum for w in used_weights]
        
        rgb_blend = np.zeros_like(rgb)
        for j, w in enumerate(used_weights):
            frame_idx = i - (available - 1 - j)
            rgb_blend += frames[frame_idx][:,:,:3] * w
        
        # 只在不透明区域混合
        solid = alpha >= 200
        for c in range(3):
            arr[:,:,c] = np.where(solid, rgb_blend[:,:,c], rgb[:,:,c])
        
        arr[:,:,3] = alpha
        
        img_out = Image.fromarray(arr.astype(np.uint8), 'RGBA')
        fmt = 'WEBP' if fps[i].endswith('.webp') else 'PNG'
        img_out.save(fps[i], fmt)
        fixed += 1
    
    print(f'{state}: {fixed} frames blended')
    return fixed

if __name__ == '__main__':
    # 支持 --heavy 标志对指定状态用5帧强混合（闪烁严重时）
    heavy = '--heavy' in sys.argv
    states = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not states:
        states = ['walk', 'roll', 'idle']
    
    heavy_states = {'dance', 'stretch', 'wave', 'sit', 'beg', 'bath'}
    
    total = 0
    for s in states:
        if heavy or s in heavy_states:
            w = [0.05, 0.08, 0.12, 0.20, 0.55]
        else:
            w = None
        total += blend_state(s, weights=w)
    print(f'TOTAL: {total} frames processed')