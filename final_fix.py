# -*- coding: utf-8 -*-
"""阶段4 帧清洁五合一（labrador 验证版，幂等可重跑，零几何变化）。
对 assets/ 全量跑（deploy_frames.py --copy 之后），作为唯一清洁脚本 + 阶段6复检。
五个 pass:
  1) 封闭洞填充: closing(3)+fill_holes, hole CC 8..4000 → 最近实体色外推+alpha=255
  2) semi 双类: 独立光环ghost(size>300 & span>40 & 贴边率band<0.7)→alpha=0；贴边AA环保留+RGB外推
  3) rim 黑线删除: 轮廓外 & lum<50 & 不透明 → alpha=0
  4) fringe 清零: alpha 1-15 & 不贴边 → 0
  5) 悬浮碎片: 非主CC size<1000 & 距主体≥20px → alpha=0（≥1000px道具/爪尖保留）
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe final_fix.py [状态名...]
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

    # ── RGB 纯外推（最近内部色）。铁律: 必须传 ~solid（indices=最近零点索引，
    #    传 mask 会映射到透明区=黑）──
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

    # ── 2) semi 双类: 光环删 / AA环保留+RGB外推（白毛绒毛自然感，禁无差别硬化）──
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

    # ── 3) rim 黑线删除: 轮廓外不透明暗像素（硬黑线非自然AA）──
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

def fix_bath_shadows(a):
    """pass6(bath 专用，纯局部规则，零毛发风险)：泡沫灰阴影/黑描边时隐时现→白化稳定。
    A 低饱和浅灰(lum90-238, sat<0.15)→白；B 暗描边(lum<120, sat<0.35)且1px邻接纯白泡沫→白；
    # C 半透灰边(al<200, sat<0.2, lum<240)→透明；D 残余小域(<200px, 不邻接泡沫)→透明(浮尘)；
    # E(v66) 泡沫内透明洞→补泡沫白：matting把白泡沫当白背景抠掉=桌面透出=时隐时现，
    #   closing+fill_holes(foam) 封闭区内 al<128 → (252,252,252,255)。
    # 验收=阴影团逐帧cv≈0.03 + 毛发损失0% + 泡沫洞=0。禁连通域+sat全局方案(连坐毛发破洞)。"""
    rgb = a[:, :, :3].astype(np.int32)
    mx = rgb.max(2)
    mn = rgb.min(2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(1, mx), 0)
    lum = rgb.mean(2)
    anyal = a[:, :, 3] > 10
    foam = anyal & (sat < 0.12) & (lum > 240)
    d = foam.copy()
    d[1:, :] |= foam[:-1, :]; d[:-1, :] |= foam[1:, :]
    d[:, 1:] |= foam[:, :-1]; d[:, :-1] |= foam[:, 1:]
    mA = anyal & (sat < 0.15) & (lum >= 90) & (lum < 238)
    mB = anyal & d & (sat < 0.35) & (lum < 120)
    mD = (a[:, :, 3] > 10) & (a[:, :, 3] < 200) & (sat < 0.20) & (lum < 240)
    m = mA | mB
    out = a.copy()
    out[m, 0] = 252; out[m, 1] = 252; out[m, 2] = 252; out[m, 3] = 255
    out[mD & ~m, 3] = 0
    # E 泡沫内透明洞补白
    filled_f = binary_fill_holes(binary_closing(foam, iterations=3))
    holes = filled_f & (a[:, :, 3] < 128)
    out[holes] = (252, 252, 252, 255)
    rest = anyal & ~m & (sat < 0.35) & (lum < 238) & ~d
    lab, nl = ccl(rest)
    if nl:
        sizes = np.bincount(lab.ravel())
        for k in range(1, nl + 1):
            if sizes[k] < 200:
                out[lab == k, 3] = 0
    return out

def save_retry(im, fp, tries=5):
    """Windows下杀软/索引瞬时锁文件→OSError 22; 重试退避解决。"""
    import time
    for t in range(tries):
        try:
            im.save(fp)
            return
        except OSError:
            if t == tries - 1:
                raise
            time.sleep(0.5 * (t + 1))

def main():
    allf = glob.glob(f'{ASSETS}/*_*.png') + glob.glob(f'{ASSETS}/*_*.webp')
    states = sys.argv[1:] or sorted({os.path.basename(f).rsplit('_', 1)[0]
                                     for f in allf
                                     if not os.path.basename(f).startswith('_')})
    tot = 0
    for st in states:
        fs = sorted(glob.glob(f'{ASSETS}/{st}_*.png') + glob.glob(f'{ASSETS}/{st}_*.webp'))
        for fp in fs:
            im = Image.open(fp).convert('RGBA')
            a = np.asarray(im)
            o = fix_frame(a)
            if st == 'bath':
                o = fix_bath_shadows(o)
            if not np.array_equal(a, o):
                save_retry(Image.fromarray(o, 'RGBA'), fp)
                tot += 1
        print(f'{st:12s} {len(fs):3d}帧 fixed', flush=True)
    print(f'TOTAL fixed frames: {tot}', flush=True)

if __name__ == '__main__':
    main()
