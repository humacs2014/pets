# -*- coding: utf-8 -*-
"""v73: eat 悬空棕色噪点横条修复。
横条=暗棕噪点矩形，逐行水平run>=90连续（毛发阴影不形成这种长run）。
聚类：连续>=15个run行且x区间互叠=一条bar；仅删run像素dilate2，毛发不碰。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe fix_eat_bar.py
"""
import glob
import numpy as np
from PIL import Image

def dilate(m, it=2):
    for _ in range(it):
        m2 = m.copy()
        m2[1:, :] |= m[:-1, :]; m2[:-1, :] |= m[1:, :]
        m2[:, 1:] |= m[:, :-1]; m2[:, :-1] |= m[:, 1:]
        m = m2
    return m

for f in sorted(glob.glob('assets/eat_*.png')):
    img = Image.open(f).convert('RGBA')
    a = np.array(img).astype(int)
    rgb, al = a[..., :3], a[..., 3]
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    db = (al > 200) & (R >= 90) & (R <= 180) & (R - B >= 45) & (R - B <= 115) & (G < R - 15)
    H, W = db.shape
    runs = {}
    for y in range(H):
        row = db[y]
        x = 0
        segs = []
        while x < W:
            if row[x]:
                x0 = x
                while x < W and row[x]:
                    x += 1
                if x - x0 >= 90:
                    segs.append((x0, x))
            else:
                x += 1
        if segs:
            runs[y] = segs
    if not runs:
        continue
    # 聚类连续run行（x互叠）
    bands = []
    ys = sorted(runs)
    cur = [ys[0]]
    for y in ys[1:]:
        if y - cur[-1] <= 2:
            prev = runs[cur[-1]]
            if any(a0 < b1 and b0 < a1 for a0, a1 in prev for b0, b1 in runs[y]):
                cur.append(y); continue
        bands.append(cur); cur = [y]
    bands.append(cur)
    out = np.array(img)
    fixed = 0
    for band in bands:
        if len(band) < 15:
            continue
        m = np.zeros((H, W), bool)
        for y in band:
            for x0, x1 in runs[y]:
                m[y, x0:x1] = True
        m = dilate(m, 2)
        fixed += int(m.sum())
        out[..., 3][m] = 0
    if fixed:
        Image.fromarray(out).save(f)
        print(f.split('\\')[-1], 'bar removed', fixed)
print('DONE')
