# -*- coding: utf-8 -*-
"""更精确地测量主体高度：用99%分位alpha阈值，忽略散落边缘像素"""
import os
import numpy as np
from PIL import Image

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
STATES = ['idle','walk','run','eat','bark','sleep','sit','lick','happy',
          'roll','dance','stretch','beg','bath','surprised','play_dead',
          'pet','kiss','wave','type']

def tight_bbox(im, alpha_thresh=30):
    """忽略低alpha散落像素的tight bbox"""
    a = np.array(im.getchannel('A'))
    mask = a > alpha_thresh
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if not rows.any():
        return None
    y0, y1 = np.argmax(rows), len(rows) - np.argmax(rows[::-1])
    x0, x1 = np.argmax(cols), len(cols) - np.argmax(cols[::-1])
    return (y1 - y0, x1 - x0)

for s in STATES:
    heights = []
    widths = []
    for i in [0, 30, 60, 90, 120]:
        for ext in ('webp','png'):
            fn = os.path.join(ASSETS, f'{s}_{i:03d}.{ext}')
            if os.path.exists(fn):
                im = Image.open(fn).convert('RGBA')
                bb = tight_bbox(im)
                if bb:
                    heights.append(bb[0])
                    widths.append(bb[1])
                break
    if heights:
        print(f'{s:12s}  h={heights}  w={widths}  h_avg={sum(heights)/len(heights):.0f}')
    else:
        print(f'{s:12s}  NO FRAMES')
