# -*- coding: utf-8 -*-
"""量化: 各状态狗主体bbox尺寸一致性 + sleep/eat网格目视"""
import os, sys, glob
import numpy as np
from PIL import Image

AS = 'assets'
STATES = ['idle','walk','run','sit','bark','sleep','eat','roll','dance','stretch','happy','beg','play_dead','lick','shake','spin']

def dog_bbox(im, exclude_bottom_prop=False):
    a = np.array(im.convert('RGBA'))[:,:,3]
    ys, xs = np.where(a > 30)
    if len(xs) == 0: return None
    return xs.min(), xs.max(), ys.min(), ys.max()

print("=== 各状态主体尺寸 (中位数, 画布512?) ===")
ref = None
for st in STATES:
    files = sorted(glob.glob(os.path.join(AS, f'{st}_*.png')))
    if not files: 
        print(f"{st}: NO FILES"); continue
    ws, hs = [], []
    for f in files:
        im = Image.open(f)
        bb = dog_bbox(im)
        if bb is None: continue
        ws.append(bb[1]-bb[0]); hs.append(bb[3]-bb[2])
    if not ws: continue
    mw, mh = int(np.median(ws)), int(np.median(hs))
    tag = ''
    if st == 'idle': ref = (mw, mh)
    elif ref:
        tag = f'  vs idle: w{mw/ref[0]:.2f}x h{mh/ref[1]:.2f}x'
    print(f"{st:10s} n={len(ws):3d} med_w={mw:3d} med_h={mh:3d}{tag}")

def grid(st, ncols=8, out=None, maxn=64):
    files = sorted(glob.glob(os.path.join(AS, f'{st}_*.png')))[:maxn]
    ims = [Image.open(f).convert('RGBA') for f in files]
    w, h = ims[0].size
    rows = (len(ims)+ncols-1)//ncols
    canvas = Image.new('RGB', (ncols*w//2, rows*h//2), (245,245,250))
    for i, im in enumerate(ims):
        im2 = im.resize((w//2, h//2))
        canvas.paste(im2, ((i%ncols)*w//2, (i//ncols)*h//2), im2)
    out = out or f'_qa_{st}_grid.png'
    canvas.save(out)
    print(f"{st} grid {len(ims)} frames -> {out}")

grid('sleep')
grid('eat', ncols=6, maxn=34)
