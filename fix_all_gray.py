# -*- coding: utf-8 -*-
"""v74: 全状态灰色 matting 残影统修。
判据 = 低饱和(mx-mn<=18)+中灰(90<=mx<=160)+不透明 → erode2 去边线 → 连通块>=60px
→ 仅修「邻接透明边界」的块（dilate4触及alpha<60）= matting 残留灰边（walk胸口/
run裆部/idle腋下等）；内部阴影（sit嘴周等合法毛发暗部）不邻透明→零误伤。
填充=列向最近合法毛发色（同fix_gray_wedge/fix_run_gray）。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe fix_all_gray.py [state...]
不带参数=全状态。
"""
import glob
import sys
import numpy as np
from PIL import Image
from scipy import ndimage

STATES = ['idle', 'sit', 'eat', 'bark', 'happy', 'roll', 'dance', 'beg',
          'bath', 'lick', 'surprised', 'play_dead', 'sleep', 'stretch',
          'walk', 'run', 'pet']
MAX_SCAN = 160

def erode(m, it=2):
    for _ in range(it):
        m2 = m.copy()
        m2[1:, :] &= m[:-1, :]; m2[:-1, :] &= m[1:, :]
        m2[:, 1:] &= m[:, :-1]; m2[:, :-1] &= m[:, 1:]
        m = m2
    return m

def dilate(m, it=4):
    for _ in range(it):
        m2 = m.copy()
        m2[1:, :] |= m[:-1, :]; m2[:-1, :] |= m[1:, :]
        m2[:, 1:] |= m[:, :-1]; m2[:, :-1] |= m[:, 1:]
        m = m2
    return m

def save_retry(im, fp, tries=5):
    import time
    for t in range(tries):
        try:
            im.save(fp)
            return
        except OSError:
            if t == tries - 1:
                raise
            time.sleep(0.5 * (t + 1))

states = sys.argv[1:] or STATES
grand = 0
# 合法毛发填充源 = 橙毛(饱和>30) 或 真白毛(mx>215且mn>200)，
# 排除抗锯齿浅灰边(如200,200,200这类mx>195的低饱和灰)
def good_fur(px):
    if px[3] < 200: return False
    mx = int(max(px[0], px[1], px[2])); mn = int(min(px[0], px[1], px[2]))
    return (mx - mn > 30) or (mx > 215 and mn > 200)
for st in states:
    fs = sorted(glob.glob('assets/%s_*.webp' % st)) + sorted(glob.glob('assets/%s_*.png' % st))
    st_tot = 0; nf = 0
    for f in fs:
        img = Image.open(f).convert('RGBA')
        a = np.array(img)
        rgb = a[..., :3].astype(np.int16); al = a[..., 3]
        mx = rgb.max(-1); mn = rgb.min(-1)
        trans = al < 60
        # v86: 灰影=中性/弱暖灰 matting 残影+v84乘式残余。门: 不透明+mx<=235(排除白肚mn>=210/mx>=236)+mn<=195(排除白毛AA边)+
        #   mx-mn<=45(弱彩)+sat<0.22(排除橙毛阴影sat0.3+)。实测: IDLE/SIT/RUN 零命中, WALK 全灰带命中。
        #   无erode/无black排除(v74d black排除误伤肩部深色毛阴影; sit嘴影本身不在门内)。
        gray = ((mx - mn) <= 45) & (mx >= 85) & (mx <= 235) & (mn <= 195) & (al > 200) & ((mx - mn) <= 0.22 * mx)
        me = gray
        if not me.any():
            continue
        cand = me
        dark = mx < 90
        # v86 双判据(离线12帧/状态验证): matting灰残影=贴轮廓平滑色块; 合法阴影=体内毛纹暗部。
        #  A) wf>0.2: CC环8px内纯白(mn>=235)占比=贴轮廓代理(肩带0.37-0.5 vs 肚影0.05-0.11)
        #  B) std5<1.8: 平滑无毛纹(灰块1.1-1.7 vs 毛纹阴影>=2.0)
        # 验证: WALK FIX 718/帧 PROT 16; IDLE FIX 0 PROT 3781; SIT FIX 42 PROT 5580; RUN FIX 2641。
        white = (al > 200) & (mn >= 235)
        lum = rgb.mean(-1).astype(np.float32)
        mu = ndimage.uniform_filter(lum, 5)
        mu2 = ndimage.uniform_filter(lum * lum, 5)
        std5 = np.sqrt(np.clip(mu2 - mu * mu, 0, None))
        # v86 strict 中性灰通道(全状态): 源matting烘焙中性灰(idle 696k/sit 583k/walk/bath实测)。
        # 白肚暖影r-b 30-77、纯白mx>235 结构上不可能触发(r-b<=15 & mx<=235)，零误伤。
        strict = (((rgb[..., 0] - rgb[..., 2]) <= 15) & ((mx - mn) <= 30) & (mx >= 85) & (mx <= 235) & (al > 200))
        me = cand | strict
        lab, n = ndimage.label(me)
        m = np.zeros_like(gray)
        for i in range(1, n + 1):
            comp = (lab == i)
            if comp.sum() < 150:
                continue
            ring = ndimage.binary_dilation(comp, iterations=8) & ~comp & (al > 200)
            wf = float(white[ring].mean()) if ring.sum() else 0.0
            sm = float(std5[comp].mean())
            if not (wf > 0.2 or sm < 1.8):
                continue   # 体内毛纹阴影=合法，不修
            m |= comp
        m |= strict   # 中性灰无条件修
        if not m.any():
            continue
        # v86 向量化毛源填充: 每像素取最近合法毛色(等价原4向扫描, O(N))
        good = (al > 200) & ~m & ((mx - mn > 30) | ((mx > 215) & (mn > 200)))
        dist, (iy, ix) = ndimage.distance_transform_edt(~good, return_indices=True)
        a[m, 0] = rgb[iy, ix][m, 0]; a[m, 1] = rgb[iy, ix][m, 1]; a[m, 2] = rgb[iy, ix][m, 2]
        a[m, 3] = 255
        a[m & (dist > 200), 3] = 0   # 无合法毛源=垃圾边透明收缩
        save_retry(Image.fromarray(a.astype(np.uint8)), f)
        st_tot += int(m.sum()); nf += 1
    grand += st_tot
    print(st, 'frames=', nf, 'px=', st_tot)
print('GRAND TOTAL', grand)
