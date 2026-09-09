# -*- coding: utf-8 -*-
"""TARGET_H 可行性体检（阶段2→3之间自动跑，无需手工标定；1024 画布管线镜像）。
本脚本严格复刻 extract_frames.py normalize_frames 的 scale 公式，预测每个状态最终成品高度:
  scale = min(target_h/median(hs), 1.6) → uw*s>0.977*CANVAS 钳制 → uh*s>0.930*CANVAS 钳制
预测值偏离目标>8% = 该状态视频不可用（主体太小被放大上限1.6封顶 / 极端宽高比被钳制），
必须回阶段2重生成该状态视频（prompt 强调主体占画面更大比例）。
TARGET_H 自动从同目录 extract_frames.py 读取（两处永不脱节）；
videos/ 目录缺失或无该状态视频的状态自动跳过（含 sleep 逐帧姿态缩放态，无单一 TARGET_H 条目）。
依赖: rembg(onnxruntime) numpy Pillow ffmpeg(在PATH)。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe calibrate_target_h.py
"""
import os, re, glob, subprocess, statistics
import numpy as np
from PIL import Image
from rembg import new_session, remove

VIDS = 'videos'
BG = (241, 239, 238)   # 与 extract_frames.py 一致
PAD = 200
TMP = '_calib'
SAMPLE_FPS = 4
N_SAMPLES = 10
TOL = 0.08

# 从 extract_frames.py 动态读取（1024画布认可值），绝不硬编码副本
def _load_target_h():
    src = open('extract_frames.py', encoding='utf-8').read()
    m = re.search(r'^TARGET_H\s*=\s*\{([^}]*)\}', src, re.M | re.S)
    if not m:
        raise SystemExit('FAIL: extract_frames.py 未找到 TARGET_H 字典')
    out = {}
    for k, v in re.findall(r"'(\w+)'\s*:\s*([0-9.]+)", m.group(1)):
        out[k] = float(v)
    if not out:
        raise SystemExit('FAIL: TARGET_H 解析为空')
    return out

def predict_final_h(state, sess, target, canvas=1024):
    """镜像 normalize_frames: 原始分辨率抠图 → union-bbox → 完整 scale 公式（1024画布）。"""
    mp4 = os.path.join(VIDS, state + '.mp4')
    if not os.path.exists(mp4):
        return None, None
    fd = os.path.join(TMP, state)
    os.makedirs(fd, exist_ok=True)
    if not glob.glob(os.path.join(fd, 'f_*.png')):
        subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', mp4,
                        '-vf', f'fps={SAMPLE_FPS}', os.path.join(fd, 'f_%04d.png')], check=True)
    fps = sorted(glob.glob(os.path.join(fd, 'f_*.png')))
    step = max(1, len(fps) // N_SAMPLES)
    boxes = []
    for fp in fps[::step][:N_SAMPLES]:
        im = Image.open(fp).convert('RGB')
        W, H = im.size
        pad = Image.new('RGB', (W + 2 * PAD, H + 2 * PAD), BG)
        pad.paste(im, (PAD, PAD))
        cut = remove(pad, session=sess).crop((PAD, PAD, PAD + W, PAD + H))
        b = np.asarray(cut)[:, :, 3] > 40
        if b.any():
            boxes.append(b)
    if len(boxes) < 3:
        return None, None
    xs, ys = [], []
    for b in boxes:
        yy, xx = np.where(b)
        xs += [xx.min(), xx.max()]; ys += [yy.min(), yy.max()]
    uw, uh = max(xs) + 1 - min(xs), max(ys) + 1 - min(ys)
    hs = [(np.where(b)[0].max() - np.where(b)[0].min()) for b in boxes]
    med = float(statistics.median(hs))
    scale = min(target / med, 1.6)        # ← 上限1.6：1024档需对源放大~1.1-1.2×；1.6封顶=主体过小风险
    capped = []
    if uw * scale > 0.977 * canvas:       # ← 宽度钳制
        scale = 0.977 * canvas / uw; capped.append('宽钳制')
    if uh * scale > 0.930 * canvas:       # ← 高度钳制
        scale = 0.930 * canvas / uh; capped.append('高钳制')
    if scale >= 1.6 and med * 1.6 < target:
        capped.append('主体过小(1.6封顶)')
    return int(med * scale), capped

if __name__ == '__main__':
    TARGET_H = _load_target_h()
    sess = new_session('isnet-general-use')
    fails = []
    checked = 0
    for st, target in TARGET_H.items():
        pred, capped = predict_final_h(st, sess, target)
        if pred is None:
            print(f'{st:>10}: 视频缺失或抠图失败（跳过）')
            continue
        checked += 1
        dev = abs(pred - target) / target
        flag = 'OK' if dev <= TOL else 'FAIL'
        note = f" [{'+'.join(capped)}]" if capped else ''
        print(f'{st:>10}: 预测成品高 {pred} vs 目标 {int(target)} (偏差{dev:.0%}) [{flag}]{note}')
        if dev > TOL:
            fails.append(st)
    if checked == 0:
        raise SystemExit('FAIL: 无任何状态视频可体检（videos/ 目录为空或缺失）')
    if fails:
        print(f'\nFAIL: {fails} 不可用 → 回阶段2重生成这些状态视频，'
              f'prompt 加"the dog fills most of the frame"提高主体占比后重跑本体检。')
        raise SystemExit(1)
    print('\nPASS: 全部状态可达成目标尺寸，extract_frames.py TARGET_H 直接用通用常数，无需任何改动。')
