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

def fix_frame(a, prop_safe=False):
    """prop_safe=True: 道具状态(type=键盘)——跳过pass2 halo删除和pass5悬浮碎片删除,
    键帽/底座等小CC逐帧被判halo/浮尘删除=用户报键盘闪烁(v101根因)。"""
    al = a[:, :, 3].astype(np.int32)
    rgb = a[:, :, :3].astype(np.float64)
    lum = rgb.mean(axis=2)
    out = a.copy()
    core = al > 127
    # v86: 外推源排除低饱和灰(matting灰带)——否则semi灰环ext取灰带自身=硬化灰块(walk 30k灰根因)
    _mx = rgb.max(axis=2); _mn = rgb.min(axis=2)
    _grayish = ((_mx - _mn) <= 45) & (_mn <= 195) & (_mx <= 235) & ((_mx - _mn) <= 0.22 * _mx)
    solid = (al > 200) & (lum >= 50) & ~_grayish   # 内部真毛色(排除premul暗边+灰带)
    body = binary_fill_holes(al > 200)        # 轮廓封闭体(含花纹)
    semi = (al >= 1) & (al <= 127)

    # ── RGB 纯外推（最近内部色）。铁律: 必须传 ~solid（indices=最近零点索引，
    #    传 mask 会映射到透明区=黑）──
    _, (iy, ix) = distance_transform_edt(~solid, return_indices=True)
    ext = rgb[iy, ix].astype(np.uint8)

    # ── 1) core 封闭洞填充 ──
    # v117: prop_safe(type键盘)跳过pass1——键帽间隙/阴影洞是道具自然结构,
    # 外推填充用奶油底座色=键帽白化(用户报键盘发白)
    if not prop_safe:
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
        if not prop_safe:
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
        if not prop_safe:
            # v117: 键盘semi=键帽AA渐变, ext外推奶油色=键帽边缘发白; 保留原RGB
            out[keep, :3] = ext[keep]

    # ── 3) rim 黑线删除: 轮廓外不透明暗像素（硬黑线非自然AA）──
    # v117: prop_safe用closing封闭body——键帽间隙semi致body漏孔, 深色键帽被判rim删除=黑斑
    if prop_safe:
        body = binary_fill_holes(binary_closing(core, iterations=3))
    rim = (al > 0) & (lum < 50) & ~body
    out[rim, 3] = 0

    # ── 4) fringe 清零 ──
    # v117: prop_safe跳过——键帽阴影AA半透边是道具自然边缘
    fringe = (al >= 1) & (al <= 15) & ~dil2 & (out[:, :, 3] > 0)
    if not prop_safe:
        out[fringe, 3] = 0

    # ── 5) 悬浮碎片 ──
    core2 = out[:, :, 3] > 127
    lab, n = ccl(core2, structure=np.ones((3, 3)))
    if n > 1 and not prop_safe:
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

# ── pass7(v103): Lab 色调对齐 idle 基准 ──
# 根因: roll偏暗(L-11.8)/kiss发青(a-12.5,b-11.9)/type去饱和(b-8.9) = 生成视频色偏。
# 逐状态自动测主体Lab均值与idle基准差→平移校正。纯像素色值变换零几何风险；
# 幂等(重跑shift≈0)。高光保护防过曝。CALIB_STATES 外的状态不碰。
CALIB_STATES = {'roll', 'kiss', 'type', 'walk', 'run'}
CALIB_REF = 'assets/idle_50.webp'

def srgb2lab(rgb):
    rgb = rgb / 255.0
    lin = np.where(rgb > 0.04045, ((rgb + 0.055) / 1.055) ** 2.4, rgb / 12.92)
    r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]
    X = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    Y = r * 0.2126 + g * 0.7152 + b * 0.0722
    Z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883
    def f(t):
        return np.where(t > 0.008856, t ** (1.0 / 3.0), 7.787 * t + 16.0 / 116.0)
    fx, fy, fz = f(X), f(Y), f(Z)
    return np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], -1)

def lab2srgb(lab):
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0
    def fi(t):
        t3 = t ** 3
        return np.where(t3 > 0.008856, t3, (t - 16.0 / 116.0) / 7.787)
    X, Y, Z = fi(fx) * 0.95047, fi(fy), fi(fz) * 1.08883
    r = X * 3.2406 - Y * 1.5372 - Z * 0.4986
    g = -X * 0.9689 + Y * 1.8758 + Z * 0.0415
    b2 = X * 0.0557 - Y * 0.2040 + Z * 1.0570
    lin = np.stack([r, g, b2], -1)
    rgb = np.where(lin > 0.0031308, 1.055 * np.clip(lin, 0, None) ** (1 / 2.4) - 0.055,
                   12.92 * lin)
    return np.clip(rgb * 255, 0, 255)

def _lab_mean(path):
    im = np.array(Image.open(path).convert('RGBA')).astype(np.float64)
    m = im[:, :, 3] > 127
    return srgb2lab(im[:, :, :3])[m].mean(0)

_REF_LAB = None

def ref_lab():
    global _REF_LAB
    if _REF_LAB is None:
        _REF_LAB = _lab_mean(CALIB_REF)
    return _REF_LAB

def fix_tone(a, shift):
    """主体像素 Lab 平移 shift(ref-cur)。仅动色值不动 alpha/几何。"""
    if np.allclose(shift, 0, atol=0.5):
        return a
    rgb = a[:, :, :3].astype(np.float64)
    lab = srgb2lab(rgb)
    lab += shift
    rgb2 = lab2srgb(lab)
    out = a.copy()
    m = a[:, :, 3] > 0
    out[m, :3] = np.where(rgb[m].max(1, keepdims=True) > 248, rgb[m], rgb2[m])
    return out

