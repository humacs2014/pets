# -*- coding: utf-8 -*-
"""桌面宠物素材alpha闪烁修复（最终版，幂等可重跑）
用法: python fix_alpha.py <assets目录>
修改下方 ANIMS 字典匹配实际状态名与帧数。
根因: 渲染/插值帧主体alpha半透明且奇偶帧不一致 → 播放闪烁。
"""
import os
import sys
import numpy as np
from PIL import Image, ImageFilter

ROOT = sys.argv[1] if len(sys.argv) > 1 else 'assets'
# 按实际宠物修改: 状态名 -> 帧数
ANIMS = {'idle':44,'walk':20,'run':15,'eat':34,'bark':34,'sleep':37,'sit':41,
         'lick':32,'happy':44,'roll':44,'dance':37,'stretch':49,'beg':30,
         'bath':34,'surprised':29,'play_dead':44}

def semi_ratio(a):
    content = a > 20
    if content.sum() == 0: return 0.0
    return ((a > 20) & (a < 235)).sum() / content.sum() * 100

# pass1: 主体填实 alpha>128 -> 255（保留<128边缘软过渡）
fixed1 = 0
for st, count in ANIMS.items():
    for i in range(count):
        p = os.path.join(ROOT, f"{st}_{i:02d}.png")
        if not os.path.exists(p): continue
        im = Image.open(p).convert('RGBA')
        a = np.asarray(im).copy()
        alpha = a[:,:,3].copy()
        if semi_ratio(alpha) < 20: continue
        alpha[alpha > 128] = 255
        a[:,:,3] = alpha
        Image.fromarray(a).save(p)
        fixed1 += 1
print(f"pass1 填实帧数: {fixed1}")

# pass2: 残留半透明帧 → 二值化(>100) + 高斯重建软边缘（保抗锯齿）
fixed2 = 0
for st, count in ANIMS.items():
    for i in range(count):
        p = os.path.join(ROOT, f"{st}_{i:02d}.png")
        if not os.path.exists(p): continue
        im = Image.open(p).convert('RGBA')
        arr = np.asarray(im).copy()
        alpha = arr[:,:,3]
        if semi_ratio(alpha) < 8: continue
        mask = Image.fromarray((alpha > 100).astype(np.uint8) * 255)
        soft = np.asarray(mask.filter(ImageFilter.GaussianBlur(0.8)))
        arr[:,:,3] = soft
        Image.fromarray(arr).save(p)
        fixed2 += 1
print(f"pass2 二值化重建帧数: {fixed2}")

# 复检: 半透明占比<15% 且无奇偶交替
bad = []
for st, count in ANIMS.items():
    ratios = []
    for i in range(count):
        p = os.path.join(ROOT, f"{st}_{i:02d}.png")
        if not os.path.exists(p): continue
        ratios.append(semi_ratio(np.asarray(Image.open(p).convert('RGBA'))[:,:,3]))
    r = np.array(ratios)
    if len(r) == 0: continue
    gap = abs(r[0::2].mean() - r[1::2].mean()) if len(r) > 3 else 0
    if r.max() > 15 or gap > 3.0:
        bad.append((st, round(float(r.max()),1), round(float(gap),2)))
print(f"复检: {bad if bad else 'PASS — 全部状态半透明<15%且无奇偶交替'}")
sys.exit(1 if bad else 0)
