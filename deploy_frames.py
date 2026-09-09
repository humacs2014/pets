# -*- coding: utf-8 -*-
"""阶段5a: frames/ → assets/ 部署 + 帧数核对（对比引擎ANIMS）。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe deploy_frames.py [--copy] [state ...]
默认只报告，--copy 才实际复制。复制后必须对全量 assets 跑 final_fix.py 清洁。

体型统一由extract_frames.py的normalize_frames按TARGET_H做（参考golden_pet项目），
deploy只做纯copy，不做任何对齐/缩放。
"""
import os, sys, glob, shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(ROOT, 'frames')
ASSETS = os.path.join(ROOT, 'assets')

# 所有动作均为121帧（union_cutout.py BEN2+rembg抠图，灰色帧补帧后保持视频原始帧数）
ANIMS = {
    'idle': 121, 'walk': 121, 'run': 121, 'eat': 121, 'bark': 121,
    'sleep': 121, 'sit': 121, 'lick': 121, 'happy': 121, 'roll': 121,
    'dance': 121, 'stretch': 121, 'beg': 121, 'bath': 121,
    'surprised': 121, 'play_dead': 121, 'pet': 121,
    'kiss': 121, 'wave': 121, 'type': 121,
}

# 部署格式：道具/泡沫状态 PNG；其余 webp q95
PROP_STATES = {'eat', 'bath', 'type'}

# 帧编号位数（121帧需要3位）
FRAME_DIGITS = 3

do_copy = '--copy' in sys.argv
only = [a for a in sys.argv[1:] if not a.startswith('--')]
os.makedirs(ASSETS, exist_ok=True)

problems = []
for st, want in ANIMS.items():
    if only and st not in only:
        continue
    fs = sorted(glob.glob(os.path.join(FRAMES, st + '_*.png')))
    got = len(fs)
    mark = 'OK ' if got == want else 'MISMATCH'
    print(f'{st:12s} frames={got:3d} anims={want:3d} {mark}')
    if got != want:
        problems.append(st)
    if do_copy and fs:
        for i, fp in enumerate(fs):
            base = f'{st}_{i:0{FRAME_DIGITS}d}'
            if st in PROP_STATES:
                shutil.copy2(fp, os.path.join(ASSETS, base + '.png'))
            else:
                for _att in range(8):
                    try:
                        from PIL import Image
                        Image.open(fp).save(os.path.join(ASSETS, base + '.webp'),
                                            'WEBP', quality=95, method=4)
                        break
                    except OSError:
                        import time as _t; _t.sleep(1.5)
                else:
                    raise OSError(f'write locked: {base}')
            if (i + 1) % 30 == 0:
                print(f'  {st}: {i+1}/{len(fs)} deployed')

        # prune stale
        want_names = {f'{st}_{i:0{FRAME_DIGITS}d}' + ('.png' if st in PROP_STATES else '.webp')
                      for i in range(len(fs))}
        for af in (glob.glob(os.path.join(ASSETS, st + '_*.png'))
                   + glob.glob(os.path.join(ASSETS, st + '_*.webp'))):
            if os.path.basename(af) not in want_names:
                os.remove(af)
        print(f'  {st}: {len(fs)} frames deployed')

if do_copy:
    print('COPIED → next: final_fix.py')
print('PROBLEMS:', problems if problems else 'none')
