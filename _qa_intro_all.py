# -*- coding: utf-8 -*-
"""全16状态开头帧专项QA: 每状态取前3帧(0/1/2)横拼, 4x4网格。
用户投诉点=各动作开头主体形象(奇怪后腿), 此表一眼扫全。"""
import os, glob
from PIL import Image, ImageDraw

STATES = ['idle', 'sit', 'eat', 'bark', 'happy', 'roll', 'dance', 'sleep',
          'stretch', 'beg', 'play_dead', 'lick', 'surprised', 'bath', 'run', 'walk']
CELL_W, CELL_H = 330, 150
cols, rows = 4, 4
canvas = Image.new('RGB', (cols * CELL_W, rows * (CELL_H + 18)), (25, 25, 25))
d = ImageDraw.Draw(canvas)
for i, st in enumerate(STATES):
    fs = sorted(glob.glob(f'assets/{st}_*.png'),
                key=lambda p: int(os.path.basename(p).rsplit('_', 1)[1].split('.')[0]))
    r, c = divmod(i, cols)
    y0 = r * (CELL_H + 18)
    d.text((c * CELL_W + 6, y0 + 2), f'{st} ({len(fs)}f)', fill=(255, 220, 0))
    pick = [fs[min(k, len(fs) - 1)] for k in (0, 1, 2)]
    for k, fp in enumerate(pick):
        im = Image.open(fp).convert('RGB')
        sc = min(105 / im.width, 140 / im.height)
        im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))))
        canvas.paste(im, (c * CELL_W + k * 110, y0 + 18 + (140 - im.height)))
canvas.save('_qa_intro_all.png')
print('saved _qa_intro_all.png', canvas.size)
