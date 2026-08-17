# -*- coding: utf-8 -*-
"""阶段3 抽帧管线模板（v56 验证版）。换宠物改 CONFIG 段即可。
流程: ffmpeg原生24fps抽帧 → isnet抠图(带PAD边距) → 质量过滤最长干净窗口
      → union-bbox+宽度钳制 → 512归一化(姿态档高度锚定) → 循环结构(intro/loop/ping-pong)
      → 重采样到ANIMS帧数 → harden alpha → 输出 frames/{state}_NN.png
用法: python extract_frames.py [状态名...]（默认全部）
依赖: rembg(onnxruntime) scipy numpy Pillow ffmpeg(在PATH)
"""
import os, sys, glob, subprocess
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))

# ══════════ CONFIG（换宠物改这里） ══════════
VIDS_DIR = 'videos'            # 阶段2下载的 mp4（{state}.mp4）
OUT_DIR = 'frames'             # 抽帧输出目录
BG = (241, 239, 238)           # rembg 画布底色（与白底视频匹配）
PAD = 200                      # 抠图前加边距防边缘伪影，抠后裁回
CANVAS = 512
GROUND = 478                   # walk/run 脚底线（canvas 512 内）

# ping-pong 往复类（正播+倒播）
PINGPONG = {'idle', 'eat', 'bark', 'sit', 'roll', 'dance', 'beg', 'bath'}
# 一次性/过渡类
ONESHOT = {'sleep', 'stretch', 'happy', 'surprised', 'play_dead'}
# 高度锚定 target_h 按姿态档（跨档=忽大忽小；husky 实测，新宠物按同法标定）：
#   站立272-278 / 坐316 / 伸展291 / 躺卧212-217
TARGET_H = {
    'idle': 274, 'bark': 274, 'happy': 274, 'dance': 274,
    'beg': 274, 'bath': 274, 'eat': 274, 'sit': 316,
    'stretch': 291,
    # walk/run 侧面视角属站立档（husky实测 walk=274 run=272）
    'walk': 274, 'run': 274,
    # lick/surprised 须锚定站立档（husky实测 270/265，否则拉布拉多424/406忽大忽小）
    'lick': 274, 'surprised': 274,
}
# 重采样到引擎 ANIMS 声明帧数（引擎零改动按 count 加载）
RT_FRAMES = {
    'idle': 101, 'eat': 34, 'bark': 57, 'sit': 63, 'roll': 121,
    'dance': 57, 'beg': 56, 'bath': 57, 'stretch': 117,
    'surprised': 45, 'play_dead': 68, 'sleep': 51, 'lick': 54,
    'happy': 62,   # ONESHOT也须重采样到ANIMS帧数，否则拉布拉多36帧≠62播放过快
    'walk': 20, 'run': 15,
}
ALL_STATES = ['idle', 'sit', 'eat', 'bark', 'happy', 'roll', 'dance',
              'beg', 'bath', 'lick', 'surprised', 'play_dead', 'sleep', 'stretch',
              'walk', 'run']
# walk/run 需侧面视角单独生成，单独处理（首尾最接近帧对作loop边界）
# ══════════ CONFIG END ══════════

os.makedirs(OUT_DIR, exist_ok=True)
from rembg import new_session, remove

def extract(name):
    """ffmpeg 原生 24fps 全帧抽帧（降采样+插值补帧=清晰度流畅度双杀）。"""
    mp4 = os.path.join(VIDS_DIR, name + '.mp4')
    if not os.path.exists(mp4):
        mp4s = sorted(glob.glob(os.path.join(VIDS_DIR, name + '_c*.mp4')))
        if not mp4s:
            return None
        mp4 = mp4s[0]
    fd = os.path.join(ROOT, '_raw_' + name)
    # 新鲜度铁律: 视频比缓存新 → 旧视频缓存必须作废(2026-08-17 walk/run 重生成被缓存短路事故)
    if os.path.isdir(fd) and os.path.getmtime(mp4) > os.path.getmtime(fd):
        import shutil
        shutil.rmtree(fd)
        print(f'  [cache invalid] _raw_{name} older than video, re-extracting', flush=True)
    os.makedirs(fd, exist_ok=True)
    if len(glob.glob(os.path.join(fd, 'f_*.png'))) < 10:
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', mp4,
                        '-vf', 'fps=24',
                        os.path.join(fd, 'f_%04d.png')], check=True)
    return sorted(glob.glob(os.path.join(fd, 'f_*.png')))

