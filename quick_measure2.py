# -*- coding: utf-8 -*-
"""量化各状态中间帧（第60帧）的主体bbox高度，判断是否需要校准"""
import os
from PIL import Image

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
STATES = ['idle','walk','run','eat','bark','sleep','sit','lick','happy',
          'roll','dance','stretch','beg','bath','surprised','play_dead',
          'pet','kiss','wave','type']

for s in STATES:
    heights = []
    for i in [0, 30, 60, 90, 120]:
        for ext in ('webp','png'):
            fn = os.path.join(ASSETS, f'{s}_{i:03d}.{ext}')
            if os.path.exists(fn):
                im = Image.open(fn).convert('RGBA')
                bbox = im.getchannel('A').getbbox()
                if bbox:
                    heights.append(bbox[3] - bbox[1])
                break
    if heights:
        print(f'{s:12s}  h_samples={heights}  min={min(heights)} max={max(heights)}')
    else:
        print(f'{s:12s}  NO FRAMES')
