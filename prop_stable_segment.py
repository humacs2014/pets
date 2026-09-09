# -*- coding: utf-8 -*-
"""prop 交互态（type 等）稳定段检测 + 最优闭环裁切（mochi v118 验证逻辑模板化）。

用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe prop_stable_segment.py <state> [--frames-dir frames]

背景（v118 教训）：img2vid 道具交互视频前几秒道具常未锚定（键盘抬起/倾斜、带手或异物
残影），全视频直接入循环 = 循环开头道具位置跳变+残影闪现。必须先数值检测稳定段、只在
稳定段内选闭环，再人工目视确认稳定段无异物后裁切。

输出：
1. 逐帧主体 bbox（y 中心、宽、高）序列 + 位置聚类 → 报告是否含未稳定 intro（类数>1）
2. 稳定段内 IoU 最优闭环帧对（首尾最接近）+ 建议裁切区间 [i, j]
3. 裁切后首尾帧对比图（<state>_seam_check.jpg，白底并排）供目视

判据全数值自动，裁切动作不执行（只报告建议区间，目视确认后手工改 extract 或直接裁）。
"""
import os
import sys
import glob
import numpy as np
from PIL import Image

def load_frames(frames_dir, state):
    files = sorted(glob.glob(os.path.join(frames_dir, f'{state}_*.png')))
    frames = []
    for fp in files:
        im = np.array(Image.open(fp).convert('RGBA'))
        frames.append(im)
    return files, frames

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    state = sys.argv[1]
    frames_dir = 'frames'
    if '--frames-dir' in sys.argv:
        frames_dir = sys.argv[sys.argv.index('--frames-dir') + 1]

    files, frames = load_frames(frames_dir, state)
    if not frames:
        print(f'FAIL: no frames at {frames_dir}/{state}_*.png')
        sys.exit(1)
    n = len(frames)
    print(f'{state}: {n} frames loaded')

    # ── 1) 逐帧主体 bbox（alpha>100 的包围盒） ──
    boxes = []
    for im in frames:
        m = im[:, :, 3] > 100
        ys, xs = np.where(m)
        if len(xs) == 0:
            boxes.append(None)
            continue
        boxes.append((xs.min(), xs.max(), ys.min(), ys.max()))

    # 主体位置特征：bbox 中心 y（道具位置跳变主要表现为 y/宽 突变）
    keys = []
    for b in boxes:
        if b is None:
            keys.append(np.nan)
            continue
        x0, x1, y0, y1 = b
        keys.append((y0 + y1) / 2.0)
    keys = np.array(keys)
    valid = ~np.isnan(keys)

    # ── 2) 位置聚类（简单 1D 分箱：中心 y 相邻帧差 >8px 视为位置变化事件） ──
    events = []
    prev = keys[valid][0] if valid.any() else None
    last_event = -1
    idxs = np.where(valid)[0]
    for pos, fi in zip(keys[idxs], idxs):
        if prev is not None and abs(pos - prev) > 8 and fi - last_event > 3:
            events.append((fi, float(pos)))
            last_event = fi
        prev = pos

    if events:
        print(f'位置突变事件 {len(events)} 处（>1 = 含未稳定 intro/道具跳变段）:')
        for fi, pos in events:
            print(f'  frame {fi:3d}: center_y → {pos:.1f}')
        stable_start = events[-1][0]
        print(f'→ 稳定段起点 = frame {stable_start}（最后一处突变之后）')
    else:
        stable_start = 0
        print('无位置突变 → 全视频稳定')

    # ── 3) 稳定段内 IoU 最优闭环帧对 ──
    seg = list(range(stable_start, n))
    if len(seg) < 8:
        print(f'FAIL: 稳定段仅 {len(seg)} 帧，视频质量不足')
        sys.exit(1)
    masks = [(frames[i][:, :, 3] > 100) for i in seg]
    best = []
    min_span = max(6, int(len(seg) * 0.3))
    for a in range(len(seg) - min_span):
        for b in range(a + min_span, len(seg)):
            inter = np.logical_and(masks[a], masks[b]).sum()
            union = np.logical_or(masks[a], masks[b]).sum()
            iou = inter / union
            best.append((iou, a, b))
    best.sort(reverse=True)
    print(f'\n稳定段 [{stable_start}, {n-1}]（{len(seg)} 帧）内 top5 闭环帧对:')
    for iou, a, b in best[:5]:
        print(f'  IoU={iou:.4f}  abs frame {seg[a]}-{seg[b]}  len={b-a+1}')

    iou, a, b = best[0]
    si, sj = seg[a], seg[b]
    print(f'\n建议裁切区间: [{si}, {sj}]（{sj - si + 1} 帧闭环）')
    if si > 0:
        print(f'  ⚠️ 丢弃前 {si} 帧 intro（含 {len([e for e in events if e[0] <= si])} 处位置突变）')

    # ── 4) 接缝对比图 ──
    f0, f1 = frames[si], frames[sj]
    H = max(f0.shape[0], f1.shape[0])
    W = max(f0.shape[1], f1.shape[1])
    canvas = np.full((H, W * 2 + 20, 4), (255, 255, 255, 255), np.uint8)
    canvas[:f0.shape[0], :f0.shape[1]] = f0
    canvas[:f1.shape[0], f0.shape[1] + 20:] = f1
    out = f'{state}_seam_check.jpg'
    Image.fromarray(canvas[:, :, :3]).save(out)
    print(f'saved {out} — 目视确认：①两帧道具位置/外观一致 ②稳定段内无手/异物残影')
    print('目视通过后：extract_frames.py 里该状态按 [si, sj] 裁切，并把帧数写入引擎 ANIMS')

if __name__ == '__main__':
    main()
