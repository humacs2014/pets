# -*- coding: utf-8 -*-
"""gray_replace.py — 灰色帧检测与替换（保守策略）
检测条件：低彩度(mx-mn<30)+半透明(40<=a<=230)+中灰(80<=min,max<=220)
像素数超过GRAY_THRESH的帧视为灰色帧，用最近非灰帧替换。
替换策略：不丢弃帧编号，保持121帧完整，灰色帧的帧数据用相邻非灰帧覆盖。
阈值设为各动作中位数x5，避免误杀正常帧。
"""
import os, numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(ROOT, 'frames')
ASSETS = os.path.join(ROOT, 'assets')

STATES = ['idle','walk','run','eat','bark','sleep','sit','lick','happy',
          'roll','dance','stretch','beg','bath','surprised','play_dead',
          'pet','kiss','wave','type']

def count_gray_pixels(im_arr):
    """统计灰色半透明脏斑像素数"""
    r, g, b, a = im_arr[:,:,0], im_arr[:,:,1], im_arr[:,:,2], im_arr[:,:,3]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    return int(((a >= 40) & (a <= 230) & ((mx - mn) < 30) & (mn >= 80) & (mx <= 220)).sum())

def detect_gray_frames(frame_dir, state, n_frames=121):
    """检测灰色帧，返回(灰色帧索引列表, 每帧灰色像素数)"""
    gray_counts = []
    for i in range(n_frames):
        fn = os.path.join(frame_dir, f'{state}_{i:03d}.png')
        if not os.path.exists(fn):
            gray_counts.append(0)
            continue
        im = np.array(Image.open(fn).convert('RGBA')).astype(int)
        gray_counts.append(count_gray_pixels(im))
    
    # 动态阈值：中位数x3，至少5000
    median_gray = int(np.median(gray_counts))
    thresh = max(median_gray * 3, 5000)
    
    bad_frames = [i for i, g in enumerate(gray_counts) if g > thresh]
    return bad_frames, gray_counts, thresh

def replace_gray_frames(frame_dir, state, bad_frames, n_frames=121):
    """用最近非灰帧替换灰色帧"""
    if not bad_frames:
        return 0
    
    # 找到非灰帧
    good_frames = [i for i in range(n_frames) if i not in bad_frames]
    if not good_frames:
        return 0
    
    replaced = 0
    for bad_i in bad_frames:
        # 找最近的非灰帧
        dists = [(abs(bad_i - g), g) for g in good_frames]
        dists.sort()
        _, nearest_good = dists[0]
        
        # 复制帧数据
        src_fn = os.path.join(frame_dir, f'{state}_{nearest_good:03d}.png')
        dst_fn = os.path.join(frame_dir, f'{state}_{bad_i:03d}.png')
        src_im = Image.open(src_fn)
        src_im.save(dst_fn)
        replaced += 1
    
    return replaced

# 第一步：在frames/上检测
print('=== 第一步：灰色帧检测 ===')
total_bad = 0
for state in STATES:
    bad, counts, thresh = detect_gray_frames(FRAMES, state)
    if bad:
        total_bad += len(bad)
        print(f'{state}: 检出{len(bad)}帧灰色(阈值={thresh}), 帧: {bad}')
    else:
        max_g = max(counts)
        print(f'{state}: 无灰色帧 (max={max_g}, 阈值={thresh})')

if total_bad == 0:
    print('\\n所有帧均通过灰色检测，无需替换。直接rebake。')
else:
    print(f'\\n共{total_bad}帧需要替换')
    # 第二步：替换
    print('\\n=== 第二步：替换灰色帧 ===')
    for state in STATES:
        bad, counts, thresh = detect_gray_frames(FRAMES, state)
        if bad:
            n = replace_gray_frames(FRAMES, state, bad)
            print(f'{state}: 替换了{n}帧')

print('\\nDONE')
