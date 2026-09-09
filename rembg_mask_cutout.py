# -*- coding: utf-8 -*-
"""rembg_mask_cutout.py — rembg前景mask + 白底抠图混合
rembg识别前景(包括键盘/浴盆)，白底抠图精确区分背景
逻辑：rembg alpha>128为前景mask → 前景区保留原始RGB+alpha=255 → 背景区alpha=0
"""
import os, numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(ROOT, 'frames')

STATES_TO_PROCESS = ['type', 'bath', 'kiss']

import rembg

session = rembg.new_session('isnet-general-use')

for state in STATES_TO_PROCESS:
    print(f'=== {state} rembg+mask ===')
    total = 0
    for i in range(121):
        fn = os.path.join(FRAMES, f'{state}_{i:03d}.png')
        if not os.path.exists(fn):
            continue
        raw = np.array(Image.open(fn).convert('RGBA'))
        
        # rembg抠图获取前景mask
        rembg_result = rembg.remove(raw[:,:,:3], session=session)
        rembg_alpha = rembg_result[:,:,3]
        
        # 前景mask：rembg alpha>128
        fg_mask = rembg_alpha > 128
        
        # 保留原始RGB（不用rembg的抠图结果），前景alpha=255，背景alpha=0
        result = raw.copy()
        result[:,:,3] = np.where(fg_mask, 255, 0).astype(np.uint8)
        # 背景区RGB清零
        bg = ~fg_mask
        for ch in range(3):
            result[bg, ch] = 0
        
        Image.fromarray(result, 'RGBA').save(fn)
        total += 1
        if (i+1) % 30 == 0:
            print(f'  {i+1}/121', flush=True)
    print(f'{state}: {total}帧完成')

print('REMBG_MASK_CUTOUT_DONE')
