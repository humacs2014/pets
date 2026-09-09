#!/usr/bin/env python3
"""
安全灰影修复：只对边缘灰色光晕做暖色调偏移。
完全避开主体内部区域，只修复边缘的灰色阴影。
"""
import glob, numpy as np
from PIL import Image
import sys

def fix_gray_edge_safe(state):
    fps = sorted(glob.glob(f'assets/{state}_*'))
    if not fps:
        print(f'No frames for {state}')
        return 0
    
    fixed = 0
    for fp in fps:
        img = Image.open(fp)
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        arr = np.array(img, dtype=np.float32)
        alpha = arr[:,:,3]
        rgb = arr[:,:,:3]
        
        # 只处理不透明区域
        solid_mask = alpha >= 200
        if not solid_mask.any():
            continue
        
        # 找边缘：alpha在128-200之间的区域（半透明边缘）
        edge_mask = (alpha >= 128) & (alpha < 255)
        
        # 对边缘区域做膨胀-腐蚀操作找到边缘附近的像素
        from scipy.ndimage import binary_dilation, binary_erosion
        kernel = np.ones((5,5), dtype=bool)
        dilated = binary_dilation(solid_mask, structure=kernel)
        eroded = binary_erosion(solid_mask, structure=kernel)
        edge_zone = dilated & ~eroded
        
        # 在边缘区域内找灰色像素
        gray_mask = (
            edge_zone &
            solid_mask &
            (rgb[:,:,0] >= 150) & (rgb[:,:,0] <= 235) &
            (rgb[:,:,1] >= 150) & (rgb[:,:,1] <= 235) &
            (rgb[:,:,2] >= 150) & (rgb[:,:,2] <= 235) &
            (np.abs(rgb[:,:,0] - rgb[:,:,1]) < 15) &
            (np.abs(rgb[:,:,1] - rgb[:,:,2]) < 15)
        )
        
        if not gray_mask.any():
            continue
        
        # 对边缘灰色像素做暖色调偏移：R+12, B-12
        gray_rgb = rgb[gray_mask]
        r, g, b = gray_rgb[:,0], gray_rgb[:,1], gray_rgb[:,2]
        rgb[gray_mask, 0] = np.clip(r + 12, 0, 255)
        rgb[gray_mask, 2] = np.clip(b - 12, 0, 255)
        
        # 保存
        arr[:,:,:3] = rgb
        img = Image.fromarray(arr.astype(np.uint8), 'RGBA')
        img.save(fp, 'WEBP' if fp.endswith('.webp') else 'PNG')
        fixed += 1
    
    print(f'{state:8s}: {fixed} frames edge-gray-fixed')
    return fixed

if __name__ == '__main__':
    states = sys.argv[1:] if len(sys.argv) > 1 else ['roll']
    total = sum(fix_gray_edge_safe(s) for s in states)
    print(f'TOTAL: {total} frames fixed')