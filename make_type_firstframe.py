# -*- coding: utf-8 -*-
"""type 首帧合成 v2（干净基底版）：
基底=sit.mp4 干净坐姿帧（纯白底、无假键盘残留），把截图样式键盘贴到狗前腿前。
参考键盘裁自 C:\\Users\\humac\\Desktop\\video (1).webp，inpaint 去柴犬爪+青色噪点。
v117d 范式：键盘盖住狗前爪，爪由视频模型从键盘顶沿上方原生生成敲击动画。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe make_type_firstframe.py [sit帧号,默认80]
"""
import os, sys
import numpy as np
import cv2
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
REF = r'C:\Users\humac\Desktop\video (1).webp'

def load_ref_keyboard():
    """参考图裁键盘（alpha）+ inpaint 去柴犬橙爪 + 去青色残留噪点。"""
    ref = np.array(Image.open(REF).convert('RGBA'))
    sub = ref[406:, :, 3] > 128
    colcnt = sub.sum(axis=0)
    vx = np.where(colcnt > 15)[0]
    x0, x1 = vx.min(), vx.max()
    rowcnt = sub[:, x0:x1+1].sum(axis=1)
    vy = np.where(rowcnt > 15)[0]
    y_t, y_b = 406 + vy.min(), 406 + vy.max()
    crop = ref[y_t:y_b+1, x0:x1+1].copy()
    r, g, b = crop[..., 0].astype(int), crop[..., 1].astype(int), crop[..., 2].astype(int)
    fur = ((r - b > 45) & (r > 120) & (g < r - 10)).astype(np.uint8)      # 柴犬橙爪（仅橙色部分；白奶油爪保留=萨摩耶白爪构图）
    fur = cv2.dilate(fur, np.ones((5, 5), np.uint8))
    cyan = ((b > 130) & (b - r > 25)).astype(np.uint8)                    # 青色残留噪点（含浅青）
    cyan = cv2.dilate(cyan, np.ones(5, np.uint8))
    mask = fur | cyan
    rgb = crop[..., :3][..., ::-1].copy()
    clean = cv2.inpaint(rgb, mask, 7, cv2.INPAINT_TELEA)
    kb = np.dstack([clean[..., ::-1], crop[..., 3]]).astype(np.uint8)
    return kb

def main():
    fi = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    cap = cv2.VideoCapture(os.path.join(ROOT, 'videos', 'sit.mp4'))
    cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ok, raw = cap.read()
    assert ok, 'frame read fail'
    H, W = raw.shape[:2]
    rgb = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB).astype(int)
    gray = rgb.mean(axis=2)
    # sit.mp4 背景=浅灰渐变237-244 → 阈值235；白毛高光虽>235但主体轮廓够用，close填洞
    fg = gray < 235
    fg = cv2.morphologyEx(fg.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8)) > 0
    ys, xs = np.where(fg)
    dy0, dy1 = ys.min(), ys.max()
    # 狗水平中心用上半身（排除地面阴影污染bbox左缘）
    up = fg[dy0:dy0 + int((dy1 - dy0) * 0.6), :]
    ysu, xsu = np.where(up)
    dx0, dx1 = xsu.min(), xsu.max()
    dog_w, dog_h = dx1 - dx0 + 1, dy1 - dy0 + 1
    print('dog bbox', dx0, dy0, dx1, dy1, 'dog_w', dog_w, 'dog_h', dog_h)

    kb = load_ref_keyboard()
    aspect = kb.shape[1] / kb.shape[0]
    # 键盘宽≈狗宽1.5（截图比例），上限90%屏宽；高按参考比例
    kb_w = int(min(dog_w * 1.5, W * 0.9))
    kb_h = int(round(kb_w / aspect))
    kbr = cv2.resize(kb[..., :3], (kb_w, kb_h), interpolation=cv2.INTER_LANCZOS4)
    ka = cv2.resize(kb[..., 3], (kb_w, kb_h), interpolation=cv2.INTER_LANCZOS4) > 128
    rx0 = max(0, min((dx0 + dx1) // 2 - kb_w // 2, W - kb_w))
    ry1 = min(H - 1, dy1 + 25)                 # 底边略低于狗底（近大远小透视）
    ry0 = ry1 - kb_h
    out = raw.copy()
    kbr_bgr = kbr[..., ::-1]
    region = out[ry0:ry1, rx0:rx0 + kb_w]
    out[ry0:ry1, rx0:rx0 + kb_w] = np.where(ka[..., None], kbr_bgr, region)
    cv2.imwrite(os.path.join(ROOT, 'type_firstframe.png'), out)
    print('saved type_firstframe.png', out.shape, 'kb at', rx0, ry0, kb_w, kb_h)

if __name__ == '__main__':
    main()
