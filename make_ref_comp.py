# -*- coding: utf-8 -*-
"""构图校正参考图生成器 v2（阶段1→2 交接工具）。

v1 两宗实测根因（萨摩耶轮用户肉眼报缺陷后取证）：
  ① 画布用原图背景色填充 → 用户截图的米色矩形被 ti2vid 复制到视频开头帧
     （用户报"开始是那张截图还能看到截图背景色"）；
  ② 主体仅 40% 高/19% 宽 → 身份锚太弱，模型逐视频自由发挥 = 画风/形象不统一
     （用户报"各个视频明显不是一条狗、大小不一致"）。

v2 算法：
  ① rembg isnet-general-use 净抠主体（白毛安全，色距判据会留背景过渡像素）；
  ② alpha 二值化 → 主体 bbox 裁出；
  ③ 等比缩放到主体高 55%（锚够强 + 上下留白≥20% 防贴边裁切）；
  ④ 贴到**纯白 (255,255,255)** 画布中央（永远不用原图背景色）；
  ⑤ 污迹清洁：rembg mask 常把主体旁淡黄影子误并入主体，ti2vid 会原样复制成视频里的
     黄斑（用户报"左前腿旁黄色痕迹"）。开运算(3)杀细毛边留厚污块，白化之；
  ⑥ 数值自检：bbox 外零非白、上下边距≥15%、左右边距≥20%。

用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe make_ref_comp.py <输入图> [主体高占比0.55]
产物: 同目录 identity_ref_comp.png
"""
import sys, os
import numpy as np
from PIL import Image

def clean_stains(arr, min_blob=20):
    """白化独立于主体的淡黄污迹块（ti2vid 会把参考图污迹原样复制成视频黄斑）。

    只清理"非主体连通分量"（size≥min_blob 且平均色淡黄）——绝不触碰主体连通分量，
    结构性保证不削主体。与主体连通的并入型污迹需手工区域清洁+肉眼复核
    （色距/纹理判据都分不开污迹核心与阴影毛，自动削必伤毛）。
    """
    from scipy import ndimage
    R, G, B = arr[..., 0], arr[..., 1], arr[..., 2]
    nonwhite = (R - B >= 5) | (R < 248)
    lab, n = ndimage.label(nonwhite, structure=np.ones((3, 3)))
    if n == 0:
        return arr
    sizes = ndimage.sum(nonwhite, lab, range(1, n + 1))
    main = int(np.argmax(sizes)) + 1
    cleaned = 0
    for i in range(n):
        cid = i + 1
        if cid == main or sizes[i] < min_blob:
            continue
        m = lab == cid
        ys, xs = np.nonzero(m)
        mean = arr[ys, xs].mean(0)
        if mean[0] - mean[2] >= 5:
            arr = arr.copy()
            arr[m] = [255, 255, 255]
            cleaned += int(m.sum())
    if cleaned:
        print(f'  stains cleaned: {cleaned} px', flush=True)
    return arr


def make_comp(src_path, subject_h_frac=0.55, out_name='identity_ref_comp.png'):
    src = Image.open(src_path).convert('RGB')
    W, H = src.size
    # ① rembg 净抠
    from rembg import remove, new_session
    rgba = remove(src, session=new_session('isnet-general-use'))
    a = np.asarray(rgba)
    alpha = a[:, :, 3]
    mask = alpha > 128
    ys, xs = np.where(mask)
    if len(xs) < 1000:
        raise SystemExit(f'[FAIL] rembg 主体像素仅 {len(xs)}，输入图可能无清晰主体')
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    crop = rgba.crop((x0, y0, x1 + 1, y1 + 1))
    print(f'  src {W}x{H} subject bbox {x1-x0+1}x{y1-y0+1} '
          f'(占画面高 {100.0*(y1-y0+1)/H:.0f}%)', flush=True)
    # ③ 缩放到目标主体高
    target_h = int(round(H * subject_h_frac))
    scale = target_h / crop.height
    tw, th = max(1, int(round(crop.width * scale))), target_h
    crop = crop.resize((tw, th), Image.LANCZOS)
    # ④ 纯白画布居中贴
    canvas = Image.new('RGB', (W, H), (255, 255, 255))
    canvas.paste(crop, ((W - tw) // 2, (H - th) // 2), crop)
    # ⑤ 污迹清洁：开运算(3)杀细毛边留厚污块 → 白化，防 ti2vid 复制黄斑
    arr = np.asarray(canvas).astype(int)
    arr = clean_stains(arr)
    canvas = Image.fromarray(arr.astype(np.uint8))
    # ⑥ 数值自检
    arr = np.asarray(canvas).astype(int)
    nonwhite = (np.abs(arr - 255).sum(2) > 30)
    nys, nxs = np.where(nonwhite)
    top_m = nys.min() / H
    bot_m = (H - 1 - nys.max()) / H
    left_m = nxs.min() / W
    right_m = (W - 1 - nxs.max()) / W
    print(f'  margins: top={top_m:.0%} bottom={bot_m:.0%} left={left_m:.0%} right={right_m:.0%}',
          flush=True)
    if top_m < 0.15 or bot_m < 0.15 or left_m < 0.20 or right_m < 0.20:
        raise SystemExit('[FAIL] 边距不足（主体过大），降低主体高占比重试')
    out = os.path.join(os.path.dirname(os.path.abspath(src_path)) or '.', out_name)
    canvas.save(out)
    print(f'  saved {out} subject={subject_h_frac:.0%} h', flush=True)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__); raise SystemExit(1)
    make_comp(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 0.55)
