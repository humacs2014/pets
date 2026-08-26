# -*- coding: utf-8 -*-
"""阶段5a: frames/ → assets/ 部署 + 帧数核对（对比引擎ANIMS）。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe deploy_frames.py [--copy] [state ...]
默认只报告，--copy 才实际复制；可指定只部署个别状态（如 deploy_frames.py --copy type）。
复制后必须对全量 assets 跑 final_fix.py 清洁。
"""
import os, sys, glob, shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(ROOT, 'frames')
ASSETS = os.path.join(ROOT, 'assets')

# 引擎 ANIMS 声明帧数（必须与主程序 ANIMS 字典 1:1）
# walk/run = gait 定制态（2完整步态周期；golden 认可 28/15，labrador 30/32，柴犬 mochi 28/88——换宠物以引擎 ANIMS 为准同步改这里）
# 追加状态（如 kiss/wave/type）同步在此登记帧数
# v110b 实测回填：idle48(calmest窗)/run80(长循环)/beg77(截断尾)/type119(ghost弃2帧)
ANIMS = {
    'idle': 48, 'walk': 44, 'run': 80, 'eat': 121, 'bark': 121,
    'sleep': 121, 'sit': 121, 'lick': 121, 'happy': 121, 'roll': 121,
    'dance': 121, 'stretch': 121, 'beg': 77, 'bath': 121,
    'surprised': 121, 'play_dead': 121, 'pet': 121,
    'kiss': 121, 'wave': 121, 'type': 119,
}

do_copy = '--copy' in sys.argv
only = [a for a in sys.argv[1:] if not a.startswith('--')]
os.makedirs(ASSETS, exist_ok=True)
# 部署格式铁律：道具/泡沫状态 PNG（webp有损压缩会在填充边界压出alpha碎洞=道具/泡沫闪/键盘透洞）；其余 webp q95
# v71：bath 加入 PNG 集——湿毛泡沫的半透明 alpha 边与碗口同理，webp 压碎后泡沫边缘黑线闪
# v118：type 键盘漏加进 PNG 集 → webp 压碎键帽填充边界=浅底透洞，一切含道具帧状态必须进此集合
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
    print('COPIED to assets/ (PROP_STATES=PNG, 其余webp)  → 下一步必须跑 final_fix.py 全量清洁 + fix_props.py audit 道具态')
print('PROBLEMS:', problems if problems else 'none')
