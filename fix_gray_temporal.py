#!/usr/bin/env python3
"""
帧间时域稳定化：对灰色像素做时间平滑，消除闪烁。
完全不碰alpha，只改RGB。
"""
import glob, numpy as np
from PIL import Image
import sys

def temporal_stabilize(state, window=3):
    fps = sorted(glob.glob(f'assets/{state}_*'))
    if not fps:
        print(f'No frames for {state}')
        return 0
    
    frames = [np.array(Image.open(fp).convert('RGBA')) for fp in fps]
    n = len(frames)
    
    # 找到所有帧的不透明区域交集
    solid_masks = [f[:,:,3] >= 200 for f in frames]
    common_solid = np.all(solid_masks, axis=0)
    
    if not common_solid.any():
        print(f'{state}: no common solid pixels')
        return 0
    
    # 检测灰色像素：R≈G≈B且不纯白不纯黑
    gray_mask = (
        common_solid &
        (frames[0][:,:,0] >= 140) & (frames[0][:,:,0] <= 230) &
        (np.abs(frames[0][:,:,0] - frames[0][:,:,1]) < 20) &
        (np.abs(frames[0][:,:,1] - frames[0][:,:,2]) < 20)
    )
    
    if not gray_mask.any():
        print(f'{state}: no gray pixels to stabilize')
        return 0
    
    print(f'{state}: {gray_mask.sum()} gray pixels to stabilize')
    
    fixed = 0
    for i in range(n):
        arr = frames[i].copy()
        rgb = arr[:,:,:3].astype(np.float32)
        
        # 获取窗口内帧的灰色像素RGB值
        start = max(0, i - window//2)
        end = min(n, i + window//2 + 1)
        
        gray_rgbs = []
        for j in range(start, end):
            gray_rgbs.append(frames[j][:,:,:3][gray_mask].astype(np.float32))
        
        # 计算窗口平均值
        mean_rgb = np.mean(gray_rgbs, axis=0)
        
        # 对灰色像素用窗口平均值替代
        rgb[gray_mask] = mean_rgb
        arr[:,:,:3] = rgb.astype(np.uint8)
        
        img = Image.fromarray(arr, 'RGBA')
        img.save(fps[i], 'WEBP' if fps[i].endswith('.webp') else 'PNG')
        fixed += 1
    
    print(f'{state}: {fixed} frames temporal-stabilized (window={window})')
    return fixed

if __name__ == '__main__':
    states = sys.argv[1:] if len(sys.argv) > 1 else ['roll']
    total = sum(temporal_stabilize(s) for s in states)
    print(f'TOTAL: {total} frames fixed')