# -*- coding: utf-8 -*-
"""union_cutout.py v2 — 禁用灰色检测，每帧直接输出BEN2+rembg union结果。
用法: python union_cutout.py [state1 state2 ...]
不传参则处理全部20个状态。
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
    sess = new_session('u2net_human_seg')
    for i, raw_p in enumerate(raw_frames):
        out_p = os.path.join(out_dir, f'{i:05d}.png')
        if os.path.exists(out_p):
            continue
        im = Image.open(raw_p)
        # pad
        w, h = im.size
        pw, ph = w + 2*PAD, h + 2*PAD
        canvas = Image.new('RGB', (pw, ph), BG)
        canvas.paste(im, (PAD, PAD))
        result = remove(canvas, session=sess)
        # unpad
        result = result.crop((PAD, PAD, PAD+w, PAD+h))
        result.save(out_p)
    del sess

def run_ben2(raw_frames, work_dir):
    out_dir = os.path.join(work_dir, 'ben2')
    os.makedirs(out_dir, exist_ok=True)
    import torch
    from transformers import AutoModelForImageSegmentation
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = AutoModelForImageSegmentation.from_pretrained(
        'Kwai-Kolors/BEN2-base', trust_remote_code=True).to(device).eval()
    from torchvision import transforms
    t_val = transforms.Compose([transforms.ToTensor()])
    for i, raw_p in enumerate(raw_frames):
        out_p = os.path.join(out_dir, f'{i:05d}.png')
        if os.path.exists(out_p):
            continue
        im = Image.open(raw_p).convert('RGB')
        inp = t_val(im).unsqueeze(0).to(device)
        with torch.no_grad():
            res = model(inp)[-1].sigmoid().squeeze(0)
        mask = (res[0] * 255).cpu().numpy().astype(np.uint8)
        out = Image.fromarray(np.dstack([np.array(im), mask]), 'RGBA')
        out.save(out_p)
    del model
    torch.cuda.empty_cache()

def make_union(rembg_arr, ben2_arr):
    a_rem = rembg_arr[:, :, 3].astype(float)
    a_ben = ben2_arr[:, :, 3].astype(float)
    union_alpha = np.maximum(a_rem, a_ben).astype(np.uint8)
    rgb = ben2_arr[:, :, :3].astype(float).copy()
    ben_zero = a_ben < 1
    rem_nonzero = a_rem > 0
    both_zero = ben_zero & ~rem_nonzero
    rgb[rem_nonzero & ben_zero] = rembg_arr[rem_nonzero & ben_zero, :3]
    rgb[both_zero] = rembg_arr[both_zero, :3]
    return np.dstack([rgb.astype(np.uint8), union_alpha.astype(np.uint8)])

def process_state(state):
    video_path = os.path.join(VIDEOS, f'{state}.mp4')
    if not os.path.exists(video_path):
        print(f'  SKIP {state}: video not found')
        return

    print(f'\n=== {state} ===', flush=True)
    total_video_frames = get_video_frame_count(video_path)
    print(f'  Video: {total_video_frames} frames', flush=True)

    work_dir = os.path.join(ROOT, f'_work_{state}')
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)
    os.makedirs(work_dir, exist_ok=True)

    # 抽帧
    print(f'  [Step 0] Extract all raw frames...', flush=True)
    all_raw = extract_all_raw(video_path, state)
    n_total = len(all_raw)
    print(f'  Got {n_total} raw frames', flush=True)

    # BEN2 主力
    print(f'  [Step 1] BEN2 (primary)...', flush=True)
    t0 = time.time()
    run_ben2(all_raw, work_dir)
    print(f'  BEN2 done in {time.time()-t0:.1f}s', flush=True)

    # rembg 辅助
    print(f'  [Step 2] rembg (auxiliary)...', flush=True)
    t0 = time.time()
    run_rembg(all_raw, work_dir)
    print(f'  rembg done in {time.time()-t0:.1f}s', flush=True)

    # 直接输出每帧union结果，不做灰色检测
    print(f'  [Step 3] Writing {n_total} frames (union, no gray filter)...', flush=True)
    rembg_dir = os.path.join(work_dir, 'rembg')
    ben2_dir = os.path.join(work_dir, 'ben2')

    for i in range(n_total):
        rembg_p = os.path.join(rembg_dir, f'{i:05d}.png')
        ben2_p = os.path.join(ben2_dir, f'{i:05d}.png')

        if not os.path.exists(rembg_p) or not os.path.exists(ben2_p):
            print(f'  SKIP frame {i}: missing rembg/ben2 output')
            continue

        rembg_arr = np.array(Image.open(rembg_p).convert('RGBA'))
        ben2_arr = np.array(Image.open(ben2_p).convert('RGBA'))
        union_arr = make_union(rembg_arr, ben2_arr)
        out_path = os.path.join(FRAMES, f'{state}_{i:03d}.png')
        Image.fromarray(union_arr, 'RGBA').save(out_path)

    print(f'  ✓ {state} complete: {n_total} frames', flush=True)

    # 清理
    for d in [work_dir, os.path.join(ROOT, f'_raw_{state}')]:
        if os.path.exists(d):
            shutil.rmtree(d)

if __name__ == '__main__':
    states = sys.argv[1:] if len(sys.argv) > 1 else ALL_STATES
    for s in states:
        process_state(s)
    print('\nALL DONE')
