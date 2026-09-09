# -*- coding: utf-8 -*-
"""rebake_uniform.py — 将frames/中的帧重新烘焙到统一canvas(1088×832)，
主体缩放到统一高度TARGET_H，底边锚定（脚底不动），水平居中。
输出到assets/。
用法: python rebake_uniform.py
"""
import os, numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(ROOT, 'frames')
ASSETS = os.path.join(ROOT, 'assets')
STATES = ['idle','walk','run','eat','bark','sleep','sit','lick','happy',
          'roll','dance','stretch','beg','bath','surprised','play_dead',
          'pet','kiss','wave','type']

CANVAS_W, CANVAS_H = 1088, 832
TARGET_SUBJECT_H = 680  # 统一主体高度（像素），在canvas内
ALPHA_THRESH = 30

os.makedirs(ASSETS, exist_ok=True)

def get_subject_bbox(arr, thresh=ALPHA_THRESH):
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

def get_subject_bottom(arr, thresh=ALPHA_THRESH):
    """主体底边y坐标（脚底位置）"""
    a = arr[:, :, 3]
    mask = a > thresh
    if not mask.any():
        return arr.shape[0]
    rows = np.any(mask, axis=1)
    # 从底部向上找第一个有内容的行
    for row in range(arr.shape[0] - 1, -1, -1):
        if rows[row]:
            return row + 1
    return arr.shape[0]

for state in STATES:
    print(f'{state}...', end=' ', flush=True)
    # 先扫描所有帧，找到最大主体高度和最低脚底位置
    max_bh = 0
    max_bottom = 0
    frames_info = []
    
    for i in range(121):
        fn = os.path.join(FRAMES, f'{state}_{i:03d}.png')
        if not os.path.exists(fn):
            continue
        arr = np.array(Image.open(fn).convert('RGBA'))
        bbox = get_subject_bbox(arr)
        bottom = get_subject_bottom(arr)
        if bbox:
            bh = bbox[3] - bbox[1]
            if bh > max_bh:
                max_bh = bh
        if bottom > max_bottom:
            max_bottom = bottom
        frames_info.append((i, arr, bbox, bottom))
    
    if max_bh == 0 or not frames_info:
        print(f'EMPTY, skip')
        continue
    
    # 缩放因子：最大主体高度→TARGET_SUBJECT_H
    scale = TARGET_SUBJECT_H / max_bh
    
    out_count = 0
    for i, arr, bbox, bottom in frames_info:
        canvas = Image.new('RGBA', (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        
        if bbox is None:
            # 空帧
            pass
        else:
            x0, y0, x1, y1 = bbox
            content = arr[y0:y1, x0:x1].copy()
            content_im = Image.fromarray(content, 'RGBA')
            
            # 缩放
            ch, cw = content.shape[:2]
            new_h = max(2, int(round(ch * scale)))
            new_w = max(2, int(round(cw * scale)))
            content_im = content_im.resize((new_w, new_h), Image.LANCZOS)
            
            # 定位：底边锚定到canvas底部(=CANVAS_H)，水平居中
            # 原始帧中脚底在bottom行，主体从y0到y1
            # 缩放后脚底位置：bottom*scale，但我们固定到canvas底部
            # 主体在canvas中的y坐标：
            # 原始帧中主体底边 = bottom, 顶边 = y0
            # 缩放后高度 = new_h, 底边锚定到 CANVAS_H
            paste_y = CANVAS_H - new_h  # 底边对齐canvas底
            paste_x = (CANVAS_W - new_w) // 2  # 水平居中
            
            canvas.paste(content_im, (paste_x, paste_y), content_im)
        
        out_fn = os.path.join(ASSETS, f'{state}_{i:03d}.png')
        canvas.save(out_fn)
        out_count += 1
    
    print(f'{out_count} frames, max_bh={max_bh}, scale={scale:.3f}', flush=True)

print('\nREBAKE_DONE')
