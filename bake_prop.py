# -*- coding: utf-8 -*-
"""阶段4 道具烤帧模板（v56 三层遮挡法，喂食动作"嘴在碗里"的唯一正确实现）。
用法: python bake_prop.py（需同目录放 final_fix.py，或改下方 import）
三层合成: ①道具全图(底) → ②狗帧(中，嘴盖食物/后缘=嘴进道具) → ③道具前壁(顶，盖嘴下部=嘴在道具内)
v56 教训: 整道具画狗上层=嘴被全盖("嘴在碗后"不像吃)；整道具画狗下层=嘴浮碗前。
输入: CLEAN_DIR = 阶段3抽出的无道具狗帧(cleaned/c_*.png) + assets 内道具 sprite
输出: assets/{prefix}_NN.png（已过 fix_frame 清洁）
"""
import glob, os
import numpy as np
from PIL import Image
from final_fix import fix_frame   # skill scripts/final_fix.py，复制到同目录

ROOT = os.path.dirname(os.path.abspath(__file__))

# ══════════ CONFIG（换宠物/换道具改这里） ══════════
CLEAN_DIR = os.path.join(ROOT, 'clean')   # 阶段3的无道具狗帧目录(c_*.png)
PROP_PATH = os.path.join(ROOT, 'assets', 'food_bowl.png')  # 道具sprite
PREFIX = 'eat'          # 输出帧前缀
NFR = 34                # 目标帧数（=引擎ANIMS该状态帧数）
PROP_SCALE = 1.75       # 道具放大倍数（原sprite通常偏小，husky碗实测1.75）
SPLIT_ROW = 8           # 道具sprite前壁分割行（原图y>=SPLIT_ROW为前壁；
                        # 用像素行分析定：纯色行=前壁，食物像素集中行=食物层）
BOWL_CX, BOWL_BOT = 350.0, 504.0  # 道具位置：cx=低头鼻尖x(右朝向=主体右端)，底=地平线
FACING = 'right'      # 狗朝向: 'left'(husky式鼻尖=最左) / 'right'(拉布拉多eat=最右)
DOG_H_ANCHOR = 230.0    # 狗帧高度锚定(90th percentile)
DOG_SCALE_CAP = 2.2     # 缩放上限
MIN_DOG_H = 100         # 低于此高度的帧视为无效(未入场)
# ══════════ CONFIG END ══════════

cleaned = sorted(glob.glob(os.path.join(CLEAN_DIR, 'c_*.png')))
assert cleaned, f'no clean frames in {CLEAN_DIR}'
ms = []
for p in cleaned:
    a = np.array(Image.open(p).convert('RGBA'))
    ys, xs = np.where(a[..., 3] > 40)
    ms.append((xs.min(), ys.min(), xs.max(), ys.max()) if len(xs) else None)
valid = [i for i, m in enumerate(ms) if m and (m[3] - m[1]) >= MIN_DOG_H]
assert len(valid) >= NFR, f'only {len(valid)} valid frames < {NFR}'
i0, i1 = valid[0], valid[-1]
idxs = [int(round(i0 + k * (i1 - i0) / (NFR - 1))) for k in range(NFR)]
hs_all = [ms[i][3] - ms[i][1] + 1 for i in valid]
SCALE = min(DOG_H_ANCHOR / float(np.percentile(hs_all, 90)), DOG_SCALE_CAP)

dogs = []
for i in idxs:
    m = ms[i]
    im = Image.open(cleaned[i]).convert('RGBA').crop((m[0], m[1], m[2] + 1, m[3] + 1))
    tw, th = max(1, int(im.width * SCALE)), max(1, int(im.height * SCALE))
    if tw > 500:
        tw, th = 500, max(1, int(th * 500 / tw))
    im = im.resize((tw, th), Image.LANCZOS)
    canvas = Image.new('RGBA', (512, 512), (0, 0, 0, 0))
    canvas.paste(im, ((512 - tw) // 2, int(BOWL_BOT) + 26 - th), im.split()[3])
    dogs.append(canvas)

# 道具：全图(底层) + 前壁层(顶层，原图y>=SPLIT_ROW放大后保留、上部alpha清零)
prop0 = Image.open(PROP_PATH).convert('RGBA')
bw = prop0.resize((int(prop0.width * PROP_SCALE), int(prop0.height * PROP_SCALE)), Image.LANCZOS)
SPLIT = int(round(SPLIT_ROW * PROP_SCALE))
front = bw.copy()
fa = np.array(front)
fa[:SPLIT, :, 3] = 0  # 前壁层：分割线以上透明
front = Image.fromarray(fa, 'RGBA')
bx = int(round(BOWL_CX - bw.width / 2))
by = int(round(BOWL_BOT - bw.height))
print('prop %dx%d @(%d,%d) front split y=%d' % (bw.width, bw.height, bx, by, SPLIT))

noses = []
os.makedirs(os.path.join(ROOT, 'assets'), exist_ok=True)
for k, dog in enumerate(dogs):
    a = np.array(dog)
    m = a[:, :, 3] > 16
    ys, xs = np.where(m)
    j = np.argmin(xs) if FACING == 'left' else np.argmax(xs)  # 鼻尖=朝向侧极端点
    noses.append((int(xs[j]), int(ys[j])))
    comp = Image.new('RGBA', (512, 512), (0, 0, 0, 0))
    comp.paste(bw, (bx, by), bw)        # 底：道具全图
    comp.paste(dog, (0, 0), dog)        # 中：狗（嘴盖食物=进道具）
    comp.paste(front, (bx, by), front)  # 顶：前壁（盖嘴下部=嘴在道具内）
    out = fix_frame(np.array(comp).astype(np.int32))
    Image.fromarray(out.astype('uint8'), 'RGBA').save(
        os.path.join(ROOT, 'assets', f'{PREFIX}_{k:02d}.png'))
print('WROTE %d frames (3-layer) → assets/%s_*' % (NFR, PREFIX))

# 审计：低头段嘴应深入道具区（被前壁遮挡），抬头段嘴在道具缘
print('prop x %d-%d, top %d, front_top %d' % (bx, bx + bw.width, by, by + SPLIT))
deep = [(k, n) for k, n in enumerate(noses)
        if bx <= n[0] <= bx + bw.width and n[1] >= by + SPLIT - 6]
mid = [(k, n) for k, n in enumerate(noses)
       if bx <= n[0] <= bx + bw.width and by - 8 <= n[1] < by + SPLIT - 6]
print('mouth deep-in-prop (behind front wall): %d' % len(deep), deep[:8])
print('mouth at rim/food level: %d' % len(mid), mid[:8])
assert len(deep) >= 3, '嘴未深入道具——检查 BOWL_CX/SPLIT_ROW 标定'
print('BAKE_PROP_DONE', flush=True)
