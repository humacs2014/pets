# -*- coding: utf-8 -*-
"""阶段3 抽帧管线模板（labrador 最终验证版）。换宠物改 CONFIG 段即可。
流程: ffmpeg原生24fps抽帧 → isnet抠图(带PAD边距) → 质量过滤+姿态选窗
      → union-bbox+宽度钳制 → 512归一化(姿态档高度锚定) → sleep逐帧姿态缩放
      → 循环结构(intro/loop/ping-pong/gait自相关) → 重采样到ANIMS帧数 → harden alpha
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe extract_frames.py [状态名...]
依赖: rembg(onnxruntime) scipy numpy Pillow ffmpeg(在PATH)
"""
import os, sys, glob, subprocess
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))

# ══════════ CONFIG（换宠物改这里） ══════════
VIDS_DIR = 'videos'            # 阶段2下载的 mp4（{state}.mp4）
OUT_DIR = 'frames'             # 抽帧输出目录
BG = (241, 239, 238)           # rembg 画布底色（与白底视频匹配）
PAD = 200                      # 抠图前加边距防边缘伪影，抠后裁回
CANVAS = 1024                  # v2 高分辨率: 512→1024（源1088x832狗≈650-700px，512画布狗仅274px=浪费过半源分辨率；1024狗548px≈1:1回收）
GROUND = 956                   # walk/run 脚底线（canvas 1024 内，=478/512*1024）
# sleep 逐帧姿态缩放目标高度（坐档/躺档）：坐档≈sit认可值-16(侧身紧凑)，躺档≈roll认可躺高
SLEEP_SIT_H, SLEEP_LIE_H = 600.0, 408.0   # v2: ×2 同步1024画布

# ping-pong 往复类（正播+倒播）
PINGPONG = {'idle', 'eat', 'bark', 'sit', 'roll', 'dance', 'beg', 'bath'}
# 一次性/过渡类
ONESHOT = {'sleep', 'stretch', 'happy', 'surprised', 'play_dead', 'pet'}
# 高度锚定 target_h 按姿态档（跨档=忽大忽小）。新宠物标定法：先跑 idle 测站立 h≈274，
# 坐姿视频取稳坐段测 h≈316，伸展段≈291，躺卧段≈204-217。
# v2: 1024画布，精确=旧512资产实测中位h×2（保持屏幕占比不变，防状态切换忽大忽小）
TARGET_H = {
    'idle': 546, 'bark': 546, 'happy': 544, 'dance': 544,
    'beg': 540, 'bath': 542, 'sit': 630,
    'stretch': 580,
    'walk': 508, 'run': 542,          # 步态侧身档（旧254/271×2，勿统一548=切换跳变8%）
    'lick': 542, 'surprised': 544,
    'eat': 474,
    'pet': 546,   # 摸摸头: 站姿档(视频为四腿站立3/4视), 与idle/bark同档防忽大忽小
    'roll': 358, 'play_dead': 344,    # 躺卧档（旧179/172×2）
}
# 重采样到引擎 ANIMS 声明帧数（引擎按 count 加载，帧数必须 1:1）
RT_FRAMES = {
    'idle': 101, 'eat': 34, 'bark': 57, 'sit': 63, 'roll': 121,
    'dance': 57, 'beg': 56, 'bath': 57, 'stretch': 117,
    'surprised': 45, 'play_dead': 68, 'sleep': 51, 'lick': 54,
    'happy': 121, 'run': 15,  # v60: walk移出RT_FRAMES——双周期=2T+1原生帧恒等, 帧数随T自适应, 禁止重采样(会产生重复帧)
}
ALL_STATES = ['idle', 'sit', 'eat', 'bark', 'happy', 'roll', 'dance',
              'beg', 'bath', 'lick', 'surprised', 'play_dead', 'sleep', 'stretch',
              'walk', 'run', 'pet']
# 姿态选窗（idle/bark 选纯侧身段跳3/4正面intro；sit 选稳坐段跳站姿intro；eat 选侧身段）
PROFILE_STATES = {'idle': 'high', 'bark': 'high', 'sit': 'low', 'eat': 'high'}
# ══════════ CONFIG END ══════════

os.makedirs(OUT_DIR, exist_ok=True)
from rembg import new_session, remove

def extract(name):
    """ffmpeg 原生 24fps 全帧抽帧（降采样+插值补帧=清晰度流畅度双杀）。"""
    mp4 = os.path.join(VIDS_DIR, name + '.mp4')
    if not os.path.exists(mp4):
        mp4s = sorted(glob.glob(os.path.join(VIDS_DIR, name + '_c*.mp4')))
        if not mp4s:
            return None
        mp4 = mp4s[0]
    fd = os.path.join(ROOT, '_raw_' + name)
    # 新鲜度铁律: 视频比缓存新 → 旧视频缓存必须作废（重生成视频被缓存短路=白生成）
    if os.path.isdir(fd) and os.path.getmtime(mp4) > os.path.getmtime(fd):
        import shutil
        shutil.rmtree(fd)
        print(f'  [cache invalid] _raw_{name} older than video, re-extracting', flush=True)
    os.makedirs(fd, exist_ok=True)
    if len(glob.glob(os.path.join(fd, 'f_*.png'))) < 10:
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', mp4,
                        '-vf', 'fps=24',
                        os.path.join(fd, 'f_%04d.png')], check=True)
    return sorted(glob.glob(os.path.join(fd, 'f_*.png')))

def cutout_frames(fps, state):
    """isnet-general-use 抠图（白底/白毛必须用此模型；u2net 液化白色头部）。"""
    mats_dir = os.path.join(ROOT, '_mats_' + state)
    mp4 = os.path.join(VIDS_DIR, state + '.mp4')
    # 新鲜度铁律: 视频比抠图缓存新 → 旧mask作废
    if os.path.isdir(mats_dir) and os.path.exists(mp4) and \
            os.path.getmtime(mp4) > os.path.getmtime(mats_dir):
        import shutil
        shutil.rmtree(mats_dir)
        print(f'  [cache invalid] _mats_{state} older than video, re-cutting', flush=True)
    os.makedirs(mats_dir, exist_ok=True)
    existing = sorted(glob.glob(os.path.join(mats_dir, 'm_*.png')))
    if len(existing) >= len(fps):
        return existing
    sess = new_session('isnet-general-use')
    mats = []
    for i, fp in enumerate(fps):
        outp = os.path.join(mats_dir, f'm_{i:04d}.png')
        if os.path.exists(outp):
            mats.append(outp); continue
        im = Image.open(fp).convert('RGB')
        W, H = im.size
        pad = Image.new('RGB', (W + 2 * PAD, H + 2 * PAD), BG)
        pad.paste(im, (PAD, PAD))
        cut = remove(pad, session=sess)
        cut = cut.crop((PAD, PAD, PAD + W, PAD + H))
        cut.save(outp)
        mats.append(outp)
        if i % 20 == 0:
            print(f'    mat {i}/{len(fps)}', flush=True)
    return mats

