# -*- coding: utf-8 -*-
"""帧诊断：检查每个动作中补帧(灰色帧填充)的位置和数量，以及主体bbox统计"""
import os
import numpy as np
from PIL import Image

FRAMES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frames')
STATES = ['idle','walk','run','eat','bark','sleep','sit','lick','happy',
          'roll','dance','stretch','beg','bath','surprised','play_dead',
          'pet','kiss','wave','type']

def get_subject_height(fn, alpha_thresh=30):
    im = Image.open(fn).convert('RGBA')
    a = np.array(im.getchannel('A'))
    mask = a > alpha_thresh
    if not mask.any():
        return 0
    rows = np.any(mask, axis=1)
    y0 = int(np.argmax(rows))
    y1 = int(len(rows) - np.argmax(rows[::-1]))
    return y1 - y0

for s in STATES:
    heights = []
    dup_runs = []  # 连续重复帧区间
    prev_h = None
    dup_start = None
    for i in range(121):
        fn = os.path.join(FRAMES, f'{s}_{i:03d}.png')
        h = get_subject_height(fn)
        heights.append(h)
        if h == prev_h:
            if dup_start is None:
                dup_start = i - 1
        else:
            if dup_start is not None and i - 1 - dup_start >= 2:
                dup_runs.append((dup_start, i - 1))
            dup_start = None
        prev_h = h
    if dup_start is not None and 120 - dup_start >= 2:
        dup_runs.append((dup_start, 120))
    
    h_min, h_max, h_avg = min(heights), max(heights), sum(heights)/len(heights)
    size_var = h_max - h_min
    dup_info = ', '.join(f'{a}-{b}({b-a+1}帧)' for a, b in dup_runs) if dup_runs else '无'
    print(f'{s:12s} h_avg={h_avg:.0f} h_range=[{h_min},{h_max}] var={size_var} 补帧区间: {dup_info}')
