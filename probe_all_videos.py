# -*- coding: utf-8 -*-
"""探测 20 个源视频：规格 + 首帧背景色 + 主体位置。"""
import os, subprocess, json
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
VD = os.path.join(ROOT, 'videos')
os.makedirs(os.path.join(ROOT, '_probe'), exist_ok=True)
STATES = sorted(os.path.splitext(f)[0] for f in os.listdir(VD) if f.endswith('.mp4'))
print(f'{len(STATES)} states: {STATES}')
for st in STATES:
    mp4 = os.path.join(VD, st + '.mp4')
    out = subprocess.check_output(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height,r_frame_rate,nb_frames',
         '-show_entries', 'format=duration', '-of', 'json', mp4])
    j = json.loads(out)
    s = j['streams'][0]
    dur = float(j['format']['duration'])
    # 首帧
    fp = os.path.join(ROOT, '_probe', st + '_f0.png')
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', mp4, '-vf', 'select=eq(n\\,0)',
                    '-frames:v', '1', fp], check=True)
    arr = np.array(Image.open(fp).convert('RGB')).astype(int)
    H, W, _ = arr.shape
    corners = np.concatenate([arr[:20, :20].reshape(-1, 3), arr[:20, -20:].reshape(-1, 3),
                              arr[-20:, :20].reshape(-1, 3), arr[-20:, -20:].reshape(-1, 3)])
    bg = corners.mean(axis=0)
    bgstd = corners.std(axis=0)
    # 主体 bbox（与背景色距>50）
    d = np.linalg.norm(arr - bg, axis=-1)
    fg = d > 50
    if fg.sum() > 50:
        ys, xs = np.where(fg)
        bb = f'x[{xs.min()}-{xs.max()}] y[{ys.min()}-{ys.max()}] w={xs.max()-xs.min()+1} h={ys.max()-ys.min()+1} px={fg.sum()}'
    else:
        bb = 'NO_FG'
    print(f'{st:12s} {s["width"]}x{s["height"]} {s["r_frame_rate"]}fps {s.get("nb_frames","?")}f {dur:.2f}s bg=RGB{tuple(bg.astype(int))}±{tuple(bgstd.astype(int))} | {bb}')
