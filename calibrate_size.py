# -*- coding: utf-8 -*-
"""资产级尺寸校准：统一全状态上屏主体高度（主体忽大忽小根因修复）。

根因：引擎上屏主体高 ∝ 资产canvas内bbox高（tight: ×262/1024, 非tight: ×250/1024）。
若各状态资产内主体高度不一致（如 walk 帧偏小、run 帧偏大），上屏后同一宠物在不同
状态间主体大小跳变，用户报"忽大忽小"。

修复：先量化各状态上屏主体高，再按系数 f 放大/缩小（底边锚定=脚底不动，水平居中锚定），
写回原canvas。

量化流程（先跑这步拿数据，再决定系数）：
  python audit_quant.py          # 输出各状态上屏主体高（h列）
若发现某状态主体偏小（如 walk=85px vs idle=143px），用本脚本校准：
  python calibrate_size.py walk=1.50 run=1.10   (先备份!)

用法: python calibrate_size.py state1=f1 state2=f2 ...
  f=1.0 表示不改动；>1 放大；<1 缩小。
"""
import os
import shutil
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, 'assets')
BACKUP = os.path.join(ROOT, 'assets_backup_calibrate')


def frames_of(state):
    out = []
    i = 0
    while True:
        for ext in ('webp', 'png'):
            fn = os.path.join(ASSETS, f'{state}_{i:02d}.{ext}')
            if os.path.exists(fn):
                out.append(fn)
                break
        else:
            break
        i += 1
    return out


def calibrate(state, f):
    fns = frames_of(state)
    if not fns:
        print(f'{state}: no frames')
        return
    done = 0
    for fn in fns:
        im = Image.open(fn).convert('RGBA')
        w, h = im.size
        a = im.getchannel('A')
        bbox = a.getbbox()
        if bbox is None:
            continue
        x0, y0, x1, y1 = bbox
        bw, bh = x1 - x0, y1 - y0
        content = im.crop(bbox)
        nw, nh = max(2, int(round(bw * f))), max(2, int(round(bh * f)))
        if nw > w or nh > h:
            # 超出canvas：钳制等比
            g = min(w / nw, h / nh)
            nw, nh = int(nw * g), int(nh * g)
        content = content.resize((nw, nh), Image.LANCZOS)
        cx = (x0 + x1) / 2.0
        nx0 = int(round(cx - nw / 2.0))
        ny1 = y1  # 底边锚定
        ny0 = ny1 - nh
        canvas = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        canvas.paste(content, (nx0, ny0), content)
        if fn.endswith('.webp'):
            canvas.save(fn, 'WEBP', quality=95)
        else:
            canvas.save(fn)
        done += 1
    print(f'{state}: {done} frames ×{f}')


if __name__ == '__main__':
    specs = [a.split('=') for a in sys.argv[1:]]
    if not specs:
        print('usage: calibrate_size.py walk=1.5 run=1.1')
        sys.exit(1)
    os.makedirs(BACKUP, exist_ok=True)
    for state, fs in specs:
        f = float(fs)
        if abs(f - 1.0) < 1e-6:
            continue
        # 备份首帧代表（全帧备份太大，仅记录系数；原帧可从git恢复）
        for fn in frames_of(state)[:1]:
            shutil.copy2(fn, os.path.join(BACKUP, os.path.basename(fn)))
        calibrate(state, f)
    print('CALIB_DONE')
