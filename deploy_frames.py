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
# walk/run = gait 定制态（2完整步态周期；golden 认可 28/15，labrador 30/32——换宠物以引擎 ANIMS 为准同步改这里）
ANIMS = {
    'idle': 101, 'walk': 28, 'run': 88, 'eat': 34, 'bark': 57,
    'sleep': 51, 'sit': 63, 'lick': 54, 'happy': 121, 'roll': 47,
    'dance': 57, 'stretch': 117, 'beg': 56, 'bath': 57,
    'surprised': 45, 'play_dead': 68, 'pet': 107,
    'kiss': 121, 'wave': 57, 'type': 49,  # v118: type裁稳定段49帧闭环
}

do_copy = '--copy' in sys.argv
only = [a for a in sys.argv[1:] if not a.startswith('--')]
os.makedirs(ASSETS, exist_ok=True)
# 部署格式铁律：道具/泡沫状态 PNG（webp有损压缩会在填充边界压出alpha碎洞=道具/泡沫闪）；其余 webp q95
# v71：bath 加入 PNG 集——湿毛泡沫的半透明 alpha 边与碗口同理，webp 压碎后泡沫边缘黑线闪
PROP_STATES = {'eat', 'bath', 'type'}
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
        for fp in fs:
            base = os.path.basename(fp)[:-4]
            if st in PROP_STATES:
                shutil.copy2(fp, os.path.join(ASSETS, base + '.png'))
            else:
                from PIL import Image as _I
                import time as _t
                # v78: Windows Defender/索引器写后瞬时扫描会锁文件=OSError 22，重试3次
                # v83: 4次不够(Defender扫描偶>2s)→8次×1.5s
                for _att in range(8):
                    try:
                        _I.open(fp).save(os.path.join(ASSETS, base + '.webp'), 'WEBP', quality=95, method=4)
                        break
                    except OSError:
                        _t.sleep(1.5)
                else:
                    raise OSError(f'write locked after retries: {base}')
        # prune stale: 帧数变更后 assets 旧帧残留（只copy不删会留幽灵帧被引擎误读）
        want = {os.path.basename(fp)[:-4] + ('.png' if st in PROP_STATES else '.webp') for fp in fs}
        for af in glob.glob(os.path.join(ASSETS, st + '_*.png')) + glob.glob(os.path.join(ASSETS, st + '_*.webp')):
            if os.path.basename(af) not in want:
                os.remove(af)
                print(f'  pruned stale {os.path.basename(af)}')
if do_copy:
    print('COPIED to assets/ (eat/bath=PNG, 其余webp)  → 下一步必须跑 final_fix.py 全量清洁 + fix_props.py audit eat')
print('PROBLEMS:', problems if problems else 'none')
