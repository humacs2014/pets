# -*- coding: utf-8 -*-
"""sleep 躺下帧尺寸归一: 侧躺w>380的帧按 s=min(1,370/w) 缩放(=roll躺下同尺度),
底部(地面线)锚定, 站姿帧不动。直接重写 frames/sleep_*.png, 之后 final_fix 同步assets。"""
import glob
import numpy as np
from PIL import Image

TARGET_W = 370
files = sorted(glob.glob('frames/sleep_*.png'))
changed = 0
for p in files:
    im = Image.open(p).convert('RGBA')
    a = np.array(im)
    alpha = a[..., 3]
    ys, xs = np.where(alpha > 30)
    if len(xs) == 0:
        continue
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    w, h = x1 - x0 + 1, y1 - y0 + 1
    if w <= 380:
        continue
    s = TARGET_W / w
    sub = im.crop((x0, y0, x1 + 1, y1 + 1))
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    sub = sub.resize((nw, nh), Image.LANCZOS)
    out = Image.new('RGBA', im.size, (0, 0, 0, 0))
    out.paste(sub, (x0, y1 + 1 - nh), sub)   # 底部锚定: 脚/地面线不动
    out.save(p)
    changed += 1
print(f'rescaled {changed}/{len(files)} lying frames to w≈{TARGET_W} (bottom-anchored)')
