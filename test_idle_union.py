# -*- coding: utf-8 -*-
"""test_idle_union.py — 用idle测试正确的union逻辑：
rembg为mask主控(0/255)，BEN2仅在rembg=255区域内补充alpha细节
"""
import os, sys, subprocess, time, glob, shutil
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
VIDEOS = os.path.join(ROOT, 'videos')
TEST_OUT = os.path.join(ROOT, '_test_idle')
os.makedirs(TEST_OUT, exist_ok=True)

state = 'idle'
video_path = os.path.join(VIDEOS, f'{state}.mp4')

# Extract raw
tmp_raw = os.path.join(TEST_OUT, 'raw')
os.makedirs(tmp_raw, exist_ok=True)
cmd = ['ffmpeg', '-i', video_path, '-q:v', '2', os.path.join(tmp_raw, 'f_%05d.png'), '-y']
subprocess.run(cmd, capture_output=True, timeout=120)
raw_frames = sorted(glob.glob(os.path.join(tmp_raw, 'f_*.png')))
print(f'Got {len(raw_frames)} raw frames')

# 只取前5帧测试
test_frames = raw_frames[:5]

# BEN2
import torch
from ben2 import BEN_Base
from torchvision import transforms

device = torch.device('cuda')
model = BEN_Base().to(device).eval()
t_val = transforms.Compose([transforms.ToTensor()])
DIV = 128

ben2_dir = os.path.join(TEST_OUT, 'ben2')
os.makedirs(ben2_dir, exist_ok=True)

print('BEN2 inference...')
for i, raw_p in enumerate(test_frames):
    im = Image.open(raw_p).convert('RGB')
    w, h = im.size
    pw = ((w + DIV - 1) // DIV) * DIV
    ph = ((h + DIV - 1) // DIV) * DIV
    canvas = Image.new('RGB', (pw, ph), (241, 239, 238))
    canvas.paste(im, (0, 0))
    inp = t_val(canvas).unsqueeze(0).to(device)
    with torch.no_grad():
        res = model(inp).sigmoid().squeeze()
    mask = (res * 255).cpu().numpy().astype(np.uint8)[:h, :w]
    # 保存BEN2 mask供检查
    np.save(os.path.join(ben2_dir, f'{i}.npy'), mask)
    print(f'  BEN2 frame {i}: mask range {mask.min()}-{mask.max()}')

del model
torch.cuda.empty_cache()

# rembg
from rembg import new_session, remove
rembg_dir = os.path.join(TEST_OUT, 'rembg')
os.makedirs(rembg_dir, exist_ok=True)
PAD = 16
BG = (241, 239, 238)

print('rembg inference...')
sess = new_session('u2net_human_seg')
for i, raw_p in enumerate(test_frames):
    im = Image.open(raw_p)
    w, h = im.size
    pw2, ph2 = w + 2*PAD, h + 2*PAD
    canvas = Image.new('RGB', (pw2, ph2), BG)
    canvas.paste(im, (PAD, PAD))
    result = remove(canvas, session=sess)
    result = result.crop((PAD, PAD, PAD+w, PAD+h))
    result.save(os.path.join(rembg_dir, f'{i}.png'))
    arr = np.array(result.convert('RGBA'))
    a = arr[:,:,3]
    print(f'  rembg frame {i}: alpha range {a.min()}-{a.max()}, alpha=0: {(a==0).sum()}, alpha=255: {(a==255).sum()}')
del sess

# Union: rembg mask主控 + BEN2在前景区域补充
union_dir = os.path.join(TEST_OUT, 'union')
os.makedirs(union_dir, exist_ok=True)
print('Union...')
for i in range(len(test_frames)):
    rembg_arr = np.array(Image.open(os.path.join(rembg_dir, f'{i}.png')).convert('RGBA'))
    ben2_mask = np.load(os.path.join(ben2_dir, f'{i}.npy'))
    rgb = rembg_arr[:, :, :3]
    a_rem = rembg_arr[:, :, 3]
    
    # rembg mask: 0/255二值
    rembg_fg = a_rem > 128  # rembg认为的前景区域
    
    # 在rembg前景区域内，用BEN2 mask的精细alpha
    # 在rembg背景区域，alpha=0
    final_alpha = np.zeros_like(a_rem)
    final_alpha[rembg_fg] = ben2_mask[rembg_fg]  # 前景区域用BEN2精细值
    # 但如果BEN2在前景区域内值太低(<128)，保持rembg的255
    ben2_low = rembg_fg & (ben2_mask < 128)
    final_alpha[ben2_low] = 255  # rembg说是前景，BEN2不确定，信任rembg
    
    union_arr = np.dstack([rgb, final_alpha.astype(np.uint8)])
    out = Image.fromarray(union_arr, 'RGBA')
    out.save(os.path.join(union_dir, f'{i:03d}.png'))
    
    a = final_alpha
    mask_check = a > 10
    if mask_check.any():
        rows = np.any(mask_check, axis=1)
        cols = np.any(mask_check, axis=0)
        y0 = int(np.argmax(rows))
        y1 = int(len(rows) - np.argmax(rows[::-1]))
        x0 = int(np.argmax(cols))
        x1 = int(len(cols) - np.argmax(cols[::-1]))
        print(f'  union frame {i}: alpha {a.min()}-{a.max()}, tight bbox: y0={y0} y1={y1} x0={x0} x1={x1}, bh={y1-y0}')

print('\nTEST_DONE - check _test_idle/union/ for results')
