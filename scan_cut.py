# -*- coding: utf-8 -*-
"""全状态直线切检测器：vcut(内容列右侧突空=垂直切)/hcut(内容行下方突空=水平切)。
假阳性说明：hcut 在 GROUND 底对齐线上是正常脚底着地行（beg/walk 等站立态会有），
需肉眼结合接触表判定；vcut 一律是真缺陷。
用法: python _scan_cut.py [状态...]  默认全状态"""
import glob, os, sys
import numpy as np
from PIL import Image

ALL = ['idle', 'sit', 'eat', 'bark', 'happy', 'roll', 'dance',
       'beg', 'bath', 'lick', 'surprised', 'play_dead', 'sleep', 'stretch',
       'walk', 'run']

for st in (sys.argv[1:] or ALL):
    fs = sorted(glob.glob(f'assets/{st}_*.png'))
    vb = hb = 0
    for f in fs:
        a = np.array(Image.open(f).convert('RGBA'))[:, :, 3]
        colcnt = (a > 0).sum(axis=0)
        rowcnt = (a > 0).sum(axis=1)
        vc = [int(x) for x in range(2, a.shape[1] - 2)
              if colcnt[x] >= 40 and colcnt[x + 1] <= 2 and colcnt[x + 2] <= 2]
        hc = [int(y) for y in range(2, a.shape[0] - 2)
              if rowcnt[y] >= 60 and rowcnt[y + 1] <= 2 and rowcnt[y + 2] <= 2]
        if vc:
            vb += 1
            if vb <= 4:
                print(f'  VCUT {os.path.basename(f)} x={vc[:3]}')
        if hc:
            hb += 1
            if hb <= 4:
                print(f'  HCUT {os.path.basename(f)} y={hc[:3]}')
    print(f'{st:12s} n={len(fs):3d} vcut_frames={vb} hcut_frames={hb}')
print('SCAN_DONE')