def alpha_metrics(mat, bottom_ok=True, relax=False):
    from scipy.ndimage import label
    a = np.array(Image.open(mat).convert('RGBA'))[:, :, 3]
    H, W = a.shape
    fg = a > 128
    total = fg.sum()
    if total == 0:
        return {'main_frac': 0, 'edge': True, 'area': 0}
    lab, n = label(fg)
    sizes = np.bincount(lab.ravel()); sizes[0] = 0
    main_frac = sizes.max() / total
    ys, xs = np.where(fg)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    # 脚触底正常（walk/run 脚底贴地）；只拒顶/左/右边缘接触（真裁切风险）。
    # bottom_ok=False（beg等直立抬爪态）: 底触=脚出框裁切，同拒。
    # relax=True（pet摸摸头）: 人手手臂从左上伸出屏幕=有意设计非裁切，豁免左/顶。
    edge = x1 >= W - 4 or (not relax and (x0 <= 3 or y0 <= 3)) or \
        (not bottom_ok and y1 >= H - 4)
    return {'main_frac': main_frac, 'edge': edge, 'area': int(total)}

def motion_scores(mats):
    """逐帧alpha差均值=运动量。站立intro≈0，步态相位大。"""
    prev, out = None, []
    for m in mats:
        a = np.array(Image.open(m).convert('RGBA'))[:, :, 3].astype(np.float32)
        if prev is not None:
            out.append(float(np.mean(np.abs(a - prev))))
        prev = a
    out.append(out[-1] if out else 0.0)
    return np.array(out)

def gait_window(mats, min_len=8):
    """walk/run专用: 放宽面积容差(步态伸展/收拢面积差大), 在干净段里选运动量最大的窗口。
    （最长干净段会选中站立intro而非奔跑段——必须按运动量选窗。）"""
    ms = [alpha_metrics(m) for m in mats]
    areas = np.array([m['area'] for m in ms])
    med = np.median(areas[areas > 0]) if (areas > 0).any() else 1
    ok = [m['main_frac'] >= 0.99 and not m['edge']
          and abs(m['area'] - med) / max(med, 1) <= 0.45 and m['area'] > 800
          for m in ms]
    runs, s = [], 0
    for i in range(len(ok) + 1):
        if i == len(ok) or not ok[i]:
            if i - s >= min_len:
                runs.append((s, i))
            s = i + 1
    if not runs:
        return None
    mot = motion_scores(mats)
    return max(runs, key=lambda r: float(np.mean(mot[r[0]:r[1]])) * (r[1] - r[0]) ** 0.3)

def _front_standing(a):
    """正面站/坐过渡帧（奇怪后腿主体）判据: 站姿档且下部行带细腿分离(密度<0.60)。
    实测: 正面站0.36-0.49、正面坐过渡0.51-0.55、侧身坐/躺>=0.64 → 0.60完美分离。
    span判据对卧姿误报(0.81-0.91重叠)，不可用。"""
    ys, xs = np.where(a > 30)
    if len(xs) == 0:
        return False
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    w, h = x1 - x0 + 1, y1 - y0 + 1
    if h <= w * 0.72:
        return False                 # 侧躺/蜷缩不约束
    band = a[y0 + int(h * 0.78): y0 + int(h * 0.94), x0:x1 + 1]
    return (band > 127).mean() < 0.60

def _standing_leg_ok(a):
    """站姿帧腿质量: 下部行带连通块跨度过宽(劈叉span>0.9)=False。
    只用span判据——blob数判据会误杀低头吃食侧视帧(低头+前后腿分离天然5blob,
    span仅0.80-0.85); 真分叉狗span 0.93-0.99。"""
    ys, xs = np.where(a > 40)
    if len(xs) == 0:
        return True
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    h, w = y1 - y0 + 1, x1 - x0 + 1
    if h <= w * 0.72:
        return True                      # 非站姿(坐/躺/低头)不约束
    band = a[y0 + int(h * 0.78): y0 + int(h * 0.94)]
    for r in band:
        line = r[x0:x1 + 1] > 127
        if line.sum() < 4:
            continue
        d = np.diff(line.astype(int))
        starts = list(np.where(d == 1)[0] + 1)
        ends = list(np.where(d == -1)[0] + 1)
        if line[0]:
            starts = [0] + starts
        if line[-1]:
            ends = ends + [len(line)]
        blobs = [(s, e) for s, e in zip(starts, ends) if e - s >= 2]
        if blobs and (blobs[-1][1] - blobs[0][0]) / w > 0.9:
            return False
    return True

def posture_window(mats, min_len=16, mode='high'):
    """按姿态宽高比选窗: mode='high'站立态选纯侧身段(跳3/4正面intro);
    mode='low'坐姿选稳坐段(跳站姿intro)。high模式叠加腿质量判据剔偶发正面张腿帧。"""
    ok, ars = [], []
    for m in mats:
        a = np.array(Image.open(m).convert('RGBA'))[:, :, 3]
        ys, xs = np.where(a > 30)
        if len(xs) == 0:
            ok.append(False); ars.append(0.0); continue
        ok.append(mode == 'low' or _standing_leg_ok(a))
        ars.append((xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1))
    ars = np.array(ars)
    sm = np.array([np.median(ars[max(0, i - 2):i + 3]) for i in range(len(ars))])
    oka = np.array(ok)
    pct = np.percentile(sm[oka], 45) if mode == 'high' else np.percentile(sm[oka], 55)
    good = oka & (sm >= pct if mode == 'high' else sm <= pct)
    best_s, best_l, s, l = 0, 0, 0, 0
    for i in range(len(good) + 1):
        if i == len(good) or not good[i]:
            if l > best_l:
                best_l, best_s = l, s
            s, l = i + 1, 0
        else:
            l += 1
    if best_l < min_len:
        return None
    return best_s, best_s + best_l