def fix_teal(a):
    """pass8(v103): 青底残留清除。rembg对近景大脸帧偶留青块(最大31k px)。
    青CC判据 G-R>25 & B-R>25；连透明/帧边=背景残→alpha=0；
    主体内封闭洞(背景透出)→最近实体毛色外推+alpha=255(填洞保主体完整)。"""
    rgb = a[:, :, :3].astype(np.int32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    teal = (a[:, :, 3] > 0) & ((g - r) > 12) & ((b - r) > 8) & (r < 190)   # v103b: 含暗灰绿残块; 白毛R≥200不受影响
    if teal.sum() < 20:
        return a
    lab, n = ccl(teal, structure=np.ones((3, 3)))
    sizes = np.bincount(lab.ravel())
    out = a.copy()
    al0 = a[:, :, 3]
    h, w = al0.shape
    edge = np.zeros((h, w), bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    solid = al0 > 200
    _mx = rgb.max(2); _mn = rgb.min(2)
    _grayish = ((_mx - _mn) <= 45) & (_mn <= 195) & (_mx <= 235) & ((_mx - _mn) <= 0.22 * _mx)
    src = solid & ~_grayish & ~teal        # v103b: 排除青色自身(青alpha=255会自填)
    _, (iy, ix) = distance_transform_edt(~src, return_indices=True)
    ext = a[iy, ix, :3].astype(np.uint8)
    for i in range(1, n + 1):
        if sizes[i] < 4:
            continue
        m = lab == i
        md = binary_dilation(m)
        if (m & edge).any() or (md & (al0 == 0)).any():
            out[m, 3] = 0          # 背景残块(邻透明/帧边)→删
        else:
            out[m, :3] = ext[m]    # 主体内洞→填毛色
            out[m, 3] = 255
    return out

def state_shift(st):
    import glob as _g
    fs = sorted(_g.glob(f'{ASSETS}/{st}_*.webp') + _g.glob(f'{ASSETS}/{st}_*.png'))
    if not fs:
        return np.zeros(3)
    cur = _lab_mean(fs[len(fs) // 2])
    return ref_lab() - cur

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

def temporal_white_stable(state):
    """v119: type专属时序白色稳定——视频模型逐帧生成的白色镜面高光(眼/颊/键帽)
    发白发亮且闪烁。白像素时序不稳定(出现率0.05-0.95)→替换为该像素时序25分位色
    (非白基色: 键帽奶白/虹膜深色); 稳定白(出现率>0.95, 如常驻眼高光)保留=自然。"""
    fs = sorted(glob.glob(f'{ASSETS}/{state}_*.webp') + glob.glob(f'{ASSETS}/{state}_*.png'))
    if len(fs) < 8:
        return
    imgs = [np.asarray(Image.open(f).convert('RGBA')) for f in fs]
    stack = np.stack(imgs).astype(np.float32)          # (N,H,W,4)
    rgb = stack[..., :3]; a = stack[..., 3]
    mx = rgb.max(-1); mn = rgb.min(-1)
    V = mx; S = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    white = (V >= 235) & (S <= 0.10) & (a > 128)
    freq = white.mean(0)
    unstable = (freq > 0.05) & (freq < 0.95)
    p25 = np.percentile(rgb, 25, axis=0)
    tot = 0
    for i, f in enumerate(fs):
        m = unstable & white[i]
        n = int(m.sum())
        if n == 0:
            continue
        o = imgs[i].copy()
        o[m, 0] = p25[m, 0]; o[m, 1] = p25[m, 1]; o[m, 2] = p25[m, 2]
        save_retry(Image.fromarray(o, 'RGBA'), f)
        tot += n
    print(f'  temporal_white: {tot} flicker-white px stabilized', flush=True)

def main():
    allf = glob.glob(f'{ASSETS}/*_*.png') + glob.glob(f'{ASSETS}/*_*.webp')
    states = sys.argv[1:] or sorted({os.path.basename(f).rsplit('_', 1)[0]
                                     for f in allf
                                     if not os.path.basename(f).startswith('_')})
    tot = 0
    # v103: kiss 青块预清(写盘)→shift测量不被青像素污染
    if 'kiss' in states:
        for fp in sorted(glob.glob(f'{ASSETS}/kiss_*.png') + glob.glob(f'{ASSETS}/kiss_*.webp')):
            im = Image.open(fp).convert('RGBA')
            a = np.asarray(im)
            o = fix_teal(a)
            if not np.array_equal(a, o):
                save_retry(Image.fromarray(o, 'RGBA'), fp)
    for st in states:
        shift = state_shift(st) if st in CALIB_STATES else np.zeros(3)
        fs = sorted(glob.glob(f'{ASSETS}/{st}_*.png') + glob.glob(f'{ASSETS}/{st}_*.webp'))
        for fp in fs:
            im = Image.open(fp).convert('RGBA')
            a = np.asarray(im)
            o = fix_frame(a, prop_safe=(st == 'type'))   # v101: 键盘道具白名单
            if st == 'bath':
                o = fix_bath_shadows(o)
            if st == 'kiss':
                o = fix_teal(o)                          # v103: 青底残块清除(校色前)
            if st in CALIB_STATES:                       # v103: 色调对齐idle基准
                o = fix_tone(o, shift)
            if not np.array_equal(a, o):
                save_retry(Image.fromarray(o, 'RGBA'), fp)
                tot += 1
        if st == 'type':                               # v119: 逐帧pass后时序白色稳定
            temporal_white_stable(st)
        print(f'{st:12s} {len(fs):3d}帧 fixed', flush=True)
    print(f'TOTAL fixed frames: {tot}', flush=True)

if __name__ == '__main__':
    main()
