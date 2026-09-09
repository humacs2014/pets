# -*- coding: utf-8 -*-
"""white_bg_cutout_v2.py — 白底抠图v2（更精确的背景检测）
问题：v1用WHITE_THRESH=240单通道阈值，type源视频背景R≈233被保留成灰色
解决：三通道均值>230+单通道最低>220=背景，更宽松但仍可靠
"""
import os, subprocess, numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
VIDEOS = os.path.join(ROOT, 'videos')
FRAMES = os.path.join(ROOT, 'frames')

STATES_TO_PROCESS = ['type', 'bath', 'kiss']

def extract_white_bg(raw_arr):
    """白底抠图：用三通道均值+最低通道判据"""
    rgb = raw_arr[:, :, :3].astype(int)
    r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
    mean_rgb = ((r + g + b) / 3.0).astype(int)
    mn = np.minimum(np.minimum(r, g), b)
    
    # 背景条件：三通道均值>=230 且 最低通道>=220
    white_mask = (mean_rgb >= 230) & (mn >= 220)
    
    result = raw_arr.copy()
    result[:, :, 3] = np.where(white_mask, 0, 255).astype(np.uint8)
    for ch in range(3):
        result[white_mask, ch] = 0
    return result

for state in STATES_TO_PROCESS:
    print(f'=== {state} 白底抠图v2 ===')
    video_fn = os.path.join(VIDEOS, f'{state}.mp4')
    
    raw_dir = os.path.join(ROOT, f'_raw_{state}')
    os.makedirs(raw_dir, exist_ok=True)
    
    subprocess.run(['ffmpeg', '-i', video_fn, '-q:v', '2', 
                    os.path.join(raw_dir, 'f_%05d.png'), '-y'],
                   capture_output=True)
    
    raw_files = sorted([f for f in os.listdir(raw_dir) if f.endswith('.png')])
    print(f'  抽帧: {len(raw_files)}帧')
    
    for idx, fn in enumerate(raw_files):
        raw = np.array(Image.open(os.path.join(raw_dir, fn)).convert('RGBA'))
        result = extract_white_bg(raw)
        out_fn = os.path.join(FRAMES, f'{state}_{idx:03d}.png')
        Image.fromarray(result, 'RGBA').save(out_fn)
        if (idx + 1) % 30 == 0:
            print(f'  {idx+1}/{len(raw_files)}', flush=True)
    
    import shutil
    shutil.rmtree(raw_dir, ignore_errors=True)
    print(f'{state}: 完成')

print('WHITE_BG_CUTOUT_V2_DONE')
