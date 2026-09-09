# -*- coding: utf-8 -*-
"""rebake_per_frame.py — 逐帧统一主体高度680px
每帧独立：tight bbox裁剪 → 缩放到主体高度680px → 底边锚定水平居中 → 输出
解决wave等动作源视频大小渐变导致rebake后大小不一致的问题
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
    max_bh = 0
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
        else:
            y0 = y1 = x0 = x1 = 0
            bh = 0
        if bh > max_bh:
            max_bh = bh
        frames_data.append((i, arr, (x0, y0, x1, y1), bh))

    if max_bh == 0:
        print(f'{state}: EMPTY, skip')
        continue

    out_count = 0
    for i, arr, (x0, y0, x1, y1), bh in frames_data:
        canvas = Image.new('RGBA', (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        if bh > 0:
            content = arr[y0:y1, x0:x1].copy()
            content_im = Image.fromarray(content, 'RGBA')
            ch, cw = content.shape[:2]
            # 每帧独立缩放到TARGET_H高度
            scale = TARGET_H / bh
            new_h = TARGET_H
            new_w = max(2, int(round(cw * scale)))
            content_im = content_im.resize((new_w, new_h), Image.LANCZOS)
            paste_y = CANVAS_H - new_h
            paste_x = (CANVAS_W - new_w) // 2
            canvas.paste(content_im, (paste_x, paste_y), content_im)
        out_fn = os.path.join(ASSETS, f'{state}_{i:03d}.png')
        canvas.save(out_fn)
        out_count += 1

    print(f'{state}: {out_count} frames, max_bh={max_bh}', flush=True)

print('REBAKE_PER_FRAME_DONE')
