# -*- coding: utf-8 -*-
"""frames/ → assets/ 部署 + 帧数核对（对比引擎ANIMS）。
用法: python deploy_frames.py [--copy]  (默认只报告，--copy才实际复制)
"""
import os, sys, glob, shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(ROOT, 'frames')
ASSETS = os.path.join(ROOT, 'assets')

# 引擎 ANIMS 声明帧数（labrador_pet.py，husky v56 值）
ANIMS = {
    'idle': 101, 'walk': 20, 'run': 15, 'eat': 34, 'bark': 57,
    'sleep': 51, 'sit': 63, 'lick': 54, 'happy': 62, 'roll': 121,
    'dance': 57, 'stretch': 117, 'beg': 56, 'bath': 57,
    'surprised': 45, 'play_dead': 68,
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
    print('COPIED to assets/')
print('PROBLEMS:', problems if problems else 'none')
