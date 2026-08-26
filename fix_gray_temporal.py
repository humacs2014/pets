# -*- coding: utf-8 -*-
"""时间轴一致灰色阴影清除（灰色阴影+闪烁根因修复，mochi v87b 验证逻辑通用化）。

两类灰阴影及其修复链（按序跑，勿跳）：
1. matting 中性灰边（邻接透明边界，walk胸口/run裆部/idle腋下）→ scripts/fix_all_gray.py
2. 视频源烘焙的暖调灰带（腿内侧/脚底/肚子下缘，嵌在白毛里，sat 20-45%）→ 本脚本
   ⚠️ 只逐帧白化不做时序统一 = 暗带随动作逐帧漂移（帧间 inter/union≈0.008）
   = 播放时同位置忽有忽无 = 闪烁（用户报"局部白色闪烁"的头号根因）。
   本脚本机制：每轮「全帧检测→并集蒙版→白化+提亮至毛白232」迭代到残留归零，
   并集保证所有帧同一位置同一处理 → 帧间零差异 → 闪烁消除。

判据（白毛犬实测饱和度双峰：阴影 sat<=45%，棕毛 sat>=50%，谷在45-50%）：
  warm = r>b+8 & sat<0.45 & 120<mx<230（暖调灰）
  neut = (mx-mn)<=12 & 140<mx<226（中性灰）
  邻域低饱和门（9x9盒模糊 sat<0.32）保护棕毛/彩色毛（棕毛邻域饱和度高不触发）
RGBA 安全：仅改 RGB，alpha 原样。幂等（收敛后残留=0，重跑零改动）。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe fix_gray_temporal.py [state...]
不带参数=全状态扫描。
"""
import glob
import sys

import numpy as np
from PIL import Image, ImageFilter

MAX_ROUNDS = 8


def detect_gray(rgb, opaque):
    """rgb: int16 HxWx3; 返回阴影掩码。"""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = rgb.max(2)
    mn = rgb.min(2)
    sat = (mx - mn) / (mx + 1.0)
    warm = (r > b + 8) & (sat < 0.45) & (mx > 120) & (mx < 230)
    neut = ((mx - mn) <= 12) & (mx > 140) & (mx < 226)
    return (warm | neut) & opaque


def apply_mask(arr, mask, nb_ok):
    """白化+提亮 mask&nb_ok 像素，保留 alpha。返回处理像素数。"""
    m = mask & nb_ok
    if not m.any():
        return 0
    rgb = arr[..., :3]
    # 提亮至毛白 232（去色相 + 去亮度差一步完成）；只提不降
    for c in range(3):
        ch = rgb[..., c]
        ch[m] = np.maximum(ch[m].astype(np.int16), 232).astype(np.uint8)
    return int(m.sum())


def frames_of(st):
    return sorted(glob.glob(f'assets/{st}_*.png')) + \
           sorted(glob.glob(f'assets/{st}_*.webp'))


def fix_state(st):
    files = frames_of(st)
    if not files:
        print(f'{st}: no frames')
        return
    frames = [np.asarray(Image.open(f).convert('RGBA')).copy() for f in files]

    # 邻域低饱和门：基于首帧饱和度（白毛区全帧一致），一次计算复用
    ref = frames[0][..., :3].astype(np.float32)
    mx = ref.max(2); mn = ref.min(2)
    sat = (mx - mn) / (mx + 1.0)
    nb = np.asarray(
        Image.fromarray((sat * 255).astype(np.uint8), 'L')
        .filter(ImageFilter.BoxBlur(6))
    ).astype(np.float32) / 255.0
    nb_ok = nb < 0.32

    total = 0
    rounds = 0
    for rnd in range(MAX_ROUNDS):
        # 全帧检测 → 并集
        union = None
        for arr in frames:
            m = detect_gray(arr[..., :3].astype(np.int16), arr[..., 3] == 255)
            union = m if union is None else (union | m)
        cnt = int((union & nb_ok).sum())
        if cnt == 0:
            break
        for arr in frames:
            total += apply_mask(arr, union, nb_ok)
        rounds = rnd + 1

    for f, arr in zip(files, frames):
        if f.endswith('.webp'):
            Image.fromarray(arr, 'RGBA').save(f, quality=95)
        else:
            Image.fromarray(arr, 'RGBA').save(f)

    # 终检残留
    resid = sum(int(detect_gray(arr[..., :3].astype(np.int16),
                                 arr[..., 3] == 255).sum()) for arr in frames)
    print(f'{st}: frames={len(frames)} rounds={rounds} '
          f'total_fixed={total} final_resid={resid}')


if __name__ == '__main__':
    if len(sys.argv) > 1:
        states = sys.argv[1:]
    else:
        import os
        seen = set()
        states = []
        for f in glob.glob('assets/*_*'):
            st = os.path.basename(f).rsplit('_', 1)[0]
            if not st.startswith('_') and st not in seen:
                seen.add(st)
                states.append(st)
    for st in states:
        fix_state(st)