def cutout_frames(fps, state):
    """isnet-general-use 抠图（白底/白毛必须用此模型；u2net 液化白色头部）。"""
    mats_dir = os.path.join(ROOT, '_mats_' + state)
    mp4 = os.path.join(VIDS_DIR, state + '.mp4')
    # 新鲜度铁律: 视频比抠图缓存新 → 旧mask作废(与_raw同事故, 见extract)
    if os.path.isdir(mats_dir) and os.path.exists(mp4) and \
            os.path.getmtime(mp4) > os.path.getmtime(mats_dir):
        import shutil
        shutil.rmtree(mats_dir)
        print(f'  [cache invalid] _mats_{state} older than video, re-cutting', flush=True)
    os.makedirs(mats_dir, exist_ok=True)
    existing = sorted(glob.glob(os.path.join(mats_dir, 'm_*.png')))
    if len(existing) >= len(fps):
        return existing
    sess = new_session('isnet-general-use')
    mats = []
    for i, fp in enumerate(fps):
        outp = os.path.join(mats_dir, f'm_{i:04d}.png')
        if os.path.exists(outp):
            mats.append(outp); continue
        im = Image.open(fp).convert('RGB')
        W, H = im.size
        pad = Image.new('RGB', (W + 2 * PAD, H + 2 * PAD), BG)
        pad.paste(im, (PAD, PAD))
        cut = remove(pad, session=sess)
        cut = cut.crop((PAD, PAD, PAD + W, PAD + H))
        cut.save(outp)
        mats.append(outp)
        if i % 20 == 0:
            print(f'    mat {i}/{len(fps)}', flush=True)
    return mats

def alpha_metrics(mat):
    from scipy.ndimage import label
    a = np.array(Image.open(mat).convert('RGBA'))[:, :, 3]
    H, W = a.shape
    fg = a > 128
    total = fg.sum()
    if total == 0:
        return {'main_frac': 0, 'edge': True, 'area': 0}
    lab, n = label(fg)
    sizes = np.bincount(lab.ravel()); sizes[0] = 0
    main_frac = sizes.max() / total
    ys, xs = np.where(fg)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    # 脚触底正常；只拒顶/左/右边缘接触（真裁切风险）
    edge = x1 >= W - 4 or x0 <= 3 or y0 <= 3
    return {'main_frac': main_frac, 'edge': edge, 'area': int(total)}

def motion_scores(mats):
    """逐帧alpha差均值=运动量。站立intro≈0，步态相位大。"""
    prev, out = None, []
    for m in mats:
        a = np.array(Image.open(m).convert('RGBA'))[:, :, 3].astype(np.float32)
        if prev is not None:
            out.append(float(np.mean(np.abs(a - prev))))
        prev = a
    out.append(out[-1] if out else 0.0)
    return np.array(out)

def gait_window(mats, min_len=8):
    """walk/run专用: 放宽面积容差(步态伸展/收拢面积差大), 在干净段里选运动量最大的窗口。
    2026-08-17事故: clean_window最长段选中站立intro而非奔跑段。"""
    ms = [alpha_metrics(m) for m in mats]
    areas = np.array([m['area'] for m in ms])
    med = np.median(areas[areas > 0]) if (areas > 0).any() else 1
    ok = [m['main_frac'] >= 0.99 and not m['edge']
          and abs(m['area'] - med) / max(med, 1) <= 0.45 and m['area'] > 800
          for m in ms]
    runs, s = [], 0
    for i in range(len(ok) + 1):
        if i == len(ok) or not ok[i]:
            if i - s >= min_len:
                runs.append((s, i))
            s = i + 1
    if not runs:
        return None
    mot = motion_scores(mats)
    return max(runs, key=lambda r: float(np.mean(mot[r[0]:r[1]])) * (r[1] - r[0]) ** 0.3)

PROFILE_STATES = {'idle': 'high', 'bark': 'high', 'sit': 'low'}

def posture_window(mats, min_len=16, mode='high'):
    """按姿态宽高比选窗: mode='high'站立态选纯侧身段(跳3/4正面intro);
    mode='low'坐姿选稳坐段(跳站姿intro)。
    2026-08-17事故: idle intro 3/4正面→多腿错觉; sit intro站姿帧→引擎站↔坐跳变。"""
    ok, ars = [], []
    for m in mats:
        a = np.array(Image.open(m).convert('RGBA'))[:, :, 3]
        ys, xs = np.where(a > 30)
        if len(xs) == 0:
            ok.append(False); ars.append(0.0); continue
        ok.append(True)
        ars.append((xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1))
    ars = np.array(ars)
    sm = np.array([np.median(ars[max(0, i - 2):i + 3]) for i in range(len(ars))])
    oka = np.array(ok)
    pct = np.percentile(sm[oka], 45) if mode == 'high' else np.percentile(sm[oka], 55)
    good = oka & (sm >= pct if mode == 'high' else sm <= pct)
    best_s, best_l, s, l = 0, 0, 0, 0
    for i in range(len(good) + 1):
        if i == len(good) or not good[i]:
            if l > best_l:
                best_l, best_s = l, s
            s, l = i + 1, 0
        else:
            l += 1
    if best_l < min_len:
        return None
    return best_s, best_s + best_l

