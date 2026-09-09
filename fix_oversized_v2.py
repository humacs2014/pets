# -*- coding: utf-8 -*-
"""修复kiss和type中bbox仍撑满canvas的帧：用邻近正常帧替换"""
import os
import shutil
import numpy as np
from PIL import Image

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
CANVAS_H, CANVAS_W = 832, 1088

def is_oversized(fn, threshold=0.9):
    try:
        im = Image.open(fn).convert('RGBA')
    except:
        return False
    bbox = im.getchannel('A').getbbox()
    if bbox is None:
        return True
    bh = bbox[3] - bbox[1]
    bw = bbox[2] - bbox[0]
    return bh > CANVAS_H * threshold and bw > CANVAS_W * threshold

for state in ['kiss', 'type']:
    # 收集所有帧
    all_fns = []
    i = 0
    while True:
        fn = None
        for ext in ('webp', 'png'):
            candidate = os.path.join(ASSETS, f'{state}_{i:03d}.{ext}')
            if os.path.exists(candidate):
                fn = candidate
                break
        if fn is None:
            break
        all_fns.append(fn)
        i += 1
    
    # 找正常帧和异常帧
    good = {}
    bad = []
    for idx, fn in enumerate(all_fns):
        if is_oversized(fn):
            bad.append(idx)
        else:
            good[idx] = fn
    
    if not bad:
        print(f'{state}: no oversized frames')
        continue
    
    if not good:
        print(f'{state}: ALL frames oversized, cannot fix!')
        continue
    
    # 用最近正常帧替换异常帧
    fixed = 0
    for b in bad:
        # 找最近的good帧
        nearest = min(good.keys(), key=lambda g: abs(g - b))
        try:
            src_im = Image.open(good[nearest]).convert('RGBA')
            dst_fn = all_fns[b]
            if dst_fn.endswith('.webp'):
                src_im.save(dst_fn, 'WEBP', quality=95)
            else:
                src_im.save(dst_fn)
            fixed += 1
        except Exception as e:
            print(f'  ERROR fixing frame {b}: {e}')
    
    print(f'{state}: {fixed} oversized frames replaced with nearest good frame (from {len(good)} good frames)')
