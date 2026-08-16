# -*- coding: utf-8 -*-
"""阶段6 定量审计门（v56 缺陷语义，与 final_fix 清洁定义一致）。
真缺陷定义:
  rim 黑边 = 不透明暗像素在主体轮廓外(~fill_holes) —— 非自然硬黑线
  fringe   = alpha 1-15 且不贴边
  halo     = 30-127 半透明 CC, span>40 且贴边率<0.7（独立光环，非AA环）
  jitter   = 相邻帧高度突变（静态<6%，动态<15%，过渡态豁免）
用法: python audit_quant.py
"""
import os, glob
import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, binary_fill_holes, label as ccl

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, 'assets')
ANIMS = {'idle': 101, 'walk': 20, 'run': 15, 'eat': 34, 'bark': 57,
         'sleep': 51, 'sit': 63, 'lick': 54, 'happy': 62, 'roll': 121,
         'dance': 57, 'stretch': 117, 'beg': 56, 'bath': 57,
         'surprised': 45, 'play_dead': 68}
STATIC = {'idle', 'sit', 'beg', 'lick'}                    # 相邻突变<6%
TRANS = {'sleep', 'roll', 'stretch', 'play_dead', 'eat'}   # 姿态大过渡,豁免jitter
fails = []
for st, want in ANIMS.items():
    fs = sorted(glob.glob(os.path.join(ASSETS, st + '_*.png')))
    if len(fs) != want:
        fails.append(f'{st}: frames {len(fs)} != {want}')
    hs, rim_f, fringe_f, halo_f = [], 0, 0, 0
    for fp in fs:
        a = np.array(Image.open(fp).convert('RGBA'))
        al = a[:, :, 3].astype(np.int32)
        lum = a[:, :, :3].mean(axis=2)
        core = al > 127
        body = binary_fill_holes(al > 200)
        ys, xs = np.where(al > 40)
        if len(xs) == 0:
            fails.append(f'{st}/{os.path.basename(fp)}: empty'); continue
        hs.append(ys.max() - ys.min() + 1)
        if ((al > 127) & (lum < 50) & ~body).sum() > 20: rim_f += 1
        dil2 = binary_dilation(core, iterations=2)
        if (((al >= 1) & (al <= 15) & ~dil2).sum()) > 30: fringe_f += 1
        semi = (al >= 30) & (al <= 127)
        if semi.any():
            lab, n = ccl(semi, structure=np.ones((3, 3)))
            sizes = np.bincount(lab.ravel())
            for i in range(1, n + 1):
                if sizes[i] <= 300: continue
                m = lab == i
                ys2 = np.where(m.any(axis=1))[0]; xs2 = np.where(m.any(axis=0))[0]
                span = max(ys2.max() - ys2.min() + 1, xs2.max() - xs2.min() + 1)
                band = (m & dil2).sum() / max(m.sum(), 1)
                if span > 40 and band < 0.7: halo_f += 1
    hs = np.array(hs, float)
    adj = np.abs(np.diff(hs)) / hs[:-1] * 100
    maxadj = adj.max() if len(adj) else 0
    if st in TRANS:
        jtag, jlim = 'trans-exempt', 999
    elif st in STATIC:
        jtag, jlim = 'static', 6
    else:
        jtag, jlim = 'dynamic', 15
    if maxadj > jlim:
        fails.append(f'{st}: adj-jump {maxadj:.1f}% > {jlim} ({jtag})')
    extra = ''
    if rim_f: fails.append(f'{st}: rim {rim_f}'); extra += f' rim={rim_f}'
    if fringe_f: fails.append(f'{st}: fringe {fringe_f}'); extra += f' fringe={fringe_f}'
    if halo_f: fails.append(f'{st}: halo {halo_f}'); extra += f' halo={halo_f}'
    print(f'{st:11s} n={len(fs):3d} h={hs.mean():5.1f} adjmax={maxadj:5.1f}% [{jtag}]{extra}')
print('RESULT:', 'ALL PASS' if not fails else fails)
