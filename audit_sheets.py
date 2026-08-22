# -*- coding: utf-8 -*-
"""阶段6 审计门辅助：生成接触表(contact sheet)供 vision 判定。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe audit_sheets.py [模式]
  identity  → 每状态取中间帧拼4×4带标签（身份一致性门）
  pose ST N → 状态ST抽N帧横排（姿态语义门，默认6帧）
  deform ST → 状态ST全部署帧网格11帧/行（解剖变形门）
输出: _audit/<模式>.png
"""
import os, sys, glob
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, 'assets')
OUT = os.path.join(ROOT, '_audit')
os.makedirs(OUT, exist_ok=True)
CELL = 160

def label_img(text):
    d = Image.new('RGB', (CELL, 24), (255, 255, 255))
    dr = ImageDraw.Draw(d)
    dr.text((4, 4), text, fill=(0, 0, 0))
    return d

def sheet(frames_paths, cols, title):
    rows = (len(frames_paths) + cols - 1) // cols
    sh = Image.new('RGB', (cols * CELL, rows * (CELL + 24)), (255, 255, 255))
    for i, p in enumerate(frames_paths):
        im = Image.open(p).convert('RGBA')
        bg = Image.new('RGB', im.size, (255, 255, 255))
        bg.paste(im, (0, 0), im.split()[3])
        bg = bg.resize((CELL, CELL), Image.LANCZOS)
        r, c = divmod(i, cols)
        sh.paste(label_img(os.path.basename(p)), (c * CELL, r * (CELL + 24)))
        sh.paste(bg, (c * CELL, r * (CELL + 24) + 24))
    out = os.path.join(OUT, title + '.png')
    sh.save(out)
    print('saved', out, sh.size)

def _glob_st(st):
    return sorted(glob.glob(os.path.join(ASSETS, st + '_*.png')) +
                  glob.glob(os.path.join(ASSETS, st + '_*.webp')))

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'identity'
    states = sorted({os.path.basename(f).rsplit('_', 1)[0]
                     for f in glob.glob(os.path.join(ASSETS, '_*.png'.replace('_*', '*_*.png')))
                     if not os.path.basename(f).startswith('_')}) or sorted(
        {os.path.basename(f).rsplit('_', 1)[0]
         for f in glob.glob(os.path.join(ASSETS, '*_*.webp'))
         if not os.path.basename(f).startswith('_')})
    if mode == 'identity':
        picks = []
        for st in states:
            fs = _glob_st(st)
            if fs:
                picks.append(fs[len(fs) // 2])
        sheet(picks, 4, 'identity_4x4')
    elif mode == 'pose':
        st = sys.argv[2]
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 6
        fs = _glob_st(st)
        idxs = [int(round(i * (len(fs) - 1) / (n - 1))) for i in range(n)]
        sheet([fs[i] for i in idxs], n, f'pose_{st}')
    elif mode == 'deform':
        st = sys.argv[2]
        fs = _glob_st(st)
        sheet(fs, 11, f'deform_{st}')
    else:
        print('unknown mode'); sys.exit(1)
