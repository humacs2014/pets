# -*- coding: utf-8 -*-
"""帧清洁五合一（v56 验证版，幂等可重跑，零几何变化）。
用法: python final_fix.py [状态名...]（默认对 assets/ 全部 {state}_*.png 跑）
对 assets/ 全量跑，作为阶段4唯一清洁脚本 + 阶段6审计门复检。
五个 pass:
  1) 封闭洞填充: closing(3)+fill_holes, hole CC 8..4000 → 最近实体色外推+alpha=255（腿缝连外不填）
  2) semi 双类: 独立光环ghost(size>300 & span>40 & 贴边率band<0.7)→alpha=0；贴边AA环(band≥0.7)保留+RGB外推
  3) rim 黑线删除: 轮廓外 & lum<50 & 不透明 → alpha=0（硬黑线非自然AA）
  4) fringe 清零: alpha 1-15 & 不贴边 → 0
  5) 悬浮碎片: 非主CC size<1000 & 距主体≥20px → alpha=0（≥1000px道具/爪尖保留）
关键铁律: 外推源 solid=(a>200 & lum≥50) 排除 premul 暗边;
  distance_transform_edt 必须传 ~solid（indices=最近零点索引，传 mask 会映射到透明区=黑）;
  _,(iy,ix)= 解包。
"""
import glob, os, sys
import numpy as np
from PIL import Image
from scipy.ndimage import (binary_dilation, binary_closing, label as ccl,
                           distance_transform_edt, binary_fill_holes)

ASSETS = 'assets'

def fix_frame(a):
    al = a[:, :, 3].astype(np.int32)
    rgb = a[:, :, :3].astype(np.float64)
    lum = rgb.mean(axis=2)
    out = a.copy()
    core = al > 127
    solid = (al > 200) & (lum >= 50)          # 内部真毛色(排除premul暗边)
    body = binary_fill_holes(al > 200)        # 轮廓封闭体(含花纹)
    semi = (al >= 1) & (al <= 127)

    # ── RGB 纯外推（最近内部色）──
    _, (iy, ix) = distance_transform_edt(~solid, return_indices=True)
    ext = rgb[iy, ix].astype(np.uint8)

    # ── 1) core 封闭洞填充 ──
    closed = binary_closing(core, iterations=3)
    filled = binary_fill_holes(closed)
    hole = filled & ~core & (al < 140)
    if hole.any():
        lab, n = ccl(hole, structure=np.ones((3, 3)))
        sizes = np.bincount(lab.ravel())
        for i in range(1, n + 1):
            if 8 <= sizes[i] <= 4000:
                m = lab == i
                out[m, :3] = ext[m]
                out[m, 3] = 255
                core = core | m

    # ── 2) semi 双类: 光环删 / AA环保留+RGB外推 ──
    dil2 = binary_dilation(core, iterations=2)
    if semi.any():
        lab, n = ccl(semi, structure=np.ones((3, 3)))
        sizes = np.bincount(lab.ravel())
        halo = np.zeros_like(semi)
        for i in range(1, n + 1):
            if sizes[i] > 300:
                m = lab == i
                ys = np.where(m.any(axis=1))[0]
                xs = np.where(m.any(axis=0))[0]
                span = max(ys.max() - ys.min() + 1, xs.max() - xs.min() + 1)
                band = (m & dil2).sum() / max(m.sum(), 1)
                if span > 40 and band < 0.7:
                    halo |= m
        keep = semi & ~halo
        out[halo, 3] = 0
        out[keep, :3] = ext[keep]

    # ── 3) rim 黑线删除: 轮廓外不透明暗像素 ──
    rim = (al > 0) & (lum < 50) & ~body
    out[rim, 3] = 0

    # ── 4) fringe 清零 ──
    fringe = (al >= 1) & (al <= 15) & ~dil2 & (out[:, :, 3] > 0)
    out[fringe, 3] = 0

    # ── 5) 悬浮碎片 ──
    core2 = out[:, :, 3] > 127
    lab, n = ccl(core2, structure=np.ones((3, 3)))
    if n > 1:
        sizes = np.bincount(lab.ravel())
        main = int(np.argmax(sizes[1:])) + 1
        dilM = binary_dilation(lab == main, iterations=3)
        dt = distance_transform_edt(~(lab == main))
        for i in range(1, n + 1):
            if i == main or sizes[i] >= 1000:
                continue
            m = lab == i
            if not (m & dilM).any() and dt[m].min() >= 20:
                out[m, 3] = 0
    return out

def main():
    states = sys.argv[1:] or sorted({os.path.basename(f).rsplit('_', 1)[0]
                                     for f in glob.glob(f'{ASSETS}/*_*.png')
                                     if not os.path.basename(f).startswith('_')})
    tot = 0
    for st in states:
        fs = sorted(glob.glob(f'{ASSETS}/{st}_*.png'))
        for fp in fs:
            im = Image.open(fp).convert('RGBA')
            a = np.asarray(im)
            o = fix_frame(a)
            if not np.array_equal(a, o):
                Image.fromarray(o, 'RGBA').save(fp)
                tot += 1
        print(f'{st:12s} {len(fs):3d}帧 fixed', flush=True)
    print(f'TOTAL fixed frames: {tot}', flush=True)

if __name__ == '__main__':
    main()
