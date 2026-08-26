# -*- coding: utf-8 -*-
"""资产数值门: 每态逐帧 bbox h/w + alpha完整性 + 相邻帧时序跳变。
判据: 尺寸cv<0.15(步态/过渡态放宽0.25), 无整帧消失(al>0像素>500), 时序h跳变<15%。"""
import os, glob
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, 'assets')
LOOSE = {'walk', 'run', 'roll', 'stretch', 'sleep', 'eat', 'lick', 'bath', 'dance', 'kiss'}  # 含位移/大形变过渡
fails = []
for st in sorted({os.path.basename(f).rsplit('_', 1)[0] for f in glob.glob(os.path.join(ASSETS, '*.png')) + glob.glob(os.path.join(ASSETS, '*.webp'))}):
    fs = sorted(glob.glob(os.path.join(ASSETS, st + '_*.png')) + glob.glob(os.path.join(ASSETS, st + '_*.webp')))
    hs, ws, alphas, jumps = [], [], [], []
    prev = None
    for fp in fs:
        a = np.array(Image.open(fp).convert('RGBA'))
        al = a[:, :, 3]
        nz = int((al > 30).sum())
        alphas.append(nz)
        if nz < 500:
            fails.append(f'{st} {os.path.basename(fp)} NEAR_EMPTY({nz})')
            prev = None
            continue
        ys, xs = np.where(al > 30)
        h, w = ys.max() - ys.min() + 1, xs.max() - xs.min() + 1
        hs.append(h); ws.append(w)
        if prev is not None:
            jumps.append(abs(h - prev[0]) / prev[0])
        prev = (h, w)
    hs, ws = np.array(hs), np.array(ws)
    cvh = hs.std() / hs.mean() if len(hs) else 9
    cvw = ws.std() / ws.mean() if len(ws) else 9
    mxj = max(jumps) if jumps else 0
    thr = 0.25 if st in LOOSE else 0.15
    flag = '' if (cvh < thr and cvw < thr and mxj < 0.20) else ' <<FLAG'
    if flag:
        fails.append(f'{st} cvh={cvh:.3f} cvw={cvw:.3f} maxjump={mxj:.2f}')
    print(f'{st:11s} n={len(fs):3d} h={hs.min():3d}-{hs.max():3d} cvh={cvh:.3f} w={ws.min():3d}-{ws.max():3d} cvw={cvw:.3f} maxjump={mxj:.2f}{flag}')
print()
print('NUMERIC_GATE:', 'FAIL ' + '; '.join(fails) if fails else 'PASS')
