# -*- coding: utf-8 -*-
"""帧插值补帧：将低帧率状态提升到目标帧率，消除卡顿感。
对 frames/ 目录的源帧做线性混合插值，生成中间帧。
然后需要更新 deploy_frames.py ANIMS + pet_engine.py ANIMS 帧数，再 redeploy + final_fix。

用法: python interpolate_frames.py [状态名...]
不指定状态则处理所有需要补帧的状态。
"""
import os, sys, glob, re
import numpy as np
from PIL import Image

FRAMES = 'frames'

# 需要补帧的状态：当前帧数→目标帧数
# 原则：总时长不变（帧数×frame_ms = 常量），补帧后frame_ms相应调整
# 目标帧率≥20fps，最好24fps
# wave已经是57@42ms=24fps，不需要补帧
# sleep有intro+loop结构，需保持intro/loop比例，单独处理
INTERP_CONFIG = {
    'bark':      {'from': 57,  'to': 114},   # 57@90ms→114@45ms=22fps, 5.13s
    'bath':      {'from': 57,  'to': 114},   # 57@90ms→114@45ms=22fps, 5.13s
    'beg':       {'from': 56,  'to': 112},   # 56@91ms→112@45ms=22fps, 5.04s
    'dance':     {'from': 57,  'to': 114},   # 57@90ms→114@45ms=22fps, 5.13s
    'sit':       {'from': 63,  'to': 126},   # 63@80ms→126@40ms=25fps, 5.04s
    'lick':      {'from': 54,  'to': 108},   # 54@74ms→108@37ms=27fps, 4.0s
    'surprised': {'from': 45,  'to': 90},    # 45@114ms→90@57ms=17.5fps, 5.13s
    'eat':       {'from': 34,  'to': 68},    # 34@96ms→68@48ms=21fps, 3.26s
    'play_dead': {'from': 68,  'to': 102},   # 68@75ms→102@50ms=20fps, 5.1s
}

# 新的frame_ms（补帧后）
NEW_FRAME_MS = {
    'bark': 45, 'bath': 45, 'beg': 45, 'dance': 45,
    'sit': 40, 'lick': 37, 'surprised': 57, 'eat': 48,
    'play_dead': 50,
}

def natural_sort(lst):
    return sorted(lst, key=lambda s: [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', s)])

def blend_frames(f0, f1, alpha):
    """线性混合两帧。alpha=0返回f0, alpha=1返回f1。"""
    a0 = np.array(f0, dtype=np.float32)
    a1 = np.array(f1, dtype=np.float32)
    out = a0 * (1.0 - alpha) + a1 * alpha
    return Image.fromarray(out.astype(np.uint8), f0.mode)

def interpolate_state(state, target_count):
    """对state的所有帧做插值补帧到target_count。"""
    pattern = os.path.join(FRAMES, f'{state}_*.png')
    src_files = natural_sort(glob.glob(pattern))
    n = len(src_files)
    if n == 0:
        print(f'{state}: no frames found')
        return 0
    if n >= target_count:
        print(f'{state}: already {n} frames >= {target_count}, skip')
        return 0
    
    print(f'{state}: {n}→{target_count} frames (interpolating {target_count - n} frames)')
    
    # 加载所有源帧
    frames = [Image.open(f).convert('RGBA') for f in src_files]
    
    # 生成插值帧
    new_frames = []
    for i in range(target_count):
        src_pos = i * (n - 1) / (target_count - 1)
        idx = int(src_pos)
        frac = src_pos - idx
        
        if idx >= n - 1:
            new_frames.append(frames[-1])
        elif frac < 0.01:
            new_frames.append(frames[idx])
        else:
            blended = blend_frames(frames[idx], frames[idx + 1], frac)
            new_frames.append(blended)
    
    # 写回frames目录
    for i, frame in enumerate(new_frames):
        out_path = os.path.join(FRAMES, f'{state}_{i:02d}.png')
        frame.save(out_path)
    
    # 删除多余的旧帧（如果目标帧数少于源帧数——不会发生，但安全起见）
    
    print(f'{state}: wrote {len(new_frames)} frames')
    return len(new_frames)

if __name__ == '__main__':
    states = sys.argv[1:] if len(sys.argv) > 1 else list(INTERP_CONFIG.keys())
    
    total = 0
    for st in states:
        cfg = INTERP_CONFIG.get(st)
        if not cfg:
            continue
        result = interpolate_state(st, cfg['to'])
        total += result
    
    print(f'\nTOTAL: {total} frames interpolated')
    if total > 0:
        print('\n!!! Must update ANIMS in both deploy_frames.py and pet_engine.py before redeploy !!!')
        print('New frame counts:')
        for st in states:
            cfg = INTERP_CONFIG.get(st)
            if cfg:
                ms = NEW_FRAME_MS.get(st, '?')
                print(f'  {st}: {cfg["to"]} frames @ {ms}ms')
