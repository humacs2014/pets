# -*- coding: utf-8 -*-
"""BEN2 vs rembg 对比测试
测试目标：
1. BEN2在白色背景(金毛背心宠物)上的抠图质量 vs rembg
2. BEN2在白色背景(萨摩耶)上的抠图质量 vs rembg  
3. 速度对比
4. 空洞/白色残留/边缘质量对比
"""
import os, sys, time, glob
import numpy as np
from PIL import Image
from scipy.ndimage import binary_fill_holes

ROOT = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(ROOT, '_ben2_results')
os.makedirs(RESULTS, exist_ok=True)

# ===== rembg baseline =====
def rembg_remove(img_path):
    """标准rembg抠图"""
    from rembg import remove
    import cv2
    cv_img = cv2.imread(img_path)
    t0 = time.time()
    rgba = remove(cv_img)
    dt = time.time() - t0
    result = Image.fromarray(cv2.cvtColor(rgba, cv2.COLOR_BGRA2RGBA))
    return result, dt

# ===== BEN2 =====
_ben2_model = None
def ben2_remove(img_path, refine=False):
    """BEN2抠图"""
    global _ben2_model
    if _ben2_model is None:
        import torch
        from ben2 import AutoModel
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        print(f'BEN2 device: {device}', flush=True)
        t0 = time.time()
        _ben2_model = AutoModel.from_pretrained('PramaLLC/BEN2')
        _ben2_model = _ben2_model.to(device).eval()
        print(f'BEN2 loaded in {time.time()-t0:.1f}s', flush=True)
    
    raw = Image.open(img_path).convert('RGB')
    t0 = time.time()
    foreground = _ben2_model.inference(raw, refine_foreground=refine)
    dt = time.time() - t0
    return foreground, dt

# ===== 质量分析 =====
def analyze_mask(img_rgba, name=""):
    """分析抠图质量"""
    arr = np.array(img_rgba.convert('RGBA'))
    al = arr[:,:,3]
    
    # 前景像素
    fg = (al > 128).sum()
    
    # 空洞检测
    core = al > 128
    body = binary_fill_holes(core)
    holes = body & ~core
    
    # 主体白色区域（背心高光/白毛残留）
    rgb = arr[:,:,:3].astype(float)
    mx = np.maximum(np.maximum(rgb[:,:,0], rgb[:,:,1]), rgb[:,:,2])
    mn = np.minimum(np.minimum(rgb[:,:,0], rgb[:,:,1]), rgb[:,:,2])
    V = mx; S = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    body_white = (al > 128) & (V >= 230) & (S <= 0.15)
    
    # 半透明像素（边缘质量指标）
    semi_transparent = (al > 0) & (al < 255) & (al > 10)
    
    # 边缘锯齿/粗糙度（alpha边缘像素的梯度方差）
    from scipy.ndimage import sobel
    al_float = al.astype(float) / 255.0
    sx = sobel(al_float, axis=1)
    sy = sobel(al_float, axis=0)
    edge_pixels = (np.abs(sx) + np.abs(sy)) > 0.1
    edge_count = edge_pixels.sum()
    
    print(f'  {name}: fg={fg}px, holes={holes.sum()}px, body_white={body_white.sum()}px, '
          f'semi_trans={semi_transparent.sum()}px, edge={edge_count}px')
    return {
        'fg': fg, 'holes': holes.sum(), 'body_white': body_white.sum(),
        'semi_trans': semi_transparent.sum(), 'edge': edge_count
    }

# ===== 测试 =====
test_cases = [
    # (label, image_path)
    ('golden_vest_idle', os.path.join(ROOT, 'frames', 'idle_00.png')),
    ('golden_vest_type', os.path.join(ROOT, 'frames', 'type_00.png')),
    ('golden_vest_stretch_raw', os.path.join(ROOT, '_tmp_stretch_108_raw.png')),
    ('samoyed_idle', os.path.join(ROOT, '..', 'samoyed_desktop_pet', 'frames', 'idle_00.png')),
]