def tub_ok_flags(mats):
    """逐帧蓝色浴盆存在判定：盆像素(B-R>30 & alpha>128)≥50k。
    无盆站立intro/甩头泡沫盖盆瞬间=False，进循环=盆闪烁跳变。"""
    flags = []
    for mp in mats:
        im = np.array(Image.open(mp).convert('RGBA'))
        r, b, a = im[:, :, 0].astype(int), im[:, :, 2].astype(int), im[:, :, 3]
        blue = int(((b - r > 30) & (a > 128)).sum())
        flags.append(blue >= 50000)
    return flags

def tub_window(mats, min_len=24):
    """bath 浴盆存在选窗：返回最长连续有盆段 (s,e)，不足 min_len 返回 None。"""
    ok = tub_ok_flags(mats)
    best_s = best_l = 0
    s = 0
    for i, v in enumerate(ok + [False]):
        if not v:
            l = i - s
            if l > best_l:
                best_s, best_l = s, l
            s = i + 1
    if best_l < min_len:
        return None
    return best_s, best_s + best_l

def gray_ok_flags(mats, max_px=10000):
    """逐帧灰色半透明脏斑排除：低彩度(mx-mn<30)+半透明(40<=a<=230)+中灰(80<=min,max<=220)
    像素>max_px 的帧=matting鬼影残留(泡沫边灰雾)，进循环=盆体灰带闪烁。正常帧≤9.5k，缺陷帧≥12k。"""
    flags = []
    for mp in mats:
        im = np.array(Image.open(mp).convert('RGBA')).astype(int)
        r, g, b, a = im[:, :, 0], im[:, :, 1], im[:, :, 2], im[:, :, 3]
        mx = np.maximum(np.maximum(r, g), b)
        mn = np.minimum(np.minimum(r, g), b)
        gray = int(((a >= 40) & (a <= 230) & ((mx - mn) < 30)
                    & (mn >= 80) & (mx <= 220)).sum())
        flags.append(gray <= max_px)
    return flags

def clean_window(mats, bottom_ok=True, relax=False, extra_ok=None):
    """逐帧打分（主CC占比≥0.999、无顶左右边缘、面积偏差≤25%、面积>1000），取最长连续干净段。
    extra_ok: 逐帧附加条件(bath的浴盆存在判定)，与干净条件AND。"""
    ms = [alpha_metrics(m, bottom_ok=bottom_ok, relax=relax) for m in mats]
    areas = np.array([m['area'] for m in ms])
    med = np.median(areas[areas > 0]) if (areas > 0).any() else 1
    ok = [m['main_frac'] >= 0.999 and not m['edge']
          and abs(m['area'] - med) / max(med, 1) <= 0.25 and m['area'] > 1000
          for m in ms]
    if extra_ok is not None:
        ok = [c and t for c, t in zip(ok, extra_ok)]
    best_s, best_l, s, l = 0, 0, 0, 0
    for i, o in enumerate(ok):
        if o:
            l += 1
            if l > best_l:
                best_l, best_s = l, s
        else:
            s, l = i + 1, 0
    if best_l < 6:
        ok = [m['main_frac'] >= 0.99 and not m['edge'] and m['area'] > 800 for m in ms]
        best_s, best_l, s, l = 0, 0, 0, 0
        for i, o in enumerate(ok):
            if o:
                l += 1
                if l > best_l:
                    best_l, best_s = l, s
            else:
                s, l = i + 1, 0
    return best_s, best_s + best_l, sum(ok), len(ok)

def treadmill_mats(mat_paths, state, smooth=2):
    """walk/run 线性去趋势对齐（mats阶段, normalize之前）:
    walk源视频狗真实横穿画面(-667px漂移)→normalize的union-bbox横跨整个行走距离
    →宽度钳制压死scale→walk h=169px仅idle的31%。必须逐帧位移收缩union-bbox。

    ⚠️v59根因修复（滑行）：v58实现把每帧质心对齐到5帧平滑中位数——平滑信号保留
    ~93%的步态周期振荡，对齐时把步态振荡一并删除(run部署帧体内摆动仅9px@1024，
    认可版labrador=64px@512 gallop前冲)→原地踏步+引擎匀速平移=太空滑步。
    现改为线性去趋势：一次拟合质心趋势→每帧只对齐趋势分量(去除净漂移)，
    周期性步态振荡(残差分量)完整保留在精灵内——与认可版labrador/husky结构一致
    (认可版视频漂移仅-44px无需强对齐, stabilize_h天然保留振荡)。

    幂等(v58继承)：位移帧写入独立临时目录_tread_tmp_<state>(每次调用先清空)，
    抠图缓存永不改动。"""
    import shutil
    tmp_dir = os.path.join(ROOT, '_tread_tmp_' + state)
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir)
    imgs = [Image.open(p).convert('RGBA') for p in mat_paths]
    cxs = []
    for im in imgs:
        a = np.array(im)[:, :, 3]
        ys, xs = np.where(a > 40)
        cxs.append(float(xs.mean()) if len(xs) else -1.0)
    valid_idx = [i for i, c in enumerate(cxs) if c >= 0]
    if len(valid_idx) < 4:
        return mat_paths
    # 线性趋势拟合(去漂移), 残差=纯步态振荡→保留
    vi = np.array(valid_idx, float)
    vc = np.array([cxs[i] for i in valid_idx])
    k = np.polyfit(vi, vc, 1)
    trend = np.polyval(k, vi)
    anchor = float(np.median(trend))
    dxs = []
    for i in range(len(cxs)):
        if cxs[i] < 0:
            dxs.append(0); continue
        tr = float(np.polyval(k, i))
        dxs.append(int(round(anchor - tr)))
    print(f'  treadmill: drift={k[0]:.2f}px/f removed, oscillation preserved', flush=True)
    maxabs = max(abs(d) for d in dxs) if dxs else 0
    moved = 0
    out = []
    for i, p in enumerate(mat_paths):
        im = imgs[i]
        # 全帧统一画布 W+2*maxabs 左对齐（防混宽破坏 normalize union-bbox 对齐,
        # 同 stabilize_h_mats 幂等教训），再施加位移
        c = Image.new('RGBA', (im.width + 2 * maxabs, im.height), (0, 0, 0, 0))
        if dxs[i] == 0:
            c.paste(im, (maxabs, 0), im.split()[3])
            np_ = os.path.join(tmp_dir, os.path.basename(p))
            c.save(np_)
            out.append(np_)
            continue
        c.paste(im, (maxabs + dxs[i], 0), im.split()[3])
        np_ = os.path.join(tmp_dir, os.path.basename(p))
        c.save(np_)
        out.append(np_)
        moved += 1
    print(f'  treadmill_mats: shifted {moved}/{len(mat_paths)} frames (union-bbox→dog body, cache untouched)', flush=True)
    return out

