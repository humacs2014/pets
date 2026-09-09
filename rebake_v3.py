# -*- coding: utf-8 -*-
"""rebake_v3.py — 逐帧统一主体高度680px，保证不超出canvas
每帧独立：tight bbox裁剪 → 缩放到主体高度680px（宽度不超canvas则用高度约束，
宽度超canvas则用宽度约束）→ 底边锚定水平居中 → 输出
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
TARGET_H = 680
ALPHA_THRESH = 128

os.makedirs(ASSETS, exist_ok=True)

for state in STATES:
    frames_data = []
    for i in range(121):
        fn = os.path.join(FRAMES, f'{state}_{i:03d}.png')
        if not os.path.exists(fn):
            continue
        arr = np.array(Image.open(fn).convert('RGBA'))
        a = arr[:, :, 3]
        a = np.where(a >= ALPHA_THRESH, 255, 0).astype(np.uint8)
        arr[:, :, 3] = a
        mask = a > 10
        if mask.any():
            rows = np.any(mask, axis=1)
            cols = np.any(mask, axis=0)
            y0 = int(np.argmax(rows))
            y1 = int(len(rows) - np.argmax(rows[::-1]))
            x0 = int(np.argmax(cols))
            x1 = int(len(cols) - np.argmax(cols[::-1]))
            bh = y1 - y0
            bw = x1 - x0
        else:
            y0 = y1 = x0 = x1 = 0
            bh = bw = 0
        frames_data.append((i, arr, (x0, y0, x1, y1), bh, bw))

    if not frames_data:
        print(f'{state}: EMPTY, skip')
        continue

    out_count = 0
    for i, arr, (x0, y0, x1, y1), bh, bw in frames_data:
        canvas = Image.new('RGBA', (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        if bh > 0 and bw > 0:
            content = arr[y0:y1, x0:x1].copy()
            content_im = Image.fromarray(content, 'RGBA')
            
            # 先按高度680px缩放
            scale_h = TARGET_H / bh
            new_h = TARGET_H
            new_w = int(round(bw * scale_h))
            
            # 如果宽度超出canvas，改为按宽度约束缩放
            if new_w > CANVAS_W:
                scale_w = (CANVAS_W - 20) / bw  # 留20px边距
                new_w = CANVAS_W - 20
                new_h = max(2, int(round(bh * scale_w)))
            
            content_im = content_im.resize((max(2, new_w), max(2, new_h)), Image.LANCZOS)
            paste_y = CANVAS_H - new_h
            paste_x = (CANVAS_W - new_w) // 2
            canvas.paste(content_im, (paste_x, paste_y), content_im)
        out_fn = os.path.join(ASSETS, f'{state}_{i:03d}.png')
        canvas.save(out_fn)
        out_count += 1

    print(f'{state}: {out_count} frames', flush=True)

print('REBAKE_V3_DONE')
