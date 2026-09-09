# -*- coding: utf-8 -*-
"""white_bg_cutout.py — 白底抠图（保留狗+物体）
对于type(键盘)、bath(浴盆)等含物体的动作，不做前景分割，
只去除纯白背景，保留狗和所有物体。
策略：RGB接近白色(>240)的区域设为透明，其他保留原始RGB+alpha=255
"""
import os, numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
VIDEOS = os.path.join(ROOT, 'videos')
FRAMES = os.path.join(ROOT, 'frames')

STATES_TO_PROCESS = ['type', 'bath']  # 需要保留物体的动作

WHITE_THRESH = 240  # RGB三通道都>240视为白色背景

def extract_white_bg(raw_arr):
    """白底抠图：白色区域alpha=0，其他alpha=255"""
    rgb = raw_arr[:, :, :3].astype(int)
    r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
    # 白色背景：三通道都接近255
    white_mask = (r >= WHITE_THRESH) & (g >= WHITE_THRESH) & (b >= WHITE_THRESH)
    
    result = raw_arr.copy()
    alpha = np.where(white_mask, 0, 255).astype(np.uint8)
    result[:, :, 3] = alpha
    # 白色区域的RGB也清零（避免透明区域有残留色）
    for ch in range(3):
        result[white_mask, ch] = 0
    return result

for state in STATES_TO_PROCESS:
    print(f'=== {state} 白底抠图 ===')
    video_fn = os.path.join(VIDEOS, f'{state}.mp4')
    
    # 从源视频抽帧
    raw_dir = os.path.join(ROOT, f'_raw_{state}')
    os.makedirs(raw_dir, exist_ok=True)
    
    import subprocess
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
    
    # 清理临时文件
    import shutil
    shutil.rmtree(raw_dir, ignore_errors=True)
    print(f'{state}: 完成')

print('WHITE_BG_CUTOUT_DONE')
