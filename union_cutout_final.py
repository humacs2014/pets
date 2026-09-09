# -*- coding: utf-8 -*-
"""union_cutout_final.py — BEN2+rembg union抠图（最终版）
逻辑：rembg做前景mask(>128=前景)，BEN2仅在rembg前景区补充精细alpha
禁用灰色检测，每帧都是真帧
"""
import os, sys, glob, shutil, subprocess, time
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
VIDEOS = os.path.join(ROOT, 'videos')
FRAMES = os.path.join(ROOT, 'frames')
PAD = 16
BG = (241, 239, 238)

os.makedirs(FRAMES, exist_ok=True)

ALL_STATES = ['idle','walk','run','eat','bark','sleep','sit','lick','happy',
              'roll','dance','stretch','beg','bath','surprised','play_dead',
              'pet','kiss','wave','type']

def get_video_frame_count(video_path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-count_frames',
                       '-select_streams', 'v:0',
                       '-show_entries', 'stream=nb_read_frames',
                       '-of', 'csv=p=0', video_path],
                      capture_output=True, text=True, timeout=30)
    return int(r.stdout.strip())

def extract_all_raw(video_path, state):
    tmp = os.path.join(ROOT, f'_raw_{state}')
    os.makedirs(tmp, exist_ok=True)
    for f in glob.glob(os.path.join(tmp, '*.png')):
        os.remove(f)
    cmd = ['ffmpeg', '-i', video_path, '-q:v', '2',
           os.path.join(tmp, 'f_%05d.png'), '-y']
    subprocess.run(cmd, capture_output=True, timeout=120)
    return sorted(glob.glob(os.path.join(tmp, 'f_*.png')))

def run_rembg(raw_frames, work_dir):
    from rembg import new_session, remove
    out_dir = os.path.join(work_dir, 'rembg')
    os.makedirs(out_dir, exist_ok=True)
    sess = new_session('u2net')
    for i, raw_p in enumerate(raw_frames):
        out_p = os.path.join(out_dir, f'{i:05d}.png')
        if os.path.exists(out_p):
            continue
        im = Image.open(raw_p)
        w, h = im.size
        pw, ph = w + 2*PAD, h + 2*PAD
        canvas = Image.new('RGB', (pw, ph), BG)
        canvas.paste(im, (PAD, PAD))
        result = remove(canvas, session=sess)
        result = result.crop((PAD, PAD, PAD+w, PAD+h))
        result.save(out_p)
        if (i + 1) % 20 == 0:
            print(f'    rembg {i+1}/{len(raw_frames)}', flush=True)
    del sess

def run_ben2(raw_frames, work_dir):
    import torch
    from ben2 import BEN_Base
    out_dir = os.path.join(work_dir, 'ben2')
    os.makedirs(out_dir, exist_ok=True)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = BEN_Base().to(device).eval()
    from torchvision import transforms
    t_val = transforms.Compose([transforms.ToTensor()])
    # pad到128的倍数
    DIV = 128
    for i, raw_p in enumerate(raw_frames):
        out_p = os.path.join(out_dir, f'{i:05d}.npy')
        if os.path.exists(out_p):
            continue
        im = Image.open(raw_p).convert('RGB')
        w, h = im.size
        pw = ((w + DIV - 1) // DIV) * DIV
        ph = ((h + DIV - 1) // DIV) * DIV
        canvas = Image.new('RGB', (pw, ph), BG)
        canvas.paste(im, (0, 0))
        inp = t_val(canvas).unsqueeze(0).to(device)
        with torch.no_grad():
            res = model(inp).squeeze()  # 已sigmoid，不要再sigmoid!
        mask = (res * 255).cpu().numpy().astype(np.uint8)[:h, :w]
        np.save(out_p, mask)
        if (i + 1) % 20 == 0:
            print(f'    BEN2 {i+1}/{len(raw_frames)}', flush=True)
    del model
    torch.cuda.empty_cache()

def make_union(rembg_arr, ben2_mask):
    """rembg做前景mask主控，BEN2仅在rembg前景区补充精细alpha"""
    a_rem = rembg_arr[:, :, 3]
    rgb = rembg_arr[:, :, :3]
    
    rembg_fg = a_rem > 128  # rembg认为的前景
    
    final_alpha = np.zeros_like(a_rem)
    final_alpha[rembg_fg] = ben2_mask[rembg_fg]  # 前景区用BEN2精细值
    # BEN2在rembg前景区值太低(<200)，信任rembg
    ben2_low = rembg_fg & (ben2_mask < 200)
    final_alpha[ben2_low] = a_rem[ben2_low]
    
    return np.dstack([rgb, final_alpha.astype(np.uint8)])

def process_state(state):
    video_path = os.path.join(VIDEOS, f'{state}.mp4')
    if not os.path.exists(video_path):
        print(f'  SKIP {state}: video not found')
        return
    print(f'\n=== {state} ===', flush=True)
    total = get_video_frame_count(video_path)
    print(f'  Video: {total} frames', flush=True)

    work_dir = os.path.join(ROOT, f'_work_{state}')
    os.makedirs(work_dir, exist_ok=True)

    all_raw = extract_all_raw(video_path, state)
    n_total = len(all_raw)
    print(f'  Got {n_total} raw frames', flush=True)

    print(f'  [Step 1] BEN2...', flush=True)
    t0 = time.time()
    run_ben2(all_raw, work_dir)
    print(f'  BEN2 done in {time.time()-t0:.1f}s', flush=True)

    print(f'  [Step 2] rembg...', flush=True)
    t0 = time.time()
    run_rembg(all_raw, work_dir)
    print(f'  rembg done in {time.time()-t0:.1f}s', flush=True)

    print(f'  [Step 3] Union...', flush=True)
    rembg_dir = os.path.join(work_dir, 'rembg')
    ben2_dir = os.path.join(work_dir, 'ben2')

    for i in range(n_total):
        rembg_p = os.path.join(rembg_dir, f'{i:05d}.png')
        ben2_p = os.path.join(ben2_dir, f'{i:05d}.npy')
        if not os.path.exists(rembg_p) or not os.path.exists(ben2_p):
            continue
        rembg_arr = np.array(Image.open(rembg_p).convert('RGBA'))
        ben2_mask = np.load(ben2_p)
        union_arr = make_union(rembg_arr, ben2_mask)
        out_path = os.path.join(FRAMES, f'{state}_{i:03d}.png')
        Image.fromarray(union_arr, 'RGBA').save(out_path)

    print(f'  ✓ {state} complete: {n_total} frames', flush=True)
    for d in [work_dir, os.path.join(ROOT, f'_raw_{state}')]:
        if os.path.exists(d):
            shutil.rmtree(d)

if __name__ == '__main__':
    states = sys.argv[1:] if len(sys.argv) > 1 else ALL_STATES
    for s in states:
        process_state(s)
    print('\nALL DONE')
