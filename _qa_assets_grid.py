"""assets级QA网格: 从 assets/<st>_*.png 均匀采样12帧拼图。用法: python _qa_assets_grid.py idle walk ..."""
import os, sys, glob, math
from PIL import Image

def grid(st):
    fs = sorted(glob.glob(f'assets/{st}_*.png'),
                key=lambda p: int(os.path.basename(p).rsplit('_', 1)[1].split('.')[0]))
    n = len(fs)
    if n == 0:
        print(f'{st}: no assets'); return
    idx = [min(int(i * (n - 1) / 11), n - 1) for i in range(12)]
    ims = [Image.open(fs[i]).convert('RGB') for i in idx]
    w, h = ims[0].size
    cols, rows = 4, 3
    sc = 220 / w
    tw, th = 220, int(h * sc)
    canvas = Image.new('RGB', (cols * tw, rows * th), (30, 30, 30))
    for k, im in enumerate(ims):
        im = im.resize((tw, th))
        canvas.paste(im, ((k % cols) * tw, (k // cols) * th))
    out = f'_qa_{st}_assets.png'
    canvas.save(out)
    print(f'{st} assets {n} frames -> {out}')

for st in (sys.argv[1:] if len(sys.argv) > 1 else ['idle']):
    grid(st)
print('DONE')
