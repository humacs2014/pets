# -*- coding: utf-8 -*-
"""cutout_ben2_only.py — 仅用BEN2抠图（通过ben2包加载模型）。
每帧直接输出，不做灰色检测。用法: python cutout_ben2_only.py [state1 state2 ...]
"""
import os, sys, glob, shutil, subprocess, time
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
VIDEOS = os.path.join(ROOT, 'videos')
FRAMES = os.path.join(ROOT, 'frames')
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

def run_ben2(raw_frames, out_dir):
    """使用 ben2 包的 BEN_Base 模型抠图。resize到960×960满足内部整除约束。"""
    import torch
    from ben2 import BEN_Base
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model = BEN_Base().to(device).eval()
    from torchvision import transforms
    t_val = transforms.Compose([transforms.ToTensor()])
    INF_SIZE = 1024  # 1024满足所有BEN2内部整除约束(1024%128=0, 1024/4=256, 256%12=8→swin window可padding)
    for i, raw_p in enumerate(raw_frames):
        out_p = os.path.join(out_dir, f'{i:05d}.png')
        if os.path.exists(out_p):
            continue
        im = Image.open(raw_p).convert('RGB')
        w, h = im.size
        # resize到960×960推理
        canvas = im.resize((INF_SIZE, INF_SIZE), Image.LANCZOS)
        inp = t_val(canvas).unsqueeze(0).to(device)
        with torch.no_grad():
            res = model(inp)[-1].sigmoid().squeeze(0)
        # mask resize回原始尺寸
        mask = (res[0] * 255).cpu().numpy().astype(np.uint8)
        mask_im = Image.fromarray(mask).resize((w, h), Image.LANCZOS)
        mask = np.array(mask_im)
        out = Image.fromarray(np.dstack([np.array(im), mask]), 'RGBA')
        out.save(out_p)
        if (i + 1) % 20 == 0:
            print(f'    BEN2 {i+1}/{len(raw_frames)}', flush=True)
    del model
    torch.cuda.empty_cache()

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
    ben2_dir = os.path.join(work_dir, 'ben2')
    os.makedirs(ben2_dir, exist_ok=True)

    # 抽帧
    print(f'  [Step 0] Extract raw frames...', flush=True)
    all_raw = extract_all_raw(video_path, state)
    n_total = len(all_raw)
    print(f'  Got {n_total} raw frames', flush=True)

    # BEN2 抠图
    print(f'  [Step 1] BEN2...', flush=True)
    t0 = time.time()
    run_ben2(all_raw, ben2_dir)
    print(f'  BEN2 done in {time.time()-t0:.1f}s', flush=True)

    # 输出到 frames/
    print(f'  [Step 2] Writing {n_total} frames...', flush=True)
    for i in range(n_total):
        ben2_p = os.path.join(ben2_dir, f'{i:05d}.png')
        if not os.path.exists(ben2_p):
            print(f'  SKIP frame {i}: BEN2 missing')
            continue
        img = Image.open(ben2_p).convert('RGBA')
        out_path = os.path.join(FRAMES, f'{state}_{i:03d}.png')
        img.save(out_path)

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
