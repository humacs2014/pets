# -*- coding: utf-8 -*-
"""white_bg_cutout_v3.py — 白底抠图v3（精确保留交互物体）
type/bath/kiss使用白底抠图：只去除白色背景区域，保留狗+键盘/浴盆
策略：源视频是白底，键盘/浴盆/泡沫都不是纯白→白底检测精确区分
阈值：三通道均值>230 + 最低通道>215 = 背景（更宽松以覆盖浅灰过渡）
"""
import os, subprocess, numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
VIDEOS = os.path.join(ROOT, 'videos')
RAW = os.path.join(ROOT, 'raw_frames')
FRAMES = os.path.join(ROOT, 'frames')

# 需要处理的动作（白底+含交互物体）
STATES = {
    'type': {'video': 'type.mp4', 'white_thresh_mean': 230, 'white_thresh_min': 215},
    'bath': {'video': 'bath.mp4', 'white_thresh_mean': 230, 'white_thresh_min': 215},
    'kiss': {'video': 'kiss.mp4', 'white_thresh_mean': 230, 'white_thresh_min': 215},
}

def extract_frames(video_path, state):
    """从视频抽帧到raw_frames/<state>/"""
    raw_dir = os.path.join(RAW, state)
    os.makedirs(raw_dir, exist_ok=True)
    for f in os.listdir(raw_dir):
        os.remove(os.path.join(raw_dir, f))
    subprocess.run(['ffmpeg', '-y', '-i', video_path, '-vf', 'fps=24',
                    os.path.join(raw_dir, 'frame_%04d.png')],
                   check=True, capture_output=True)
    n = len([f for f in os.listdir(raw_dir) if f.endswith('.png')])
    print(f'{state}: {n} frames extracted from video')
    return raw_dir

def white_bg_cutout(raw_dir, state, thresh_mean, thresh_min):
    """白底抠图：只去除接近白色的背景，保留所有非白内容"""
    total = 0
    for i in range(121):
        raw_fn = os.path.join(raw_dir, f'frame_{i+1:04d}.png')
        out_fn = os.path.join(FRAMES, f'{state}_{i:03d}.png')
        if not os.path.exists(raw_fn):
            continue
        img = Image.open(raw_fn).convert('RGBA')
        arr = np.array(img)
        rgb = arr[:,:,:3].astype(int)
        
        # 背景检测：三通道均值>thresh_mean AND 最低通道>thresh_min
        ch_mean = (rgb[:,:,0] + rgb[:,:,1] + rgb[:,:,2]) // 3
        ch_min = np.minimum(rgb[:,:,0], np.minimum(rgb[:,:,1], rgb[:,:,2]))
        bg_mask = (ch_mean >= thresh_mean) & (ch_min >= thresh_min)
        
        # 前景保留原始RGB，alpha=255
        result = arr.copy()
        result[:,:,3] = np.where(bg_mask, 0, 255).astype(np.uint8)
        # 背景区RGB清零
        for ch in range(3):
            result[bg_mask, ch] = 0
        
        Image.fromarray(result, 'RGBA').save(out_fn)
        total += 1
        if (i+1) % 30 == 0:
            print(f'  {i+1}/121', flush=True)
    print(f'{state}: {total}帧白底抠图完成')

for state, cfg in STATES.items():
    print(f'=== {state} ===')
    video_path = os.path.join(VIDEOS, cfg['video'])
    if not os.path.exists(video_path):
        print(f'  SKIP: {video_path} not found')
        continue
    raw_dir = extract_frames(video_path, state)
    white_bg_cutout(raw_dir, state, cfg['white_thresh_mean'], cfg['white_thresh_min'])

print('WHITE_BG_CUTOUT_V3_DONE')
