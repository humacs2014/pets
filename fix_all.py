# -*- coding: utf-8 -*-
"""萨摩耶+背心三合一修复：
1. 体型统一：所有状态主体高度统一到idle基准(465px)，底边锚定
2. 实心化：消除半透明像素(alpha<200→0或255)，杜绝身体透明
3. 灰影清除：脖颈/尾巴/边缘的灰色半透明像素→实心或透明，不提白
4. 保留白色头部：不碰alpha>=200的白色像素的RGB
"""
import os, sys, glob
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, 'assets')
TARGET_H = 465  # idle基准高度

def get_content_bbox(arr):
    """获取alpha>10的内容区域"""
    alpha = arr[:,:,3]
    mask = alpha > 10
    ys = np.where(mask.any(1))[0]
    xs = np.where(mask.any(0))[0]
    if len(ys) == 0 or len(xs) == 0:
        return None
    return xs.min(), ys.min(), xs.max()+1, ys.max()+1

def solidify(arr):
    """消除半透明像素：alpha>=128→255, alpha<128→0"""
    alpha = arr[:,:,3]
    new_alpha = np.where(alpha >= 128, 255, 0).astype(np.uint8)
    arr[:,:,3] = new_alpha
    return arr

def remove_gray_halo(arr):
    """清除边缘灰影：alpha=0附近的灰色RGB像素→纯透明"""
    alpha = arr[:,:,3]
    rgb = arr[:,:,:3]
    
    # 找到alpha边缘区域（alpha 1-127的半透明像素）
    edge_mask = (alpha > 0) & (alpha < 200)
    if edge_mask.sum() == 0:
        return arr
    
    # 这些半透明像素的RGB往往是灰色（matte残留），直接清零
    arr[edge_mask, 3] = 0  # 设为完全透明
    
    # 再检查solid边缘外1px的灰色光晕
    solid_mask = alpha >= 200
    # 膨胀solid区域
    from scipy.ndimage import binary_dilation
    solid_dil = binary_dilation(solid_mask, iterations=2)
    halo_mask = solid_dil & ~solid_mask & (alpha == 0)
    # 检查halo区域是否有灰色RGB残留（alpha=0但RGB非0）
    halo_gray = halo_mask & ((rgb[:,:,0] > 30) | (rgb[:,:,1] > 30) | (rgb[:,:,2] > 30))
    if halo_gray.sum() > 0:
        # 这些是纯透明像素的RGB残留，清零
        arr[halo_gray, 0] = 0
        arr[halo_gray, 1] = 0
        arr[halo_gray, 2] = 0
    
    return arr

def fix_gray_neck_tail(arr):
    """定向清除脖颈和尾巴区域的灰色阴影（solid像素中的灰色）
    不动白色头部(alpha>=200且R>230,G>230,B>230的像素不动)"""
    alpha = arr[:,:,3]
    rgb = arr[:,:,:3].astype(np.int16)
    
    solid_mask = alpha >= 200
    if solid_mask.sum() == 0:
        return arr
    
    # 计算每个solid像素的饱和度
    r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    sat = maxc - minc  # 饱和度
    bright = (r + g + b) // 3  # 亮度
    
    # 灰影像素：饱和度低(饱和度<25)，亮度中等(100-230)，非纯白(亮度<235)
    # 这些是脖颈/尾巴的灰色阴影
    gray_shadow = solid_mask & (sat < 25) & (bright >= 100) & (bright < 230)
    
    if gray_shadow.sum() > 0:
        # 将灰色阴影向暖色调偏移（匹配毛发颜色），而非提白
        # 萨摩耶白毛的RGB约(210,195,175)，灰色阴影(200,195,184)
        # 向(210,195,175)偏移30%
        target_r, target_g, target_b = 210, 195, 175
        arr_rgb = arr[:,:,:3]
        old = arr_rgb[gray_shadow].astype(np.int16)
        new = old * 0.70 + np.array([target_r, target_g, target_b]) * 0.30
        arr[:,:,:3][gray_shadow] = np.clip(new, 0, 255).astype(np.uint8)
    
    return arr