def clean_window(mats):
    """逐帧打分（主CC占比≥0.999、无顶左右边缘、面积偏差≤25%、面积>1000），取最长连续干净段。"""
    ms = [alpha_metrics(m) for m in mats]
    areas = np.array([m['area'] for m in ms])
    med = np.median(areas[areas > 0]) if (areas > 0).any() else 1
    ok = [m['main_frac'] >= 0.999 and not m['edge']
          and abs(m['area'] - med) / max(med, 1) <= 0.25 and m['area'] > 1000
          for m in ms]
    best_s, best_l, s, l = 0, 0, 0, 0
    for i, o in enumerate(ok):
        if o:
            l += 1
            if l > best_l:
                best_l, best_s = l, s
        else:
            s, l = i + 1, 0
    if best_l < 6:
        ok = [m['main_frac'] >= 0.99 and not m['edge'] and m['area'] > 800 for m in ms]
        best_s, best_l, s, l = 0, 0, 0, 0
        for i, o in enumerate(ok):
            if o:
                l += 1
                if l > best_l:
                    best_l, best_s = l, s
            else:
                s, l = i + 1, 0
    return best_s, best_s + best_l, sum(ok), len(ok)

def normalize_frames(mat_paths, target_h=None):
    """union-bbox 裁切 → 512 归一化 + 宽度钳制（防横躺姿态左右裁切），底部对齐。"""
    imgs = [Image.open(p).convert('RGBA') for p in mat_paths]
    boxes = [np.array(f)[:, :, 3] > 40 for f in imgs]
    xs, ys = [], []
    for b in boxes:
        yy, xx = np.where(b)
        if len(xx) == 0: continue
        xs += [xx.min(), xx.max()]; ys += [yy.min(), yy.max()]
    if not xs:
        return None
    ux0, uy0, ux1, uy1 = min(xs), min(ys), max(xs) + 1, max(ys) + 1
    uw, uh = ux1 - ux0, uy1 - uy0
    scale = min(470.0 / max(uw, uh), 1.0)
    if target_h:
        hs = [(np.where(b)[0].max() - np.where(b)[0].min()) for b in boxes if b.any()]
        if hs:
            scale = min(target_h / float(np.median(hs)), 1.0)
    # v56 宽度钳制：横躺姿态防左右裁切
    if uw * scale > 500: scale = 500.0 / uw
    if uh * scale > 476: scale = 476.0 / uh
    bottom = GROUND
    frames = []
    for im in imgs:
        c = im.crop((ux0, uy0, ux1, uy1))
        tw, th = max(1, int(c.width * scale)), max(1, int(c.height * scale))
        c = c.resize((tw, th), Image.LANCZOS)
        canvas = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
        canvas.paste(c, ((CANVAS - tw) // 2, bottom - th), c.split()[3])
        frames.append(canvas)
    return frames

def harden_alpha(img):
    a = img.getchannel('A')
    a = a.point(lambda v: 255 if v > 100 else v)
    img.putalpha(a)
    return img

def resample_seq(seq, target):
    n = len(seq)
    if n == target or n < 2:
        return seq
    idxs = [int(round(i * (n - 1) / (target - 1))) for i in range(target)]
    return [seq[i] for i in idxs]

def stabilize_h(frames):
    """水平相位相关稳定化（保留垂直弹跳），消除主体漂移。"""
    alphas = [np.array(f)[:, :, 3].astype(np.float32) for f in frames]
    shifts = [0.0]
    for i in range(1, len(frames)):
        f0, f1 = np.fft.fft2(alphas[i - 1]), np.fft.fft2(alphas[i])
        cp = f0 * np.conj(f1)
        peak = np.fft.ifft2(cp / (np.abs(cp) + 1e-9))
        pk = np.unravel_index(np.argmax(np.abs(peak)), peak.shape)
        H, W = alphas[i].shape
        dy = pk[0] if pk[0] < H // 2 else pk[0] - H
        dx = pk[1] if pk[1] < W // 2 else pk[1] - W
        dx = max(-8, min(8, dx))
        shifts.append(shifts[-1] + dx)
    out = []
    for i, f in enumerate(frames):
        arr = np.array(f)
        s = int(round(shifts[i] - np.mean(shifts)))
        arr = np.roll(arr, -s, axis=1)
        if s > 0: arr[:, :s, 3] = 0
        elif s < 0: arr[:, s:, 3] = 0
        out.append(Image.fromarray(arr))
    return out

def find_loop_pair(frames, min_span_frac=0.33):
    """暴力找首尾最接近帧对作 loop 边界（walk/run 用）。"""
    arrs = [np.array(f)[:, :, 3].astype(np.float32) for f in frames]
    n = len(arrs)
    min_span = max(4, int(n * min_span_frac))
    best = (0, n - 1, 1e18)
    for i in range(0, n - min_span):
        for j in range(i + min_span, n):
            d = np.mean(np.abs(arrs[i] - arrs[j]))
            if d < best[2]:
                best = (i, j, d)
    return best

def find_gait_loop(frames, min_span_frac=0.28, max_span_frac=0.75):
    """walk/run 步态循环: 自相关找周期T(完整步态周期=相似度峰值), 再相位对齐起点。
    2026-08-17事故: find_loop_pair选到半周期→loop=半步→"同一姿势循环"无跑动感。
    min_span=0.28: 24fps幼犬gallop周期≈12-18帧, 低于此的T是半周期假谷(v1实测T=9=半步)。"""
    arrs = np.array([np.array(f)[:, :, 3].astype(np.float32) for f in frames])
    n = len(arrs)
    min_span = max(4, int(n * min_span_frac))
    max_span = min(n - 2, int(n * max_span_frac))
    best_T, best_score = min_span, 1e18
    scores = {}
    for T in range(min_span, max_span + 1):
        ds = np.array([np.mean(np.abs(arrs[i] - arrs[i + T])) for i in range(n - T)])
        scores[T] = float(ds.mean())
    # 局部极小优先(周期峰值), 避免大T假最小
    cands = [T for T in range(min_span + 1, max_span)
             if scores[T] <= scores[T - 1] and scores[T] <= scores[T + 1]]
    if cands:
        best_T = min(cands, key=lambda T: scores[T])
    else:
        best_T = min(scores, key=scores.get)
    best_score = scores[best_T]
    T = best_T
    i0 = int(min(range(n - T), key=lambda i: np.mean(np.abs(arrs[i] - arrs[i + T]))))
    print(f'  gait loop: period T={T} start={i0} score={best_score:.1f}', flush=True)
    return i0, i0 + T

def process_state(name):
    print(f'== {name} ==', flush=True)
    fps = extract(name)
    if not fps:
        print(f'  SKIP: no mp4', flush=True); return
    mats = cutout_frames(fps, name)
    if name in ('sleep', 'stretch'):
        # 过渡视频不做面积过滤（躺/站面积差异大），取全部非边缘帧
        ms = [alpha_metrics(m) for m in mats]
        sel = [m for m, t in zip(mats, ms) if not t['edge'] and t['area'] > 1000]
        print(f'  transition: kept {len(sel)}/{len(mats)}', flush=True)
    else:
        if name in ('walk', 'run'):
            gw = gait_window(mats)
            if gw:
                s, e = gw
                print(f'  gait window [{s}:{e}] len={e-s} (motion-selected)', flush=True)
            else:
                s, e, _, _ = clean_window(mats)
                print(f'  gait window fallback [{s}:{e}]', flush=True)
        else:
            s, e, nclean, ntot = clean_window(mats)
            print(f'  clean window [{s}:{e}] len={e-s} ({nclean}/{ntot} ok)', flush=True)
            if name in PROFILE_STATES:
                pw = posture_window(mats[s:e], mode=PROFILE_STATES[name])
                if pw:
                    s2, e2 = pw
                    print(f'  profile window [{s + s2}:{s + e2}] len={e2 - s2} (side-facing selected)', flush=True)
                    s, e = s + s2, s + e2
        if e - s < 4:
            print('  TOO FEW, skip', flush=True); return
        sel = mats[s:e]
    frames = normalize_frames(sel, TARGET_H.get(name))
    if not frames:
        print('  normalize failed', flush=True); return
    frames = stabilize_h(frames)
    if name in PINGPONG:
        seq = frames + frames[-2:0:-1]
    elif name in ONESHOT:
        seq = frames          # intro+loop 分段在引擎侧/部署脚本处理
    else:
        if name in ('walk', 'run'):
            i, j = find_gait_loop(frames)
            seq = frames[i:j + 1]
        else:
            i, j, d = find_loop_pair(frames)
            seq = frames[i:j + 1]
            print(f'  loop pair ({i},{j}) seam={d:.1f}', flush=True)
    if name in RT_FRAMES:
        seq = resample_seq(seq, RT_FRAMES[name])
    for k, f in enumerate(seq):
        harden_alpha(f).save(os.path.join(OUT_DIR, f'{name}_{k:02d}.png'))
    print(f'  WROTE {len(seq)} frames → {OUT_DIR}/{name}_*', flush=True)
    return len(seq)

if __name__ == '__main__':
    only = sys.argv[1:] if len(sys.argv) > 1 else None
    for n in (only or ALL_STATES):
        try:
            process_state(n)
        except Exception as ex:
            print(f'  ERROR {n}: {ex}', flush=True)
    print('EXTRACT_DONE', flush=True)
