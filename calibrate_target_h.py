# -*- coding: utf-8 -*-
"""TARGET_H 可行性体检（阶段2→3之间自动跑，无需手工标定）。
结论: TARGET_H 是跨宠物通用成品锚定(站274/坐316/伸291/躺204)，不是标定值——
normalize_frames 的 scale=target_h/median(hs) 自动吸收任意视频原始尺寸。
本脚本严格复刻 normalize_frames 的 scale 公式，预测每个状态最终成品高度:
  scale = min(target_h/median(hs), 1.0) → uw*s>500钳制 → uh*s>476钳制 → 最终=median×scale
预测值偏离目标>8% = 该状态视频不可用（主体太小被scale≤1封顶 / 极端宽高比被钳制），
必须回阶段2重生成该状态视频（prompt 强调主体占画面更大比例）。
依赖: rembg(onnxruntime) numpy Pillow ffmpeg(在PATH)。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe calibrate_target_h.py
"""
import os, glob, subprocess, statistics
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

# extract_frames.py 通用常数（跨宠物不变，勿改）
TARGET_H = {'idle': 274, 'sit': 316, 'stretch': 291, 'sleep': 204}

def predict_final_h(state, sess):
    """镜像 normalize_frames: 原始分辨率抠图 → union-bbox → 完整 scale 公式。"""
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
    target = TARGET_H[state]
    scale = min(target / med, 1.0)          # ← 主体太小则封顶1.0（风险点1）
    capped = []
    if uw * scale > 500:                    # ← 宽度钳制（风险点2）
        scale = 500.0 / uw; capped.append('宽钳制')
    if uh * scale > 476:                    # ← 高度钳制（风险点3）
        scale = 476.0 / uh; capped.append('高钳制')
    if scale >= 1.0 and med < target:
        capped.append('主体过小(scale封顶1.0)')
    return int(med * scale), capped

if __name__ == '__main__':
    sess = new_session('isnet-general-use')
    fails = []
    for st, target in TARGET_H.items():
        pred, capped = predict_final_h(st, sess)
        if pred is None:
            print(f'{st}: 视频缺失或抠图失败'); fails.append(st); continue
        dev = abs(pred - target) / target
        flag = 'OK' if dev <= TOL else 'FAIL'
        note = f" [{'+'.join(capped)}]" if capped else ''
        print(f'{st:>8}: 预测成品高 {pred} vs 目标 {target} (偏差{dev:.0%}) [{flag}]{note}')
        if dev > TOL:
            fails.append(st)
    if fails:
        print(f'\nFAIL: {fails} 不可用 → 回阶段2重生成这些状态视频，'
              f'prompt 加"the dog fills most of the frame"提高主体占比后重跑本体检。')
        raise SystemExit(1)
    print('\nPASS: 全部状态可达成目标尺寸，extract_frames.py TARGET_H 直接用通用常数，无需任何改动。')
