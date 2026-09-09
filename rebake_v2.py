# -*- coding: utf-8 -*-
"""rebake_v2.py — 从frames/读取union帧，二值化BEN2残留soft alpha，
裁剪tight bbox，统一主体高度TARGET_H=680，底边锚定水平居中，输出到assets/
"""
import os, numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(ROOT, 'frames')
ASSETS = os.path.join(ROOT, 'assets')
os.makedirs(ASSETS, exist_ok=True)

CANVAS_W, CANVAS_H = 1088, 832
TARGET_SUBJECT_H = 680
ALPHA_THRESH = 10  # 低于此视为透明

STATES = ['idle','walk','run','eat','bark','sleep','sit','lick','happy',
          'roll','dance','stretch','beg','bath','surprised','play_dead',
          'pet','kiss','wave','type']

for state in STATES:
    print(f'{state}...', end=' ', flush=True)
    max_bh = 0
    frames_data = []
    
    for i in range(121):
        fn = os.path.join(FRAMES, f'{state}_{i:03d}.png')
        if not os.path.exists(fn):
            continue
        arr = np.array(Image.open(fn).convert('RGBA'))
        a = arr[:, :, 3]
        # 清理soft alpha：>=128→255, <128→0
        a = np.where(a >= 128, 255, 0).astype(np.uint8)
        arr[:, :, 3] = a
        
        # tight bbox
        mask = a > ALPHA_THRESH
        if mask.any():
            rows = np.any(mask, axis=1)
            cols = np.any(mask, axis=0)
            y0 = int(np.argmax(rows))
            y1 = int(len(rows) - np.argmax(rows[::-1]))
            x0 = int(np.argmax(cols))
            x1 = int(len(cols) - np.argmax(cols[::-1]))
            bh = y1 - y0
        else:
            y0 = y1 = x0 = x1 = 0
            bh = 0
        
        if bh > max_bh:
            max_bh = bh
        frames_data.append((i, arr, (x0, y0, x1, y1), bh))
    
    if max_bh == 0:
        print('EMPTY, skip')
        continue
    
    scale = TARGET_SUBJECT_H / max_bh
    out_count = 0
    for i, arr, (x0, y0, x1, y1), bh in frames_data:
        canvas = Image.new('RGBA', (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        if bh > 0:
            content = arr[y0:y1, x0:x1].copy()
            content_im = Image.fromarray(content, 'RGBA')
            ch, cw = content.shape[:2]
            new_h = max(2, int(round(ch * scale)))
            new_w = max(2, int(round(cw * scale)))
            content_im = content_im.resize((new_w, new_h), Image.LANCZOS)
            paste_y = CANVAS_H - new_h
            paste_x = (CANVAS_W - new_w) // 2
            canvas.paste(content_im, (paste_x, paste_y), content_im)
        out_fn = os.path.join(ASSETS, f'{state}_{i:03d}.png')
        canvas.save(out_fn)
        out_count += 1
    
    print(f'{out_count} frames, max_bh={max_bh}, scale={scale:.3f}', flush=True)

print('\nREBAKE_V2_DONE')