def calibrate_height(state, target_h=TARGET_H):
    """统一所有状态主体高度到target_h，底边锚定"""
    fps = sorted(glob.glob(os.path.join(ASSETS, f'{state}_*')))
    if not fps:
        return 0
    
    # 先测量第一帧的内容高度
    img0 = Image.open(fps[0])
    arr0 = np.array(img0.convert('RGBA'))
    bbox = get_content_bbox(arr0)
    if bbox is None:
        return 0
    x0, y0, x1, y1 = bbox
    ch = y1 - y0
    cw = x1 - x0
    
    # 计算缩放系数
    f = target_h / ch
    # 钳制
    f = max(0.7, min(1.5, f))
    
    if abs(f - 1.0) < 0.01:
        # 不需要缩放
        pass
    
    done = 0
    for fp in fps:
        img = Image.open(fp).convert('RGBA')
        arr = np.array(img)
        h, w = arr.shape[:2]
        
        # 获取当前帧bbox
        bbox = get_content_bbox(arr)
        if bbox is None:
            continue
        bx0, by0, bx1, by1 = bbox
        bw, bh = bx1 - bx0, by1 - by0
        
        # 缩放
        nw, nh = max(2, int(round(bw * f))), max(2, int(round(bh * f)))
        
        # 钳制不超出canvas
        if nw > w or nh > h:
            g = min(w / nw, h / nh)
            nw, nh = int(nw * g), int(nh * g)
        
        # 裁剪内容
        content = img.crop(bbox)
        content = content.resize((nw, nh), Image.LANCZOS)
        
        # 底边锚定 + 水平居中
        cx = (bx0 + bx1) / 2.0
        nx0 = int(round(cx - nw / 2.0))
        ny1 = by1  # 底边不动
        ny0 = ny1 - nh
        
        canvas = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        canvas.paste(content, (nx0, ny0), content)
        
        # 保存
        ext = os.path.splitext(fp)[1]
        canvas.save(fp, 'WEBP' if ext == '.webp' else 'PNG', quality=95)
        done += 1
    
    print(f'{state:12s}: {done} frames, f={f:.3f} (h={ch}→{int(ch*f)})', flush=True)
    return done

def process_state(state):
    """对单个状态执行：1.实心化 2.灰影清除 3.灰颈尾修复"""
    fps = sorted(glob.glob(os.path.join(ASSETS, f'{state}_*')))
    if not fps:
        return 0
    
    fixed = 0
    for fp in fps:
        img = Image.open(fp).convert('RGBA')
        arr = np.array(img)
        
        # Step 1: 实心化（消除半透明）
        arr = solidify(arr)
        
        # Step 2: 灰影/光晕清除
        arr = remove_gray_halo(arr)
        
        # Step 3: 灰颈尾修复（不提白，向暖色偏移）
        arr = fix_gray_neck_tail(arr)
        
        # 保存
        ext = os.path.splitext(fp)[1]
        Image.fromarray(arr).save(fp, 'WEBP' if ext == '.webp' else 'PNG', quality=95)
        fixed += 1
    
    return fixed

if __name__ == '__main__':
    states = sys.argv[1:] if len(sys.argv) > 1 else [
        'idle', 'sit', 'sleep', 'bark', 'lick', 'happy', 'roll', 'dance',
        'stretch', 'beg', 'bath', 'pet', 'surprised', 'play_dead', 'eat',
        'walk', 'run', 'kiss', 'wave', 'type'
    ]
    
    total = 0
    # Phase 1: 体型校准
    print('=== Phase 1: Height calibration ===', flush=True)
    for st in states:
        total += calibrate_height(st)
    
    # Phase 2: 像素修复
    print('\n=== Phase 2: Solidify + Gray removal ===', flush=True)
    fixed_total = 0
    for st in states:
        fixed = process_state(st)
        fixed_total += fixed
        print(f'{st:12s}: {fixed} frames fixed', flush=True)
    
    print(f'\nTOTAL: {total} calibrated, {fixed_total} fixed', flush=True)
    print('FIX_DONE', flush=True)
