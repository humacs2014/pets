# -*- coding: utf-8 -*-
"""type 首帧 v2：直接以用户参考图为构图基础（真键盘），柴犬→萨摩耶化。
- 橙色毛区(y<385)提亮白化（保阴影结构）
- 头部用身份图萨摩耶真头替换（feather 混合）
- 青色噪点 inpaint
- 贴到 1088x832 纯白画布
"""
import numpy as np, cv2
from PIL import Image

REF = r'C:/Users/humac/Desktop/video (1).webp'
SAM = 'identity_ref_user.png'
OUT = 'type_firstframe_v2.png'
VW, VH = 1088, 832
S = 1.40  # ref 放大倍率

ref = np.array(Image.open(REF).convert('RGBA'))
h0, w0 = ref.shape[:2]
refb = cv2.resize(ref, (int(w0*S), int(h0*S)), interpolation=cv2.INTER_LANCZOS4)
rgb = refb[:,:,:3].astype(np.int16); al = refb[:,:,3]
R,G,B = rgb[:,:,0],rgb[:,:,1],rgb[:,:,2]

# 1) 青色噪点 inpaint（键盘缝里的参考图杂质）
cyan = ((B>140)&(G>110)&(R<130)&(al>10)).astype(np.uint8)
cyan = cv2.dilate(cyan, np.ones((5,5),np.uint8))
bgr = cv2.cvtColor(refb[:,:,:3], cv2.COLOR_RGB2BGR)
bgr = cv2.inpaint(bgr, cyan, 5, cv2.INPAINT_TELEA)
refb[:,:,:3] = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
rgb = refb[:,:,:3].astype(np.int16)
R,G,B = rgb[:,:,0],rgb[:,:,1],rgb[:,:,2]

# 2) 橙色毛白化（仅键盘上方 y<385*S，避开 keycap）——加强版：低饱和橙也覆盖
fur = (R-B>32)&(G-B>2)&(al>10)
fur[ int(385*S): , :] = False
furm = (fur.astype(np.float32))
furm = cv2.GaussianBlur(furm, (15,15), 0)
furm = np.clip(furm*1.6,0,1)[:,:,None]
# 白化：向白提亮，只保留少量阴影结构
white = 255 - (255 - rgb)*0.20
out = rgb*(1-furm) + white*furm
refb[:,:,:3] = np.clip(out,0,255).astype(np.uint8)

# 3) 萨摩耶头替换
sam = np.array(Image.open(SAM).convert('RGB')).astype(np.int16)
sbg = np.abs(sam - np.array([253,253,242])).sum(axis=2) < 45
sdog = (~sbg).astype(np.uint8)
ys,xs = np.where(sdog[:262,:])
hx0,hx1,hy0,hy1 = xs.min(),xs.max(),ys.min(),310  # 含脖子段便于融合
head = sam[hy0:hy1, hx0:hx1+1]
hmask = sdog[hy0:hy1, hx0:hx1+1].astype(np.float32)
# 目标宽 = 柴犬头宽*scale (柴犬头在 refb 中宽约 322*S)，1.22x 确保全覆盖
tw = int(322*S*1.22); th = int(head.shape[0]*tw/head.shape[1])
head_r = cv2.resize(head.astype(np.uint8), (tw,th), interpolation=cv2.INTER_LANCZOS4)
hm_r = cv2.resize(hmask, (tw,th))
hm_r = cv2.GaussianBlur(hm_r, (21,21), 0)
# 底部 feather 加长（脖子渐隐）
fade = np.ones((th,1)); fl = int(th*0.25)
fade[-fl:,0] = np.linspace(1,0,fl)
hm_r = hm_r * fade
hmr3 = np.clip(hm_r,0,1)[:,:,None]

# 4) 画布合成：ref 贴底居中
canvas = np.full((VH,VW,3),255,np.uint8)
rh,rw = refb.shape[:2]
ox = (VW-rw)//2; oy = VH-20-rh
al3 = (al/255.0)[:,:,None]
piece = refb[:,:,:3].astype(np.int16)
ys0 = max(oy,0); ys1 = min(oy+rh,VH)
xs0 = max(ox,0); xs1 = min(ox+rw,VW)
cy, cx_ = ys0-oy, xs0-ox
hh2 = ys1-ys0; ww2 = xs1-xs0
canvas[ys0:ys1, xs0:xs1] = np.clip(
    canvas[ys0:ys1, xs0:xs1]*(1-al3[cy:cy+hh2, cx_:cx_+ww2])
    + piece[cy:cy+hh2, cx_:cx_+ww2]*al3[cy:cy+hh2, cx_:cx_+ww2],
    0, 255).astype(np.uint8)
print('canvas paste done')

# 5) 头贴上：顶边与原柴犬头顶对齐，水平居中对齐原头中心
cx = int(226*S)+ox; top = oy+int(2*S)
hyA, hxA = top, cx-tw//2
yb,xb = max(hyA,0),max(hxA,0)
ye,xe = min(hyA+th,VH), min(hxA+tw,VW)
sub = canvas[yb:ye,xb:xe].astype(np.int16)
hh = head_r[yb-hyA:ye-hyA, xb-hxA:xe-hxA].astype(np.int16)
mm = hmr3[yb-hyA:ye-hyA, xb-hxA:xe-hxA]
canvas[yb:ye,xb:xe] = np.clip(sub*(1-mm)+hh*mm,0,255).astype(np.uint8)

Image.fromarray(canvas).save(OUT)
# 缩略验证图
Image.fromarray(canvas).resize((544,416)).save('_probe/v2_firstframe_thumb.png')
print('saved', OUT)
