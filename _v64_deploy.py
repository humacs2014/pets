# -*- coding: utf-8 -*-
"""v64 部署：assets_v64(tight png) → assets(webp q95)。
删除16个tight状态旧方画布webp，walk认可版不动。"""
import os, glob
from concurrent.futures import ProcessPoolExecutor
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'assets_v64')
DST = os.path.join(ROOT, 'assets')
TIGHT = ['idle', 'run', 'eat', 'bark', 'sleep', 'sit', 'lick', 'happy',
         'roll', 'dance', 'stretch', 'beg', 'bath', 'surprised',
         'play_dead', 'pet']

def conv(fn):
    src = os.path.join(SRC, fn)
    dst = os.path.join(DST, fn[:-4] + '.webp')
    im = Image.open(src)
    im.save(dst, 'WEBP', quality=95, method=4)
    return os.path.getsize(dst)

def main():
    # 1. 删除旧方画布webp（tight状态）
    removed = 0
    for st in TIGHT:
        for f in glob.glob(os.path.join(DST, f'{st}_*.webp')):
            os.remove(f)
            removed += 1
    print(f'removed {removed} old square-canvas webp')
    # 2. tight png → webp q95
    pngs = sorted(os.path.basename(f) for f in glob.glob(os.path.join(SRC, '*.png')))
    print(f'converting {len(pngs)} tight frames...')
    tot = 0
    with ProcessPoolExecutor(max_workers=6) as ex:
        for i, sz in enumerate(ex.map(conv, pngs)):
            tot += sz
    print(f'DONE webp total = {tot/1e6:.1f}MB')
    # 3. 校验帧数
    for st in TIGHT:
        n = len(glob.glob(os.path.join(DST, f'{st}_*.webp')))
        print(f'{st:10s} {n}')
    print('walk kept:', len(glob.glob(os.path.join(DST, 'walk_*.webp'))))

if __name__ == '__main__':
    main()
