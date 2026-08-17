# -*- coding: utf-8 -*-
"""对新 walk/run 视频直接抽原始帧拼网格 QA（绕开缓存的抽帧管线）。"""
import os, sys, subprocess, glob, math
from PIL import Image

os.chdir(os.path.dirname(os.path.abspath(__file__)))

def grid(name, n=12, cols=4):
    tmp = f'_qaraw_{name}'
    os.makedirs(tmp, exist_ok=True)
    for f in glob.glob(f'{tmp}/f_*.png'):
        os.remove(f)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', f'videos/{name}.mp4',
                    '-vf', 'fps=24', f'{tmp}/f_%04d.png'], check=True)
    fr = sorted(glob.glob(f'{tmp}/f_*.png'))
    idx = [int(i * (len(fr) - 1) / (n - 1)) for i in range(n)]
    ims = [Image.open(fr[i]).convert('RGB') for i in idx]
    w, h = ims[0].size
    tw = 220
    th = int(h * tw / w)
    ims = [im.resize((tw, th)) for im in ims]
    rows = math.ceil(n / cols)
    g = Image.new('RGB', (cols * tw, rows * th), 'white')
    for k, im in enumerate(ims):
        g.paste(im, ((k % cols) * tw, (k // cols) * th))
    out = f'_qa_{name}_raw.png'
    g.save(out)
    print(name, 'total frames:', len(fr), 'grid saved:', out)

for st in (sys.argv[1:] if len(sys.argv) > 1 else ['walk', 'run']):
    grid(st)
print('DONE')
