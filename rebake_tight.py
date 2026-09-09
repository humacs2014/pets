# -*- coding: utf-8 -*-
"""rebake_tight.py — 将frames/中的帧裁剪到主体tight bbox，统一主体高度为TARGET_H。
底边锚定（脚底不动），水平居中。输出到assets/。
用法: python rebake_tight.py
"""
import os, numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(ROOT, 'frames')
ASSETS = os.path.join(ROOT, 'assets')
STATES = ['idle','walk','run','eat','bark','sleep','sit','lick','happy',
          'roll','dance','stretch','beg','bath','surprised','play_dead',
          'pet','kiss','wave','type']

# 目标主体高度（像素）。idle帧的主体平均高度约700px，以此为准
TARGET_H = 700

# alpha阈值：低于此值的像素视为透明（忽略散落噪点）
ALPHA_THRESH = 30

os.makedirs(ASSETS, exist_ok=True)

def tight_bbox_alpha(arr, thresh=ALPHA_THRESH):
    """返回主体tight bbox (x0, y0, x1, y1)，alpha>thresh的区域"""
    a = arr[:, :, 3]
    mask = a > thresh
    if not mask.any():
        return None
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    y0 = int(np.argmax(rows))
    y1 = int(len(rows) - np.argmax(rows[::-1]))
    x0 = int(np.argmax(cols))
    x1 = int(len(cols) - np.argmax(cols[::-1]))
    return (x0, y0, x1, y1)

for state in STATES:
    print(f'{state}...', end=' ', flush=True)
    # 先扫描所有帧获取最大主体高度（决定缩放比例）
    max_bh = 0
    frame_data = []  # [(i, bbox)]
    for i in range(121):
        fn = os.path.join(FRAMES, f'{state}_{i:03d}.png')
        if not os.path.exists(fn):
            continue
        arr = np.array(Image.open(fn).convert('RGBA'))
        bbox = tight_bbox_alpha(arr)
        if bbox:
            bh = bbox[3] - bbox[1]
            if bh > max_bh:
                max_bh = bh
        frame_data.append((i, arr, bbox))
    
    if max_bh == 0:
        print(f'EMPTY, skip')
        continue
    
    # 缩放因子：将最大主体高度映射到TARGET_H
    scale = TARGET_H / max_bh
    
    out_count = 0
    for i, arr, bbox in frame_data:
        if bbox is None:
            # 空帧，输出空白
            out = Image.new('RGBA', (1, 1), (0, 0, 0, 0))
        else:
            x0, y0, x1, y1 = bbox
            # 裁剪到主体区域
            content = arr[y0:y1, x0:x1]
            # 缩放主体到统一高度
            ch, cw = content.shape[:2]
            new_h = max(2, int(round(ch * scale)))
            new_w = max(2, int(round(cw * scale)))
            content_im = Image.fromarray(content, 'RGBA')
            content_im = content_im.resize((new_w, new_h), Image.LANCZOS)
            out = content_im
        out_fn = os.path.join(ASSETS, f'{state}_{i:03d}.png')
        out.save(out_fn)
        out_count += 1
    
    print(f'{out_count} frames, max_bh={max_bh}, scale={scale:.3f}', flush=True)

print('\nREBAKE_DONE')
