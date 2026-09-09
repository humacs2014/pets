# -*- coding: utf-8 -*-
"""修复异常帧：bbox撑满canvas的帧（灰色帧补帧遗留）
对每个帧检查alpha通道，如果bbox占canvas>90%，用alpha>30阈值重新裁剪到tight bbox"""
import os
import numpy as np
from PIL import Image

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
STATES = ['idle','walk','run','eat','bark','sleep','sit','lick','happy',
          'roll','dance','stretch','beg','bath','surprised','play_dead',
          'pet','kiss','wave','type']

def tight_crop(im, alpha_thresh=30):
    """裁剪到alpha>thresh的tight bbox，底边和水平居中锚定"""
    a = np.array(im.getchannel('A'))
    w, h = im.size
    mask = a > alpha_thresh
    if not mask.any():
        return im
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    y0 = int(np.argmax(rows))
    y1 = int(len(rows) - np.argmax(rows[::-1]))
    x0 = int(np.argmax(cols))
    x1 = int(len(cols) - np.argmax(cols[::-1]))
    
    bbox = im.getchannel('A').getbbox()
    if bbox is None:
        return im
    
    # 只有当bbox撑满>90%时才修复
    bbox_h = bbox[3] - bbox[1]
    bbox_w = bbox[2] - bbox[0]
    if bbox_h < h * 0.9 and bbox_w < w * 0.9:
        return im  # 正常帧，不修
    
    # 裁剪到tight区域，底边锚定
    content = im.crop((x0, y0, x1, y1))
    cw, ch = content.size
    
    # 放回原canvas，底边锚定，水平居中
    canvas = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    nx0 = (w - cw) // 2
    ny0 = h - ch  # 底边锚定
    canvas.paste(content, (nx0, ny0), content)
    return canvas

fixed_total = 0
for s in STATES:
    fixed = 0
    i = 0
    while True:
        fn = None
        for ext in ('webp', 'png'):
            candidate = os.path.join(ASSETS, f'{s}_{i:03d}.{ext}')
            if os.path.exists(candidate):
                fn = candidate
                break
        if fn is None:
            break
        try:
            im = Image.open(fn).convert('RGBA')
        except Exception as e:
            print(f'  SKIP corrupt: {os.path.basename(fn)} ({e})')
            i += 1
            continue
        bbox = im.getchannel('A').getbbox()
        if bbox:
            bw = bbox[2] - bbox[0]
            bh = bbox[3] - bbox[1]
            if bh > im.size[1] * 0.9 and bw > im.size[0] * 0.9:
                new_im = tight_crop(im)
                if fn.endswith('.webp'):
                    new_im.save(fn, 'WEBP', quality=95)
                else:
                    new_im.save(fn)
                fixed += 1
        i += 1
    if fixed > 0:
        print(f'{s}: {fixed} frames fixed')
        fixed_total += fixed

print(f'\nTOTAL fixed: {fixed_total}')
