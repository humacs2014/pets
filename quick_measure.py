# -*- coding: utf-8 -*-
"""快速量化各状态首帧主体高度"""
import os
from PIL import Image

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
STATES = ['idle','walk','run','eat','bark','sleep','sit','lick','happy',
          'roll','dance','stretch','beg','bath','surprised','play_dead',
          'pet','kiss','wave','type']

for s in STATES:
    for ext in ('webp','png'):
        fn = os.path.join(ASSETS, f'{s}_000.{ext}')
        if os.path.exists(fn):
            im = Image.open(fn).convert('RGBA')
            bbox = im.getchannel('A').getbbox()
            if bbox:
                bh = bbox[3] - bbox[1]
                bw = bbox[2] - bbox[0]
                print(f'{s:12s}  bbox_h={bh:4d}  bbox_w={bw:4d}  canvas={im.size[0]}x{im.size[1]}')
            else:
                print(f'{s:12s}  EMPTY')
            break