# 找更多有代表性的帧（白背心闪烁最严重的）
for state in ['bark', 'dance', 'beg', 'sit', 'wave']:
    fs = sorted(glob.glob(os.path.join(ROOT, 'frames', f'{state}_*.png')))
    if fs:
        mid = len(fs) // 2
        test_cases.append((f'golden_vest_{state}_mid', fs[mid]))

print(f'=== {len(test_cases)} test cases ===')
for label, path in test_cases:
    exists = '✓' if os.path.exists(path) else '✗'
    print(f'  {exists} {label}: {path}')

# Run rembg baseline first (no GPU needed)
print('\n===== REMBG BASELINE =====')
rembg_results = {}
for label, path in test_cases:
    if not os.path.exists(path):
        print(f'  SKIP {label} (file not found)')
        continue
    print(f'\n--- {label} (rembg) ---')
    try:
        result, dt = rembg_remove(path)
        out_path = os.path.join(RESULTS, f'{label}_rembg.png')
        result.save(out_path)
        stats = analyze_mask(result, 'rembg')
        rembg_results[label] = {'time': dt, 'stats': stats, 'path': out_path}
        print(f'  time={dt:.1f}s, saved {out_path}')
    except Exception as e:
        print(f'  ERROR: {e}')

# Run BEN2 (needs GPU for reasonable speed)
print('\n===== BEN2 =====')
ben2_results = {}
ben2_refine_results = {}
for label, path in test_cases:
    if not os.path.exists(path):
        print(f'  SKIP {label} (file not found)')
        continue
    print(f'\n--- {label} (BEN2) ---')
    try:
        # Standard inference
        result, dt = ben2_remove(path, refine=False)
        out_path = os.path.join(RESULTS, f'{label}_ben2.png')
        result.save(out_path)
        stats = analyze_mask(result, 'BEN2')
        ben2_results[label] = {'time': dt, 'stats': stats, 'path': out_path}
        print(f'  time={dt:.1f}s, saved {out_path}')
        
        # Refined inference
        result_r, dt_r = ben2_remove(path, refine=True)
        out_path_r = os.path.join(RESULTS, f'{label}_ben2_refined.png')
        result_r.save(out_path_r)
        stats_r = analyze_mask(result_r, 'BEN2_refined')
        ben2_refine_results[label] = {'time': dt_r, 'stats': stats_r, 'path': out_path_r}
        print(f'  refined time={dt_r:.1f}s, saved {out_path_r}')
    except Exception as e:
        print(f'  ERROR: {e}')

# Summary comparison
print('\n===== SUMMARY =====')
print(f'{"label":<30s} | {"rembg holes":>12s} | {"BEN2 holes":>12s} | {"BEN2ref holes":>14s} | {"rembg white":>12s} | {"BEN2 white":>12s} | {"rembg time":>12s} | {"BEN2 time":>12s}')
print('-' * 130)
for label, _ in test_cases:
    r_h = rembg_results.get(label, {}).get('stats', {}).get('holes', '?')
    b_h = ben2_results.get(label, {}).get('stats', {}).get('holes', '?')
    br_h = ben2_refine_results.get(label, {}).get('stats', {}).get('holes', '?')
    r_w = rembg_results.get(label, {}).get('stats', {}).get('body_white', '?')
    b_w = ben2_results.get(label, {}).get('stats', {}).get('body_white', '?')
    r_t = f'{rembg_results.get(label, {}).get("time", 0):.1f}s' if label in rembg_results else '?'
    b_t = f'{ben2_results.get(label, {}).get("time", 0):.1f}s' if label in ben2_results else '?'
    print(f'{label:<30s} | {r_h:>12} | {b_h:>12} | {br_h:>14} | {r_w:>12} | {b_w:>12} | {r_t:>12} | {b_t:>12}')

print('\nAll results saved to:', RESULTS)
