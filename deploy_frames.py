# -*- coding: utf-8 -*-
"""阶段5a: frames/ → assets/ 部署 + 帧数核对（对比引擎ANIMS）。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe deploy_frames.py [--copy]
默认只报告，--copy 才实际复制。复制后必须对全量 assets 跑 final_fix.py 清洁。
"""
import os, sys, glob, shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(ROOT, 'frames')
ASSETS = os.path.join(ROOT, 'assets')

# 引擎 ANIMS 声明帧数（必须与主程序 ANIMS 字典 1:1）
ANIMS = {
    'idle': 101, 'walk': 28, 'run': 15, 'eat': 34, 'bark': 57,
    'sleep': 51, 'sit': 63, 'lick': 54, 'happy': 121, 'roll': 121,
    'dance': 57, 'stretch': 117, 'beg': 56, 'bath': 57,
    'surprised': 45, 'play_dead': 68, 'pet': 107,
}

do_copy = '--copy' in sys.argv
os.makedirs(ASSETS, exist_ok=True)
problems = []
for st, want in ANIMS.items():
    fs = sorted(glob.glob(os.path.join(FRAMES, st + '_*.png')))
    got = len(fs)
    mark = 'OK ' if got == want else 'MISMATCH'
    print(f'{st:12s} frames={got:3d} anims={want:3d} {mark}')
    if got != want:
        problems.append(st)
    if do_copy and fs:
        for fp in fs:
            shutil.copy2(fp, os.path.join(ASSETS, os.path.basename(fp)))
if do_copy:
    print('COPIED to assets/  → 下一步必须跑 final_fix.py 全量清洁')
print('PROBLEMS:', problems if problems else 'none')