def normalize_frames(mat_paths, target_h=None):
    """union-bbox 裁切 → 512 归一化 + 宽度钳制（防横躺姿态左右裁切），底部对齐。"""
    imgs = [Image.open(p).convert('RGBA') for p in mat_paths]
    boxes = [np.array(f)[:, :, 3] > 40 for f in imgs]
    xs, ys = [], []
    for b in boxes:
        yy, xx = np.where(b)
        if len(xx) == 0: continue
        xs += [xx.min(), xx.max()]; ys += [yy.min(), yy.max()]
    if not xs:
        return None
    ux0, uy0, ux1, uy1 = min(xs), min(ys), max(xs) + 1, max(ys) + 1
    uw, uh = ux1 - ux0, uy1 - uy0
    scale = min(0.918 * CANVAS / max(uw, uh), 1.0)   # 470/512≈0.918（随画布缩放）
    if target_h:
        hs = [(np.where(b)[0].max() - np.where(b)[0].min()) for b in boxes if b.any()]
        if hs:
            # 上限1.6而非1.0：1024档target普遍需对源放大~1.1-1.2×（旧512档源≈target
            # 无需放大）；封顶1.0会把happy/stretch压小14%/9%=状态切换忽大忽小。
            scale = min(target_h / float(np.median(hs)), 1.6)
    # 宽度钳制：横躺姿态防左右裁切
    if uw * scale > 0.977 * CANVAS: scale = 0.977 * CANVAS / uw   # 500/512
    if uh * scale > 0.930 * CANVAS: scale = 0.930 * CANVAS / uh   # 476/512
    bottom = GROUND
    frames = []
    for im in imgs:
        c = im.crop((ux0, uy0, ux1, uy1))
        tw, th = max(1, int(c.width * scale)), max(1, int(c.height * scale))
        c = c.resize((tw, th), Image.LANCZOS)
        canvas = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
        canvas.paste(c, ((CANVAS - tw) // 2, bottom - th), c.split()[3])
        frames.append(canvas)
    return frames

def sleep_scale_frames(frames):
    """sleep 逐帧姿态缩放（含连续姿态过渡的状态必须逐帧锚定，不能用单基准整体缩放）:
    union-bbox整体缩放以最大帧(坐h≈468)为基准→坐姿=1.7x其他状态+躺下突缩="过大+大→小"。
    逐帧目标高度: 坐档SLEEP_SIT_H / 躺档SLEEP_LIE_H / 中间按h线性过渡,
    相邻帧目标差<=3px=无跳变, 底部GROUND锚定。"""
    hs, ws = [], []
    for f in frames:
        a = np.array(f)[:, :, 3]
        yy, xx = np.where(a > 40)
        if len(xx) == 0:
            hs.append(0); ws.append(0); continue
        hs.append(yy.max() - yy.min() + 1); ws.append(xx.max() - xx.min() + 1)
    hs = np.array(hs, float); ws = np.array(ws, float)
    hmax = hs.max()
    out = []
    for i, f in enumerate(frames):
        h = hs[i]
        if h <= 0:
            out.append(f); continue
        if h >= 0.85 * hmax:
            th = SLEEP_SIT_H          # 坐档
        elif h <= 0.55 * hmax:
            th = SLEEP_LIE_H          # 躺档
        else:
            t = (h - 0.55 * hmax) / (0.30 * hmax)
            th = SLEEP_LIE_H + t * (SLEEP_SIT_H - SLEEP_LIE_H)
        s = th / h
        if ws[i] * s > 0.918 * CANVAS:   # 宽度钳制防越界（470/512 随画布缩放）
            s = 0.918 * CANVAS / ws[i]
        tw, tth = max(1, int(round(ws[i] * s))), max(1, int(round(h * s)))
        a = np.array(f)[:, :, 3]
        yy, xx = np.where(a > 40)
        y0, x0 = yy.min(), xx.min()
        crop = f.crop((x0, y0, x0 + int(ws[i]), y0 + int(h)))
        crop = crop.resize((tw, tth), Image.LANCZOS)
        canvas = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
        canvas.paste(crop, ((CANVAS - tw) // 2, GROUND - tth), crop.split()[3])
        out.append(canvas)
    return out

def harden_alpha(img):
    a = img.getchannel('A')
    a = a.point(lambda v: 255 if v > 100 else v)
    img.putalpha(a)
    return img

def harden_foam(img):
    """bath 泡沫硬化：视频模型把泡沫渲成半透明(RGB混入蓝盆/灰底=腿透视、灰泡)。
    不透明(a>200)的发蓝白泡(min>130 & b-r>=8)与中灰残雾(饱和<25, 120<min<=215)
    向实心白泡(250,250,248) blend，越暗补越满。纯白泡[238,238,235](b-r<0)/蓝盆(min<130)/
    金毛(r>b)均不触发。"""
    im = np.array(img).astype(np.float32)
    r, g, b, a = im[:, :, 0], im[:, :, 1], im[:, :, 2], im[:, :, 3]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    foam = (a > 200) & (((b - r) >= 8) | ((mx - mn) < 25)) & (mn > 130)
    t = np.clip((255.0 - mn) / 125.0, 0, 1)
    blend = np.where(foam, 0.75 + 0.25 * t, 0.0)
    for c, tgt in ((0, 250.0), (1, 250.0), (2, 248.0)):
        im[:, :, c] = im[:, :, c] * (1 - blend) + tgt * blend
    return Image.fromarray(np.clip(im, 0, 255).astype(np.uint8), 'RGBA')

def detrend_seq(frames, target_osc_ptp=65.0):
    """v60: 选定循环子窗口的漂移去除+振荡衰减到认可版基线。
    1) treadmill对全窗口全局线性拟合, 子窗口局部斜率≠全局(狗横穿轨迹非严格线性)
       →残留漂移=循环内滑移+wrap跳回, 必须去除。
    2) golden源视频狗体横向摆动固有~240px(@1024), 是认可版labrador/husky
       (55-70px)的4倍——100%保留=晃动/抖动(v58全压=21px滑步, 两个极端都被否)。
       取证认可版基线ptp∈[55,70]→衰减增益gain=target/osc_ptp≈0.27, 只衰减水平
       位移分量, 姿势/腿部内容(RGB帧差)与周期间差异完整保留。
    数学: cx=trend+osc → 目标cx=anchor+gain*osc
          dx=(anchor-trend)-(1-gain)*osc。gain=1退化为纯去趋势。
    画布余量: 最终cx收敛到anchor±gain*osc_half≈[508,572], 狗体宽~500→
    边缘∈[258,822]⊂[0,1024]不触边。"""
    cxs = []
    for f in frames:
        a = np.array(f)[:, :, 3]
        ys, xs = np.where(a > 40)
        cxs.append(float(xs.mean()) if len(xs) else -1.0)
    valid = [i for i, c in enumerate(cxs) if c >= 0]
    if len(valid) < 4:
        return frames
    vi = np.array(valid, float)
    vc = np.array([cxs[i] for i in valid])
    k = np.polyfit(vi, vc, 1)
    trend = np.array([float(np.polyval(k, i)) for i in range(len(frames))])
    osc = np.array([c - t if c >= 0 else 0.0 for c, t in zip(cxs, trend)])
    osc_ptp = float(np.ptp(osc[valid]))
    gain = min(1.0, target_osc_ptp / osc_ptp) if osc_ptp > 1 else 1.0
    anchor = float(np.median(trend[valid]))
    dxs = []
    for i in range(len(frames)):
        if cxs[i] < 0:
            dxs.append(0); continue
        dxs.append(int(round((anchor - trend[i]) - (1.0 - gain) * osc[i])))
    maxabs = max(abs(d) for d in dxs)
    out = []
    for i, f in enumerate(frames):
        if dxs[i] == 0:
            out.append(f); continue
        c = Image.new('RGBA', f.size, (0, 0, 0, 0))
        c.paste(f, (dxs[i], 0), f.split()[3])
        out.append(c)
    print(f'  detrend_seq: slope={k[0]:.2f}px/f osc_ptp={osc_ptp:.0f}→gain={gain:.2f} maxshift={maxabs}px', flush=True)
    return out

def refit_bounds(frames, margin=12):
    """stabilize_h 水平roll漂移可能把bbox推出canvas=边界截断（walk左切/run尾切）。
    全序列bbox极值检测：任何帧触边→整体等比缩小+重新居中，保证margin像素余量。"""
    tops, lefts, rights, bots = [], [], [], []
    for f in frames:
        a = np.array(f)[:, :, 3]
        ys, xs = np.nonzero(a > 30)
        if len(xs) == 0:
            continue
        tops.append(ys.min()); lefts.append(xs.min())
        rights.append(xs.max()); bots.append(ys.max())
    if not tops:
        return frames
    min_l, max_r, min_t = min(lefts), max(rights), min(tops)
    w, h = max_r - min_l + 1, max(bots) - min_t + 1
    # 需要的画布: w+2*margin / h+margin(底部GROUND固定)
    s = min(1.0, (CANVAS - 2 * margin) / w, (GROUND - margin) / h)
    if s >= 1.0 and min_l >= margin and (CANVAS - 1 - max_r) >= margin and min_t >= margin:
        return frames
    base_x = (CANVAS - int(round(w * s))) // 2   # 全序列union左缘落点，保持帧间相对位移
    out = []
    for f in frames:
        a = np.array(f)[:, :, 3]
        ys, xs = np.nonzero(a > 30)
        if len(xs) == 0:
            out.append(f); continue
        y0, x0, y1, x1 = ys.min(), xs.min(), ys.max(), xs.max()
        c = f.crop((x0, y0, x1 + 1, y1 + 1))
        tw, th = max(1, int(round(c.width * s))), max(1, int(round(c.height * s)))
        c = c.resize((tw, th), Image.LANCZOS)
        canvas = Image.new('RGBA', (CANVAS, CANVAS), (0, 0, 0, 0))
        px = base_x + int(round((x0 - min_l) * s))
        canvas.paste(c, (px, GROUND - th), c.split()[3])
        out.append(canvas)
    return out

def dedup_still(frames, thr=1.0, keep_every=1):
    """剔除连续近静止帧（beg等微动作状态 ping-pong后静止感翻倍）。
    保留首帧+与上一保留帧差>thr的帧，最多隔keep_every帧强制保留一帧防过度剔除。"""
    if len(frames) < 4:
        return frames
    out = [frames[0]]
    prev = np.array(frames[0])[:, :, 3].astype(np.float32)
    since = 0
    for f in frames[1:]:
        a = np.array(f)[:, :, 3].astype(np.float32)
        d = float(np.mean(np.abs(a - prev)))
        since += 1
        if d > thr or since >= 4:
            out.append(f)
            prev = a
            since = 0
    return out

def resample_seq(seq, target):
    n = len(seq)
    if n == target or n < 2:
        return seq
    idxs = [int(round(i * (n - 1) / (target - 1))) for i in range(target)]
    return [seq[i] for i in idxs]

def stabilize_h_mats(mats):
    """水平相位相关稳定化前移到 mats 全尺寸帧阶段（1088x832、边距150+px）：
    旧 stabilize_h 在 512 canvas 上做 np.roll 零清边——union 宽钳制500后右余量仅6px，
    漂移超限即把头/尾竖直切掉（walk头切20帧/roll右切9帧）。mats 阶段边距充足切不到，
    平移后由 normalize union-bbox 吸收位移。覆写原 m_*.png。

    ⚠️幂等修复(1024档)：旧实现把移动帧扩宽覆写(W+2ext)、静止帧保持W→缓存混宽
    (1088/1248并存)，重跑时 fft2 相位相关 (832,1088) vs (832,1248) 广播报错。
    现先把全部帧 pad 到统一画布(Wc=maxW, 左对齐)再算位移，输出统一宽 Wc+2ext，
    任意次重跑形状一致；多余透明边由 normalize union-bbox 裁掉，不影响成品。"""
    imgs = [Image.open(p).convert('RGBA') for p in mats]
    Wc = max(im.width for im in imgs)
    Hc = max(im.height for im in imgs)
    base = []
    for im in imgs:
        c = Image.new('RGBA', (Wc, Hc), (0, 0, 0, 0))
        c.paste(im, (0, 0))
        base.append(np.array(c)[:, :, 3].astype(np.float32))
    shifts = [0.0]
    for i in range(1, len(base)):
        f0, f1 = np.fft.fft2(base[i - 1]), np.fft.fft2(base[i])
        cp = f0 * np.conj(f1)
        peak = np.fft.ifft2(cp / (np.abs(cp) + 1e-9))
        pk = np.unravel_index(np.argmax(np.abs(peak)), peak.shape)
        dx = pk[1] if pk[1] < Wc // 2 else pk[1] - Wc
        dx = max(-16, min(16, dx))
        shifts.append(shifts[-1] + dx)
    m = float(np.mean(shifts))
    s_list = [int(round(sh - m)) for sh in shifts]
    ext = max(abs(s) for s in s_list) + 16   # 扩展画布：内容永不出界、零清只落在padding
    outW = Wc + 2 * ext
    moved = 0
    for i, p in enumerate(mats):
        s = s_list[i]
        c = Image.new('RGBA', (outW, Hc), (0, 0, 0, 0))
        c.paste(imgs[i], (ext, 0))
        arr = np.array(c)
        arr = np.roll(arr, -s, axis=1)
        if s > 0:
            arr[:, :s] = 0
        elif s < 0:
            arr[:, s:] = 0
        Image.fromarray(arr).save(p)
        if s != 0:
            moved += 1
    print(f'  stabilize(mats): shifted {moved}/{len(mats)} frames ext={ext}', flush=True)
    return mats

def stabilize_h(frames):
    """水平相位相关稳定化（保留垂直弹跳），消除主体漂移。"""
    alphas = [np.array(f)[:, :, 3].astype(np.float32) for f in frames]
    shifts = [0.0]
    for i in range(1, len(frames)):
        f0, f1 = np.fft.fft2(alphas[i - 1]), np.fft.fft2(alphas[i])
        cp = f0 * np.conj(f1)
        peak = np.fft.ifft2(cp / (np.abs(cp) + 1e-9))
        pk = np.unravel_index(np.argmax(np.abs(peak)), peak.shape)
        H, W = alphas[i].shape
        dy = pk[0] if pk[0] < H // 2 else pk[0] - H
        dx = pk[1] if pk[1] < W // 2 else pk[1] - W
        dx = max(-8, min(8, dx))
        shifts.append(shifts[-1] + dx)
    out = []
    for i, f in enumerate(frames):
        arr = np.array(f)
        s = int(round(shifts[i] - np.mean(shifts)))
        arr = np.roll(arr, -s, axis=1)
        if s > 0: arr[:, :s, 3] = 0
        elif s < 0: arr[:, s:, 3] = 0
        out.append(Image.fromarray(arr))
    return out

def _gait_profile(mats, min_len=40, leg_span_check=True):
    """walk/run 姿态选窗: 侧身档 ar∈[1.15,1.55](>1.55=趴卧段) + 腿质量span<0.9,
    取最长连续段(min_len)。gait_window 只按运动量选, 会选中正面intro(头动大)或趴卧段——
    golden walk 实测: intro ar 0.9-1.17 被 gait_window 选中→assets 全正面。
    ⚠️run 必须 leg_span_check=False: 奔跑四腿全伸展时 rowband 覆盖全宽 span≈1.0,
    span<0.9 会误杀全部侧身帧(run 实测仅选中20帧1周期→插值模糊+重复感)。"""
    ok = []
    for p in mats:
        a = np.array(Image.open(p).convert('RGBA'))[:, :, 3]
        ys, xs = np.nonzero(a > 30)
        if len(xs) == 0:
            ok.append(False); continue
        h = ys.max() - ys.min() + 1; w = xs.max() - xs.min() + 1
        ar = w / h
        if ar < 1.15 or ar > 1.55:
            ok.append(False); continue
        if not leg_span_check:
            ok.append(True); continue
        low = int(ys.min() + 0.75 * h)
        high = int(ys.min() + 0.97 * h)
        rowband = a[low:high, :] > 30
        cols = np.nonzero(rowband.any(axis=0))[0]
        if len(cols) == 0:
            ok.append(False); continue
        spans, s = [], 0
        for k in range(1, len(cols)):
            if cols[k] != cols[k - 1] + 1:
                spans.append((s, cols[k - 1])); s = k
        spans.append((s, len(cols) - 1))
        span = (cols[spans[-1][1]] - cols[spans[0][0]] + 1) / w
        ok.append(span < 0.9)
    best_l, best_s, s, l = 0, 0, 0, 0
    for i, o in enumerate(ok):
        if o:
            l += 1
            if l > best_l:
                best_l, best_s = l, s
        else:
            s, l = i + 1, 0
    return (best_s, best_s + best_l) if best_l >= min_len else None

def gait_crossfade(seq, K=6):
    """v57 walk循环接缝硬修: 末K帧向首帧线性crossfade（loop视频工业标准做法）。
    相位选窗无法把wrap seam压到帧间差以下(实测最优34>max帧间15),
    crossfade末帧=首帧→wrap=0; 倒数第k帧blend权重平滑, 帧间差≈正常步态差。
    视觉=步态末段自然回归起始相位(240ms), 远好于硬跳帧。"""
    n = len(seq)
    if n <= K + 2:
        return seq
    A0 = np.array(seq[0]).astype(np.float32)
    out = list(seq)
    for k in range(K):
        w = (k + 1) / float(K)
        idx = n - K + k
        cur = np.array(seq[idx]).astype(np.float32)
        out[idx] = Image.fromarray(
            np.clip((1 - w) * cur + w * A0, 0, 255).astype(np.uint8))
    return out


def find_walk_loop(frames, T, nperiods=3):
    """v57 walk循环重构: 引擎循环的实际wrap=末帧→首帧, 旧find_gait_loop只优化
    单周期相位接缝(i0→i0+T), wrap接缝实测24.98=1.65x帧间最大差=每循环一次可见跳帧
    ("走几秒顿一下")。直接扫描所有起点, 以 nperiods*T 帧窗口的 末→首 RGB掩膜差
    为目标选最优; 周期数加到3(更长循环=重复感更弱)。"""
    n = len(frames)
    arrs = [np.array(f) for f in frames]
    best_i, best_s = 0, 1e18
    for i0 in range(0, max(1, n - nperiods * T + 1)):
        e = i0 + nperiods * T
        if e > n:
            break
        a0, a1 = arrs[e - 1][:, :, 3], arrs[i0][:, :, 3]
        m = (a0 > 30) & (a1 > 30)
        if m.sum() < 500:
            continue
        seam = float(np.mean(np.abs(
            arrs[e - 1][:, :, :3].astype(np.float32)[m]
            - arrs[i0][:, :, :3].astype(np.float32)[m])))
        if seam < best_s:
            best_s, best_i = seam, i0
    return best_i, best_s


def find_loop_pair(frames, min_span_frac=0.33):
    """暴力找首尾最接近帧对作 loop 边界（lick 等循环类状态用）。"""
    arrs = [np.array(f)[:, :, 3].astype(np.float32) for f in frames]
    n = len(arrs)
    min_span = max(4, int(n * min_span_frac))
    best = (0, n - 1, 1e18)
    for i in range(0, n - min_span):
        for j in range(i + min_span, n):
            d = np.mean(np.abs(arrs[i] - arrs[j]))
            if d < best[2]:
                best = (i, j, d)
    return best

def find_gait_loop(frames, min_span=8, max_span_frac=0.6):
    """walk/run 步态循环: RGB掩膜自相关找完整步态周期T, 再相位对齐起点。
    必须用RGB而非alpha: 幼犬剪影左右对称→alpha自相关在半视频处产生假极小(walk实测T=71),
    RGB带纹理能锁定真步态周期(walk/run均T=16)。min_span绝对帧界[8,~0.6n]:
    24fps幼犬gait周期≈10-20帧; 按比例缩放min_span在长窗口会跳过真周期落假峰。"""
    arrs = np.array([np.array(f) for f in frames])  # RGBA
    n = len(arrs)
    lo = max(6, min_span)
    hi = min(n - 2, max(24, int(n * max_span_frac)))
    scores = {}
    for T in range(lo, hi + 1):
        vals = []
        for i in range(n - T):
            a0, a1 = arrs[i][:, :, 3], arrs[i + T][:, :, 3]
            mask = (a0 > 30) & (a1 > 30)
            if mask.sum() < 500:
                continue
            vals.append(float(np.mean(np.abs(
                arrs[i][:, :, :3].astype(np.float32)[mask]
                - arrs[i + T][:, :, :3].astype(np.float32)[mask]))))
        scores[T] = float(np.mean(vals)) if vals else 1e18
    # 局部极小优先(周期峰值), 避免大T假最小
    cands = [T for T in range(lo + 1, hi)
             if scores[T] <= scores[T - 1] and scores[T] <= scores[T + 1]]
    if cands:
        best_T = min(cands, key=lambda T: scores[T])
    else:
        best_T = min(scores, key=scores.get)
    T = best_T
    # 相位对齐起点(RGB掩膜), 限制 i0 使窗口至少容纳2完整周期(重复感减半)
    def seam(i):
        a0, a1 = arrs[i][:, :, 3], arrs[i + T][:, :, 3]
        m = (a0 > 30) & (a1 > 30)
        if m.sum() < 500:
            return 1e18
        return float(np.mean(np.abs(
            arrs[i][:, :, :3].astype(np.float32)[m] - arrs[i + T][:, :, :3].astype(np.float32)[m])))
    i0 = int(min(range(max(1, n - T)), key=seam))
    i0 = min(i0, max(0, n - 1 - 2 * T))
    print(f'  gait loop: period T={T} start={i0} score={scores[T]:.1f}', flush=True)
    return i0, i0 + T

def process_state(name):
    print(f'== {name} ==', flush=True)
    fps = extract(name)
    if not fps:
        print(f'  SKIP: no mp4', flush=True); return
    mats = cutout_frames(fps, name)
    if name in ('sleep', 'stretch'):
        # 过渡视频不做面积过滤（躺/站面积差异大），取全部非边缘帧；
        # sleep 开头正面站/坐过渡帧（奇怪后腿主体）必须用 _front_standing 剔除
        ms = [alpha_metrics(m) for m in mats]
        sel = [m for m, t in zip(mats, ms) if not t['edge'] and t['area'] > 1000]
        front = [np.array(Image.open(m).convert('RGBA'))[:, :, 3] for m in sel]
        nfront = sum(1 for a in front if _front_standing(a))
        if nfront:
            sel = [m for m, a in zip(sel, front) if not _front_standing(a)]
            print(f'  transition: dropped {nfront} front-facing frames', flush=True)
        # 清醒坐立帧剔除（认可版sleep起点h/w≈1.38，>1.40=清醒坐立非睡觉）:
        ups = []
        for m in sel:
            a = np.array(Image.open(m).convert('RGBA'))[:, :, 3]
            ys, xs = np.where(a > 30)
            if len(xs) == 0:
                ups.append(False); continue
            h = ys.max() - ys.min() + 1; w = xs.max() - xs.min() + 1
            ups.append(h / w > 1.40)
        nup = sum(ups)
        if nup and len(sel) - nup >= 24:
            sel = [m for m, u in zip(sel, ups) if not u]
            print(f'  transition: dropped {nup} upright-awake frames (h/w>1.40)', flush=True)
        assert len(sel) >= 24, f'过滤后仅{len(sel)}帧, 视频需重生成'
        print(f'  transition: kept {len(sel)}/{len(mats)}', flush=True)
    else:
        if name in ('walk', 'run'):
            pw = _gait_profile(mats, leg_span_check=(name == 'walk'))
            if pw:
                s, e = pw
                print(f'  gait profile window [{s}:{e}] len={e-s} (side-facing selected)', flush=True)
                if (e - s) >= 40:
                    # run: profile窗已是侧身奔跑段; 内层gait_window面积容差±45%误杀
                    # 奔跑伸展帧(身体拉长面积波动大)→收窄20帧仅1周期=插值模糊+重复感。
                    # 整段交给find_gait_loop选2周期（76帧实测T=18→37帧真实帧）。
                    # v60d: walk同理——gait_window会把profile窗截断到不足2T
                    # (实测64帧窗T=37→单周期回退), 整段交给find_gait_loop扫描最优接缝。
                    pass
                else:
                    gw = gait_window(mats[s:e])
                    if gw and (gw[1] - gw[0]) >= 16:
                        s2, e2 = gw
                        print(f'  gait window [{s + s2}:{s + e2}] len={e2-s2} (motion-selected in profile)', flush=True)
                        s, e = s + s2, s + e2
            else:
                gw = gait_window(mats)
                if gw:
                    s, e = gw
                    print(f'  gait window [{s}:{e}] len={e-s} (motion-selected, no profile window)', flush=True)
                else:
                    s, e, _, _ = clean_window(mats)
                    print(f'  gait window fallback [{s}:{e}]', flush=True)
        else:
            s, e, nclean, ntot = clean_window(
                mats, bottom_ok=(name != 'beg'),   # beg 直立抬爪: 底触=脚出框裁切
                relax=(name == 'pet'),             # pet: 手臂伸出屏幕=有意设计
                extra_ok=([t and g for t, g in zip(tub_ok_flags(mats), gray_ok_flags(mats))]
                          if name == 'bath' else None))
            print(f'  clean window [{s}:{e}] len={e-s} ({nclean}/{ntot} ok)', flush=True)
            if name in PROFILE_STATES:
                pw = posture_window(mats[s:e], mode=PROFILE_STATES[name])
                if pw:
                    s2, e2 = pw
                    print(f'  profile window [{s + s2}:{s + e2}] len={e2 - s2} (side-facing selected)', flush=True)
                    s, e = s + s2, s + e2
        if e - s < 4:
            print('  TOO FEW, skip', flush=True); return
        sel = stabilize_h_mats(mats)[s:e]
    if name in ('walk', 'run'):
        sel = treadmill_mats(sel, name)   # v57: normalize前对齐→union-bbox收缩到狗本体→scale由target_h决定 (v58: 非破坏性)
    frames = normalize_frames(sel, TARGET_H.get(name))
    if not frames:
        print('  normalize failed', flush=True); return
    frames = refit_bounds(frames)      # 修 stabilize roll 漂移导致的边界截断（walk左/run右）
    if name == 'sleep':
        frames = sleep_scale_frames(frames)
    if name == 'beg':
        frames = dedup_still(frames)   # 微动作状态剔连续静止帧，ping-pong静止感减半
    if name in PINGPONG:
        seq = frames + frames[-2:0:-1]
    elif name in ONESHOT:
        seq = frames          # intro+loop 分段在引擎 ANIMS 的 intro_frames 处理
    else:
        if name in ('walk', 'run'):
            # v60: walk=2原生周期真实帧(v55双周期结构, 无v58重采样/crossfade陷阱)。
            # 根因(v60取证): 单周期循环每1.2s完全相同帧原样重播+wrap接缝跳变
            # (实测walk接缝alpha差88.5=帧间均值40.2的2.2倍 vs 认可版47.5/73.8=0.64比)
            # =用户报"一套动画帧不断重复播放"。2周期窗含AI视频周期间自然微差异,
            # 且用find_walk_loop在2T窗口扫描最优wrap接缝。run保持单周期(用户已认可:
            # 跑动帧间差79.1已达认可版86.5量级, 双周期会拉长gallop节奏)。
            i, j = find_gait_loop(frames)
            T = j - i
            if name == 'walk' and i + 2 * T < len(frames):
                w, seam = find_walk_loop(frames, T, nperiods=2)
                seq = frames[w:w + 2 * T + 1]
                print(f'  gait seq: {len(seq)} frames = 2 native periods (T={T} start={w} seam={seam:.1f})', flush=True)
                seq = detrend_seq(seq)   # v60: 子窗口残留漂移二次去除(run已认可不动)
                # v60d: 隔帧抽样(stride2)。根因取证: golden全帧提取帧间RGB差仅15
                # (24fps每帧微动) vs 认可版labrador=21/husky=40(隔帧提取, 每帧动作幅度大),
                # 小帧差=视觉上"慢速翻页式重复"。stride2后fd=22.4≈labrador认可版21,
                # 双周期结构保留(周期不重复), 帧延迟翻倍保持原生步频。
                seq = seq[::2]
                print(f'  stride2 sample: {len(seq)} frames (T={T // 2})', flush=True)
            else:
                seq = frames[i:j + 1]
                print(f'  gait seq: {len(seq)} frames = 1 native period (T={T})', flush=True)
        else:
            i, j, d = find_loop_pair(frames)
            seq = frames[i:j + 1]
            print(f'  loop pair ({i},{j}) seam={d:.1f}', flush=True)
    if name in RT_FRAMES:
        seq = resample_seq(seq, RT_FRAMES[name])
    for k, f in enumerate(seq):
        im = harden_alpha(f)
        if name == 'bath':
            im = harden_foam(im)
        im.save(os.path.join(OUT_DIR, f'{name}_{k:02d}.png'))
    print(f'  WROTE {len(seq)} frames → {OUT_DIR}/{name}_*', flush=True)
    return len(seq)

if __name__ == '__main__':
    only = sys.argv[1:] if len(sys.argv) > 1 else None
    for n in (only or ALL_STATES):
        try:
            process_state(n)
        except Exception as ex:
            print(f'  ERROR {n}: {ex}', flush=True)
    print('EXTRACT_DONE', flush=True)
