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
import cv2
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
# v-samoyed2: 用户铁律"宠物动作按本次验收视频完成"——ping-pong倒播非视频内容、
# resample抽帧=2倍速/掉帧，全废。新批次全部native 24fps全帧。
PINGPONG = set()
# 一次性/过渡类
ONESHOT = {'sleep', 'stretch', 'happy', 'surprised', 'play_dead', 'pet', 'kiss',
           'idle', 'eat', 'bark', 'sit', 'dance', 'beg', 'bath', 'lick',
           'roll', 'wave', 'type'}  # v-samoyed2: 全态native全窗; type整视频敲键=全窗(loop由引擎ANIMS定)
# v100: 3新动作（亲亲/挥手/敲键盘），参考图质量路线=高对比青底源
# 高度锚定 target_h 按姿态档（跨档=忽大忽小）。新宠物标定法：先跑 idle 测站立 h≈274，
# 坐姿视频取稳坐段测 h≈316，伸展段≈291，躺卧段≈204-217。
# v2: 1024画布，精确=旧512资产实测中位h×2（保持屏幕占比不变，防状态切换忽大忽小）
TARGET_H = {
    'idle': 546, 'bark': 546, 'happy': 544, 'dance': 544,
    'beg': 540, 'bath': 542, 'sit': 630,
    'stretch': 580,
    'walk': 560, 'run': 542,          # v76: walk 508→560 对齐idle档(546)——用户报walk明显小于其他状态(实测屏上85px vs idle 135px); run保持
    'lick': 542, 'surprised': 544,
    'eat': 474,
    'pet': 546,   # 摸摸头: 站姿档(视频为四腿站立3/4视), 与idle/bark同档防忽大忽小
    'roll': 546, 'play_dead': 344,    # v110: 630→546(#3用户报roll比其他大; 取证meanW624 vs sit525; 站姿档对齐idle)
    'kiss': 630, 'wave': 630, 'type': 640,  # v100: kiss/wave坐姿档=sit 630; type含键盘整体bbox 640
}
# 重采样到引擎 ANIMS 声明帧数（引擎按 count 加载，帧数必须 1:1）
# v-samoyed2: 清空——全态native全帧禁resample(速度/流畅度忠实视频)，帧数=extract实测回填ANIMS。
RT_FRAMES = {
}
ALL_STATES = ['idle', 'sit', 'eat', 'bark', 'happy', 'roll', 'dance',
              'beg', 'bath', 'lick', 'surprised', 'play_dead', 'sleep', 'stretch',
              'walk', 'run', 'pet', 'kiss', 'wave', 'type']
# kiss/wave/type = mochi 验证的扩展态（不做则从此处+TARGET_H/RT_FRAMES/deploy ANIMS/引擎ANIMS 五处删；
# 要做需先按阶段2 首帧锚定范式合成交互首帧再生成视频，type 裁稳定段逻辑见 dispatch else 分支）。
# 缺视频的状态 extract 自动跳过返回，留着不报错。
# 姿态选窗（bark 选纯侧身段跳3/4正面intro；sit 选稳坐段跳站姿intro；eat 选侧身段）
# v76: idle 移出——新idle视频设计为FRONT VIEW正面朝向(用户要求开屏正面迎向用户)，
# 旧high选窗会把正面段当intro跳过=正面修复失效。
PROFILE_STATES = {'bark': 'high', 'sit': 'low', 'eat': 'high'}
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

def chroma_cutout_frame(fp):
    """v102/v103: type专用色距抠图。isnet显著性模型把奶白键盘当背景删除(用户报键盘消失)。
    v103取证: 地平线模糊横带=低饱和青(H≈43,S≈11)与狗/键盘连通→灰带伪影;
    键盘暖白(H≈28,S≈32)/狗(H≈16,S≈58)。
    算法: ①RGB色距去青底(四角采样) ②HSV低饱和青横带mask(H∈[33,70]&S<22)置透明
    ③CC清理(全宽h<30细条=键盘阴影线/小碎片删除)。"""
    im = Image.open(fp).convert('RGB')
    arr = np.array(im).astype(np.float32)
    H, W = arr.shape[:2]
    m = 20
    corners = np.concatenate([arr[:m, :m].reshape(-1, 3), arr[:m, -m:].reshape(-1, 3),
                              arr[-m:, :m].reshape(-1, 3), arr[-m:, -m:].reshape(-1, 3)])
    bg = corners.mean(axis=0)
    d = np.linalg.norm(arr - bg, axis=-1)
    alpha = np.clip((d - 45) / 45, 0, 1)
    # v103: 低饱和青横带(背景虚化带)置透明——暖白键盘/狗不受影响(H<33或S>30)
    hsv = cv2.cvtColor(np.array(im)[:, :, ::-1], cv2.COLOR_BGR2HSV)
    band = (hsv[..., 0] >= 33) & (hsv[..., 0] <= 70) & (hsv[..., 1] < 22)
    alpha[band] = 0
    # v105: 青色色相硬删——背景亮渐变带(H≈94/S≈133)比四角亮逃出色距, 色相法根治;
    # 狗H<30/奶白键盘H<40/黑色S<40 全安全
    cyan = (hsv[..., 0] >= 75) & (hsv[..., 0] <= 115) & (hsv[..., 1] > 90) & (hsv[..., 2] > 120)
    alpha[cyan] = 0
    # v104: 键盘下暗阴影条(S<30&V<160, 奶白键盘V>200/狗S>40均安全)置透明
    # v117: 限底部50行——真键盘含深色键帽(S<30&V<160全中), 全图删=键帽变洞
    yy = np.arange(H)[:, None] * np.ones((1, W))
    shadow = (hsv[..., 1] < 30) & (hsv[..., 2] < 160) & (yy > H - 50)
    alpha[shadow] = 0
    # v107: 冷调残留硬删——底带/左右缘背景残丝(B-R>6冷调: RGB≈[169,195,196]等);
    # 取证: 狗白毛B-R≈-30/键帽B-R≈-33全暖调安全, 黑色字B-R≈0不触发。
    cold = (arr[..., 2] - arr[..., 0]) > 6
    alpha[cold] = 0
    alpha = (alpha * 255).astype(np.uint8)
    # CC清理: 全宽细条(h<30, w>0.6W)=键盘下阴影线; 小碎片<2000px
    from scipy.ndimage import label
    lab, n = label(alpha > 128)
    if n > 1:
        sizes = np.bincount(lab.ravel()); sizes[0] = 0
        for cc in range(1, n + 1):
            if sizes[cc] == 0:
                continue
            ys, xs = np.where(lab == cc)
            h, w = ys.max() - ys.min() + 1, xs.max() - xs.min() + 1
            if (h < 30 and w > 0.6 * W) or sizes[cc] < 2000:
                alpha[lab == cc] = 0
    # v104: 二值化——半透明渐变残余(1-127)在深色底显灰横带, 必须硬切
    alpha = ((alpha > 128) * 255).astype(np.uint8)
    # v105: 底缘垂线清除——键盘主体底缘(row fg>300)以下连体残丝整行删
    rows = (alpha > 0).sum(axis=1)
    body_rows = np.where(rows > 300)[0]
    if len(body_rows):
        alpha[body_rows.max() + 1:, :] = 0
    # v119: 轮廓内洞修复——chroma误删两类像素(白桌=发白发亮+逐帧闪):
    # ①高光(眼/颊/键帽顶)带环境青色调中band/cold规则→洞; ②键帽间隙透青底→洞。
    # 修法: 主CC轮廓fill_holes得洞; 内容洞=回贴raw原色(恢复高光),
    # 键盘带(y>600)青色洞=填奶白基色(参考图为实心键盘)。洞限≤3000px防填腋窝真透空。
    from scipy.ndimage import binary_fill_holes
    lab2, n2 = label(alpha > 128)
    if n2 >= 1:
        sz2 = np.bincount(lab2.ravel()); sz2[0] = 0
        main = lab2 == int(np.argmax(sz2))
        holes = binary_fill_holes(main) & (alpha <= 128)
        hl, hn = label(holes)
        hsz = np.bincount(hl.ravel()); hsz[0] = 0
        cream = np.array([233, 216, 190], dtype=np.float32)
        hsvf = cv2.cvtColor(arr.astype(np.uint8)[:, :, ::-1], cv2.COLOR_BGR2HSV)
        for c in range(1, hn + 1):
            if hsz[c] == 0 or hsz[c] > 3000:
                continue
            msk = hl == c
            ys, xs = np.where(msk)
            yc = ys.mean()
            # 白度分类(源坐标1088x832): 高光洞=白回贴原色; 键帽带(y620-750)洞填奶白;
            # 键帽间隙hole为封闭洞(爪间透空是notch不在此), 按y带填安全
            Vm = hsvf[msk, 2].mean(); Sm = hsvf[msk, 1].mean() / 255.0
            if Vm >= 240 and Sm <= 0.12:
                alpha[msk] = 255              # 眼/颊/键帽高光回贴raw原色
            elif 620 <= yc <= 750:
                arr[msk] = cream              # 键帽间隙透青底→奶白实心
                alpha[msk] = 255
            # 其余(底缘残影/脸部非白洞)保持透明
    # v119b: 键盘带notch直填——穿透性间隙(键帽间/左端整帽缺失)与外背景连通,
    # fill_holes检测不到; 按键盘水平范围(y615-786)内透明像素直接填奶白
    # (含爪间透空=键盘面露出, 更贴近参考图实心键盘)
    creamm = (arr[..., 0] > 215) & (arr[..., 1] > 190) & (arr[..., 2] > 150) & (arr[..., 2] < 225) & (alpha > 128)
    cols = np.where(creamm[694:774].sum(0) > 3)[0]
    if len(cols):
        x0, x1 = max(0, cols.min() - 8), min(arr.shape[1], cols.max() + 8)
        zone = np.zeros(alpha.shape, bool)
        zone[612:778, x0:x1] = True
        fillme = zone & (alpha == 0)
        arr[fillme] = cream
        alpha[fillme] = 255
    out = np.dstack([arr, alpha.astype(np.float32)]).astype(np.uint8)
    return Image.fromarray(out, 'RGBA')

def cutout_frames(fps, state):
    """isnet-general-use 抠图（白底/白毛必须用此模型；u2net 液化白色头部）。
    type例外: isnet把键盘当背景删 → chroma色距保键盘。"""
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
    # v-samoyed2: type改走isnet——新type.mp4为白底且isnet完整保留狗+键盘(探针对比:
    # chroma白毛开洞/hybrid键盘右侧奶白残带, 均废)。chroma分支仅留作旧青底管线历史。
    if state == 'type_chroma_legacy':
        # v102: 色距抠图保键盘; 旧isnet缓存必须强制重切
        marker = os.path.join(mats_dir, '_chroma_v119')
        if existing and not os.path.exists(marker):
            import shutil
            shutil.rmtree(mats_dir)
            os.makedirs(mats_dir, exist_ok=True)
            existing = []
            print('  [cache invalid] type isnet mats → chroma re-cut', flush=True)
        open(marker, 'w').close()
    if len(existing) >= len(fps):
        return existing
    if state == 'type_chroma_legacy':
        mats = []
        for i, fp in enumerate(fps):
            outp = os.path.join(mats_dir, f'm_{i:04d}.png')
            if os.path.exists(outp):
                mats.append(outp); continue
            chroma_cutout_frame(fp).save(outp)
            mats.append(outp)
            if i % 20 == 0:
                print(f'    mat {i}/{len(fps)}', flush=True)
        return mats
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

def treadmill_mats(mat_paths, state, smooth=2, mode='linear', win=25):
    """walk/run 线性去趋势对齐（mats阶段, normalize之前）:
    walk源视频狗真实横穿画面(-667px漂移)→normalize的union-bbox横跨整个行走距离
    →宽度钳制压死scale→walk h=169px仅idle的31%。必须逐帧位移收缩union-bbox。

    mode='linear'(walk/run): 一次拟合质心趋势→每帧只对齐趋势分量(去除净漂移)。
    mode='median'(roll, v76): 狗滚动时左右非线性徘徊(质心p2p=784px)，线性拟合残差
    仍647px→宽度钳制0.825→roll仅473/500。中值滤波W=25分离趋势(徘徊)与残差(滚动
    摆动)，残差90px→union_w=656→scale不受宽度钳制→精确恢复500。窗宽25≈半个滚动
    周期，滚动摆动在窗内均值≈0被滤出趋势；残留90px=自然滚动摆动保留在精灵内。

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
    # 趋势拟合(去漂移), 残差=纯振荡→保留
    vi = np.array(valid_idx, float)
    vc = np.array([cxs[i] for i in valid_idx])
    if mode == 'median':
        from scipy.ndimage import median_filter
        trend_full = median_filter(vc, size=win, mode='nearest')
        anchor = float(np.median(trend_full))
        dxs = []
        for i in range(len(cxs)):
            if cxs[i] < 0:
                dxs.append(0); continue
            tr = float(trend_full[valid_idx.index(i)])
            dxs.append(int(round(anchor - tr)))
        print(f'  treadmill(median W={win}): wander removed, roll sway preserved', flush=True)
    else:
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

def warm_balance_frames(frames, target_rgb=(205.0, 190.0, 175.0)):
    """v107: roll发青修复(用户报颜色发青)。取证: roll白毛区H偏蓝绿(S≈8-10)而
    idle认可白胸RGB(205,190,175)暖白。方法: 每帧取白毛像素(S<30&V>140&α>200)中值
    为白点, 全窗白点中值→增益=target/white(逐通道clip 0.85-1.20), 全帧统一增益
    (窗中值基准=无帧间闪烁)。"""
    wps = []
    datas = []
    for f in frames:
        a = np.array(f)
        rgb = a[:, :, :3].astype(float)
        hsv = cv2.cvtColor(a[:, :, :3], cv2.COLOR_RGB2HSV).astype(int)
        m = (a[:, :, 3] > 200) & (hsv[:, :, 1] < 30) & (hsv[:, :, 2] > 140)
        datas.append(a)
        if m.sum() > 100:
            wps.append(np.median(rgb[m], axis=0))
    if not wps:
        return frames
    white = np.median(np.array(wps), axis=0)
    gain = np.clip(np.array(target_rgb) / np.maximum(white, 1), 0.85, 1.20)
    print(f'  warm_balance: white={white.round(0)} gain={gain.round(3)}', flush=True)
    out = []
    for a in datas:
        b = a.copy()
        b[:, :, :3] = np.clip(b[:, :, :3].astype(float) * gain, 0, 255).astype(np.uint8)
        out.append(Image.fromarray(b, 'RGBA'))
    return out

def roll_perframe_scale(frames, stand_h=548, lie_h=450):
    """v101: roll站/躺姿态差巨大(union归一后站帧h=826=2×idle主体412, 用户报大小出入)。
    逐帧锚定(同sleep_scale_frames思路): 源h>=0.80*hmax→站档stand_h(≈idle档412-474);
    h<=0.55*hmax→躺档lie_h; 中间线性过渡, 底部GROUND锚定+宽度钳制。
    v107: stand_h 450→548对齐idle认可站高(用户报"从小变大"根因=站帧偏小);
    lie_h 420→450(躺姿面积与站姿视觉体量匹配)。"""
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
        if h >= 0.80 * hmax:
            th = stand_h
        elif h <= 0.55 * hmax:
            th = lie_h
        else:
            t = (h - 0.55 * hmax) / (0.25 * hmax)
            th = lie_h + t * (stand_h - lie_h)
        s = th / h
        if ws[i] * s > 0.918 * CANVAS:
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

def stabilize2d_mats(mats, win=5):
    """v110 (#1#2): 2D相位相关高频抖动去除——stabilize_h_mats只稳水平, 垂直弹跳/
    AI视频时序微抖残留=用户报"不少动作画面不停抖动/抖腿"。累积位移序列median(win)
    =低频参考(大动作), 修正量=raw-smooth=仅高频抖动(±几px), 大动作(滚/步态)不被破坏。
    随后alpha 3中值去逐帧毛刺闪烁。覆写 mats。幂等(二次跑修正量≈0)。"""
    from scipy.ndimage import median_filter
    imgs = [Image.open(p).convert('RGBA') for p in mats]
    Wc = max(im.width for im in imgs); Hc = max(im.height for im in imgs)
    base = []
    for im in imgs:
        c = Image.new('RGBA', (Wc, Hc), (0, 0, 0, 0))
        c.paste(im, (0, 0))
        base.append(np.array(c)[:, :, 3].astype(np.float32))
    sx = [0.0]; sy = [0.0]
    for i in range(1, len(base)):
        f0, f1 = np.fft.fft2(base[i - 1]), np.fft.fft2(base[i])
        cp = f0 * np.conj(f1)
        peak = np.fft.ifft2(cp / (np.abs(cp) + 1e-9))
        pk = np.unravel_index(np.argmax(np.abs(peak)), peak.shape)
        dx = pk[1] if pk[1] < Wc // 2 else pk[1] - Wc
        dy = pk[0] if pk[0] < Hc // 2 else pk[0] - Hc
        dx = max(-16, min(16, dx)); dy = max(-16, min(16, dy))
        sx.append(sx[-1] + dx); sy.append(sy[-1] + dy)
    sxr, syr = np.array(sx), np.array(sy)
    cx = np.round(sxr - median_filter(sxr, size=win)).astype(int)
    cy = np.round(syr - median_filter(syr, size=win)).astype(int)
    extx = int(max(abs(v) for v in cx)) + 16
    exty = int(max(abs(v) for v in cy)) + 16
    H2, W2 = Hc + 2 * exty, Wc + 2 * extx
    # v110b: 全部帧统一到扩展画布(内存), 再blend, 再同尺寸存盘——
    # 修复v110a逐帧不同尺寸广播崩溃。
    shifted = []
    moved = 0
    for i, im in enumerate(imgs):
        c = np.zeros((H2, W2, 4), np.uint8)
        c[exty:exty + im.height, extx:extx + im.width] = np.array(im)
        if cx[i] or cy[i]:
            c = np.roll(c, (-int(cy[i]), -int(cx[i])), axis=(0, 1))
            if cy[i] > 0: c[:cy[i]] = 0
            elif cy[i] < 0: c[cy[i]:] = 0
            if cx[i] > 0: c[:, :cx[i]] = 0
            elif cx[i] < 0: c[:, cx[i]:] = 0
            moved += 1
        shifted.append(c)
    # alpha时域3帧FIR blend(0.25/0.5/0.25): AI视频轮廓/腿逐帧微跳=肉眼抖动;
    # ≥128→255(3帧多数位置=平滑轮廓); 被blend补alpha的像素RGB用邻帧alpha加权外推(防黑边)。
    for i in range(1, len(shifted) - 1):
        a_cur = shifted[i][:, :, 3].astype(np.float32)
        b = 0.25 * shifted[i - 1][:, :, 3] + 0.5 * a_cur + 0.25 * shifted[i + 1][:, :, 3]
        new_a = np.where(b >= 128, 255, np.round(b)).astype(np.uint8)
        add = (new_a == 255) & (a_cur < 128)
        if add.any():
            pa = shifted[i - 1][:, :, 3].astype(np.float32) / 255.0
            na = shifted[i + 1][:, :, 3].astype(np.float32) / 255.0
            wsum = (pa + na)[..., None] + 1e-6
            fill = (pa[..., None] * shifted[i - 1][:, :, :3] + na[..., None] * shifted[i + 1][:, :, :3]) / wsum
            rgb = shifted[i][:, :, :3].astype(np.float32)
            rgb = np.where(add[..., None], fill, rgb)
            shifted[i][:, :, :3] = np.round(rgb).astype(np.uint8)
        shifted[i][:, :, 3] = new_a
    for c, p in zip(shifted, mats):
        Image.fromarray(c).save(p)
    print(f'  stabilize2d: shift-corrected {moved}/{len(mats)} + alpha-blend {len(mats)-2} (ext={extx},{exty})', flush=True)
    return mats

def calmest_window(mats, win=48):
    """v110 (#2): 选mask-jump均值最低的win长窗(idle开场抖腿段剔除)。数据驱动。"""
    areas = []
    masks = []
    for p in mats:
        m = np.array(Image.open(p).convert('RGBA'))[:, :, 3] > 30
        masks.append(m); areas.append(m.sum())
    js = []
    for i in range(1, len(masks)):
        js.append((masks[i - 1] ^ masks[i]).sum() / max(areas[i - 1], 1))
    js = np.array(js)
    if len(js) < win:
        return 0, len(mats)
    best_s, best_v = 0, None
    for s in range(0, len(js) - win + 2, 2):
        v = js[s:s + win - 1].mean()
        if best_v is None or v < best_v:
            best_v, best_s = v, s
    print(f'  calmest window [{best_s}:{best_s + win}) mean_jump={best_v:.3f} (full={js.mean():.3f})', flush=True)
    return best_s, best_s + win

def type_drop_ghost(mats):
    """v110 (#6): 源视频开头灰色斑块被isnet当主体→弃帧。判据: 上半亮neutral块
    (v>=225,sat<25)面积>1.4×中位数=含斑块。数据驱动, 仅删超标帧。"""
    vals = []
    for p in mats:
        a = np.array(Image.open(p).convert('RGBA'), np.int32)
        m = a[:, :, 3] > 30
        v = a[:, :, :3].max(axis=2); sat = v - a[:, :, :3].min(axis=2)
        ys, xs = np.where(m)
        tb = 0
        if len(ys):
            y0 = ys.min(); hh = ys.max() - y0 + 1
            band = np.zeros_like(m); band[y0:y0 + int(0.5 * hh)] = True
            tb = int((m & band & (v >= 225) & (sat < 25)).sum())
        vals.append(tb)
    vals = np.array(vals)
    med = np.median(vals[2:]) if len(vals) > 4 else np.median(vals)
    thr = 1.4 * max(med, 1)
    keep = [p for p, t in zip(mats, vals) if t <= thr]
    print(f'  type ghost-drop: {len(mats) - len(keep)} frames (thr={thr:.0f} med={med:.0f})', flush=True)
    return keep if keep else mats

def kiss_degray(mats):
    """v110 (#5): kiss走近凑脸段rembg把灰色渐变背景当主体保留(面积极达83%画布,
    四角r==g==b灰 alpha半透)=用户报"背景灰色闪烁"。flood-fill从边界连通的
    neutral灰区(sat<=12, v<=240)清零。数据驱动逐帧。"""
    from scipy.ndimage import label
    for p in mats:
        im = Image.open(p).convert('RGBA')
        a = np.array(im)
        rgb = a[:, :, :3].astype(np.int32); al = a[:, :, 3]
        sat = rgb.max(axis=2) - rgb.min(axis=2); v = rgb.max(axis=2)
        grayish = (al > 0) & (sat <= 12) & (v <= 240)
        lab, n = label(grayish)
        if n == 0:
            continue
        border = set(lab[0, :]) | set(lab[-1, :]) | set(lab[:, 0]) | set(lab[:, -1])
        border.discard(0)
        if not border:
            continue
        kill = np.isin(lab, list(border))
        a[kill, 3] = 0
        Image.fromarray(a).save(p)
    print(f'  kiss degray: flood-filled border-gray on {len(mats)} frames', flush=True)
    return mats

def beg_trim_tail(mats, thr=0.25):
    """v110 (#7): beg作揖后段下半身被源视频画框截断(底部3行填充率骤升=平切)。
    从尾回扫第一个fill<thr的帧=截断点, 弃尾。数据驱动。"""
    fills = []
    for p in mats:
        m = np.array(Image.open(p).convert('RGBA'))[:, :, 3] > 30
        ys, xs = np.where(m)
        if len(ys) == 0:
            fills.append(0.0); continue
        bot = ys.max(); w = m[ys.min():bot + 1].any(axis=0).sum()
        fills.append(m[max(bot - 2, 0):bot + 1].sum() / max(w * 3, 1))
    fills = np.array(fills)
    e = len(mats)
    for i in range(len(mats) - 1, -1, -1):
        if fills[i] < thr:
            e = i + 1; break
    print(f'  beg tail-trim: [{0}:{e}) (tail fill={fills[-1]:.2f} thr={thr})', flush=True)
    return 0, e

def soft_highlight(img, knee=210.0, ratio=0.45):
    """v110 (#4): bath泡沫硬化后白毛过曝(v>240占82%)。knee以上向knee压缩:
    out=knee+(v-knee)*ratio, 保泡沫立体感去白闪。"""
    a = np.array(img).astype(np.float32)
    rgb = a[:, :, :3]
    over = np.clip(rgb - knee, 0, None)
    a[:, :, :3] = rgb - over * (1 - ratio)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), 'RGBA')

def _gait_profile(mats, min_len=40, leg_span_check=True, ar_lo=1.15, ar_hi=1.55, gap_tol=0):
    """walk/run 姿态选窗: 侧身档 ar∈[ar_lo,ar_hi](>1.55=趴卧段) + 腿质量span<0.9,
    取最长连续段(min_len)。gait_window 只按运动量选, 会选中正面intro(头动大)或趴卧段——
    golden walk 实测: intro ar 0.9-1.17 被 gait_window 选中→assets 全正面。
    ⚠️run 必须 leg_span_check=False: 奔跑四腿全伸展时 rowband 覆盖全宽 span≈1.0,
    span<0.9 会误杀全部侧身帧(run 实测仅选中20帧1周期→插值模糊+重复感)。
    柴犬等短腿品种侧身ar偏低(1.0-1.24)且span无判别间隙(0.75-0.97 vs 正面0.83-0.97)→
    walk 用 ar_lo=0.98 + leg_span_check=False (正面intro ar<=0.93 仍有间隙)。
    v85: ar_hi 1.55→1.85(walk大跨步伸展帧ar>1.55被误杀→侧视窗27帧→单周期14帧循环=重复感);
    gap_tol: 侧视窗允许≤gap_tol帧的ar下探(步态振荡收拢相位), 桥接成长窗=3周期长循环。"""
    ok = []
    for p in mats:
        a = np.array(Image.open(p).convert('RGBA'))[:, :, 3]
        ys, xs = np.nonzero(a > 30)
        if len(xs) == 0:
            ok.append(False); continue
        h = ys.max() - ys.min() + 1; w = xs.max() - xs.min() + 1
        ar = w / h
        if ar < ar_lo or ar > ar_hi:
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
    if gap_tol > 0:
        # v85: 桥接≤gap_tol帧的ar下探段(步态收拢相位), 合并成长侧视窗
        ok = list(ok)
        i = 0
        while i < len(ok):
            if not ok[i]:
                j = i
                while j < len(ok) and not ok[j]:
                    j += 1
                if j - i <= gap_tol and i > 0 and j < len(ok):
                    for k in range(i, j):
                        ok[k] = True
                i = j
            else:
                i += 1
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


def walk_width_norm(seq, target_area=189747):
    """v85 尺寸统一: v84大跨步trot成品面积中位231k vs 认可基线walk=189,747(+22%),
    而idle134k/run191k/sit174k均与各自基线一致 → 用户报"各动作大小不统一"唯walk超标。
    按bbox面积中位数等比缩放(宽高同比例,腿不变形), GROUND底部锚定。仅walk应用。"""
    areas = []
    for f in seq:
        a = np.array(f)[:, :, 3]
        areas.append(int((a > 40).sum()))   # v85: 像素面积(非bbox), 与基线度量一致
    if not areas:
        return seq
    med_a = float(np.median(areas))
    s = (target_area / med_a) ** 0.5
    if abs(s - 1.0) < 0.02:
        return seq
    out = []
    for f in seq:
        a = np.array(f)[:, :, 3]
        ys, xs = np.where(a > 40)
        if len(xs) == 0:
            out.append(f); continue
        y0, x0, y1, x1 = ys.min(), xs.min(), ys.max(), xs.max()
        c = f.crop((x0, y0, x1 + 1, y1 + 1))
        tw, th = max(1, int(round(c.width * s))), max(1, int(round(c.height * s)))
        c = c.resize((tw, th), Image.LANCZOS)
        canvas = Image.new('RGBA', f.size, (0, 0, 0, 0))
        canvas.paste(c, ((CANVAS - tw) // 2, GROUND - th), c.split()[3])
        out.append(canvas)
    print(f'  walk_size_norm: med_area={med_a:.0f}→{target_area} (s={s:.3f})', flush=True)
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

def drop_whitebg(fps):
    """v101: I2V首帧=白底身份图(roll/type_v100目检确认)——四角全白=白底帧剔除,
    否则运行时有1帧白底站立闪现。仅对青底新管线状态调用。"""
    out = []
    for fp in fps:
        im = Image.open(fp).convert('RGB')
        w, h = im.size
        px = [im.getpixel((2, 2)), im.getpixel((w - 3, 2)),
              im.getpixel((2, h - 3)), im.getpixel((w - 3, h - 3))]
        if all(min(p) > 225 for p in px):
            print(f'  [drop whitebg] {os.path.basename(fp)}', flush=True)
            continue
        out.append(fp)
    return out

def process_state(name):
    print(f'== {name} ==', flush=True)
    fps = extract(name)
    if not fps:
        print(f'  SKIP: no mp4', flush=True); return
    if name in ('roll_legacy_bluebg', 'type_legacy_bluebg'):
        # v-samoyed2: 新批次全部白底视频——drop_whitebg会删光所有帧, 停用。
        fps = drop_whitebg(fps)
    mats = cutout_frames(fps, name)
    # ═══ v110: 7缺陷修复分支 ═══
    # v110b修正: stabilize2d先跑(内部统一画布→同尺寸存盘, 幂等), 否则抠帧尺寸
    # 不一时后续calmest/beg_trim的mask异或会崩溃(832,1602 vs 832,1668)。
    if name not in ('walk', 'run'):
        mats = stabilize2d_mats(mats)     # #1 全态2D高频抖动去除(walk/run步态自有treadmill)
    if name == 'kiss':
        mats = kiss_degray(mats)          # #5 走近凑脸段灰背景闪烁
    if name == 'type':
        mats = type_drop_ghost(mats)      # #6 开头ghost斑块帧弃掉
    if name == 'idle':
        s0, e0 = calmest_window(mats)     # #2 开场抖腿段弃掉
        mats = mats[s0:e0]
    if name == 'beg':
        _, e0 = beg_trim_tail(mats)       # #7 后段下半身截断弃尾
        mats = mats[:e0]
    if name not in ('walk', 'run'):
        mats = stabilize2d_mats(mats)     # #2二次(选窗子集): 幂等, 修正量≈0
    if name in ('sleep_legacy_filter', 'stretch_legacy_filter'):
        # v-samoyed2: 旧过滤(剔站立过渡帧)与"视频=动作"铁律冲突, 且过滤结果仅用于
        # assert(sel随后被stabilize覆盖=死代码门)。新视频站→躺过渡是认可内容, 全窗保留;
        # sleep的站→躺由引擎intro_frames播一次+躺卧段loop处理。
        pass
    else:
        if name in ('walk', 'run'):
            if name == 'walk':
                # v78: 新walk视频前段=正面intro(ar<0.90)，gait profile窗阈值0.98凑不够40帧
                # 会回退全段[motion-selected]=正面intro混入循环=loop起点跳变。
                # 头部连续正面帧裁除（遇侧视即停），尾部3/4收势不裁（gait seam自选）。
                # v81: AR阈值自适应——0.90/0.98是按旧视频侧视ar≈0.99标定的;
                # 新视频侧视ar仅0.70-0.89(幼犬tail-up紧凑体型)→旧阈值会裁掉整段。
                # 自适应: 全视频ar排序取上2/3分位段的p10减0.05作侧视下界,
                # 下夹0.60防异常。front-trim需连续3帧达标才停(防单帧尖峰早停)。
                _ars = []
                for m in mats:
                    a = np.array(Image.open(m).convert('RGBA'))[:, :, 3]
                    ys, xs = np.where(a > 30)
                    if len(xs):
                        _ars.append((xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1))
                if len(_ars) > 30:
                    _side = sorted(_ars)[int(len(_ars) * 2 / 3):]
                    # v82: 下限1.00(真侧视剪影AR>=1.05; 0.60下限曾放过斜侧视频=
                    # 用户报"斜侧身体不像走动")。视频无真侧视段时宁可回退短窗/重跑。
                    WALK_AR = max(1.00, float(np.quantile(_side, 0.10)) - 0.05)
                else:
                    WALK_AR = 1.05
                print(f'  v81 adaptive walk AR={WALK_AR:.2f} (side p10 of top-2/3)', flush=True)

                def _ar_of(p):
                    a = np.array(Image.open(p).convert('RGBA'))[:, :, 3]
                    ys, xs = np.where(a > 30)
                    if len(xs) == 0:
                        return 0.0
                    return (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1)

                _s = 0
                while _s < len(mats) - 24:
                    if all(_ar_of(mats[_s + k]) >= WALK_AR for k in range(3)):
                        break
                    _s += 1
                if _s > 0:
                    mats = mats[_s:]
                    print(f'  v78 walk front-trim: dropped {_s} front-facing intro frames', flush=True)
            _walk_lo = min(WALK_AR, 1.25) if name == 'walk' else 1.15  # v100: run分支WALK_AR未定义(UnboundLocalError)，else为死代码取默认1.15
            # v85: walk侧窗下界 min(adaptive,1.25)。自适应1.39误杀步态振荡收拢相位帧
            # (ar 1.26-1.38全是侧身)→最长段22<40→fallback motion窗27帧=14帧单周期循环=重复感。
            # 正面intro实测上限1.24, 1.25安全保留front-trim成果。
            pw = _gait_profile(mats, leg_span_check=False,
                               ar_lo=_walk_lo if name == 'walk' else 0.98,
                               ar_hi=1.85 if name == 'walk' else 1.55,
                               gap_tol=2 if name == 'walk' else 0) if name == 'walk' else \
                 _gait_profile(mats, leg_span_check=False, ar_lo=1.15, ar_hi=1.85, gap_tol=2)
            # v100: run移植v85 walk修复——默认ar_hi=1.55误杀奔跑伸展帧(实测ar 1.55-1.73)，
            # profile窗30<40→fallback motion窗12帧=单周期插值模糊+重复感；1.85+gap2→全段119帧。
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
            if name in ('type', 'kiss'):
                # v102: chroma保键盘后键盘触左右边=有意构图(宽键盘出屏), clean_window的
                # edge判据全拒(0/119)。全视频即敲键动作, 全窗; 白底帧已由drop_whitebg剔除。
                # v102 kiss: 走近+凑近舔镜头=主体必然触边, clean_window只选中段10帧坐姿段
                # (丢走近/舔镜头), 同type全窗。
                s, e = 0, len(mats)
                print(f'  {name} full-window (chroma: edge-touch by design) {e - s} frames', flush=True)
            else:
                # v-samoyed2: 用户铁律"宠物动作=源视频动作, 认可的是源视频"——
                # 旧 clean_window/profile_window/crouch-trim 选窗启发式会裁掉
                # 认可视频内容(idle丢51帧/sit丢54帧)。新批次视频经目检均为单一
                # 完整动作(含站立→动作自然过渡), 全窗保留; 尺寸一致性由
                # TARGET_H/sleep_scale 保证, 漂移由 treadmill 去除。
                s, e = 0, len(mats)
                print(f'  {name} full-window (user-approved video = action, no trim) {e - s} frames', flush=True)
            if name == 'dance_legacy_looppet':
                # v-samoyed2: dance已改ONESHOT全窗一次性(无loop=无混段根因),
                # 双腿门纯删站立过渡段=删认可内容, 停用。
                pass
            if name == 'idle_legacy_crouchtrim':
                # v-samoyed2: 全窗铁律; 新idle视频无趴卧段, crouch-trim停用。
                pass
        if e - s < 4:
            print('  TOO FEW, skip', flush=True); return
        # v110: kiss degray已前移到选窗前, 灰背景不再撑大union/干扰相位相关,
        # 恢复统一水平stabilize(旧skip分支v102已废)。
        sel = stabilize_h_mats(mats)[s:e]
    if name in ('walk', 'run'):
        sel = treadmill_mats(sel, name)   # v57: normalize前对齐→union-bbox收缩到狗本体→scale由target_h决定 (v58: 非破坏性)
    elif name == 'idle':
        # v-samoyed2: 新idle视频有慢速左漂(质心943→225≈260px), 直接loop=
        # 屏上每5s瞬移~180px。linear treadmill只去净位移, 微动/朝向/踏步振荡全保留。
        sel = treadmill_mats(sel, name)
    elif name == 'roll':
        # v76: roll滚动时左右非线性徘徊(质心p2p=784px)→union-bbox宽1436→宽度钳制
        # 压死scale→仅473/500。中值去趋势W=25分离徘徊(趋势)与滚动摆动(残差90px保留)
        # →union_w=656不受钳制→精确恢复500。v-samoyed2保留: 水平去趋势不删帧、
        # 站→躺过渡为垂直分量不受影响, 且消除loop首尾水平瞬移。
        sel = treadmill_mats(sel, name, mode='median', win=25)
    frames = normalize_frames(sel, TARGET_H.get(name))
    if not frames:
        print('  normalize failed', flush=True); return
    frames = refit_bounds(frames)      # 修 stabilize roll 漂移导致的边界截断（walk左/run右）
    if name == 'roll_legacy_graybg':
        # v-samoyed2: 新批次白底视频无发青, warm_balance会把roll单独调暖黄=与其他态色调不一致, 停用。
        frames = warm_balance_frames(frames)   # v107: 发青修复(白点增益→idle认可暖白)
        frames = roll_perframe_scale(frames)   # v101: 站/躺逐帧锚定对齐主体档
    if name == 'sleep':
        frames = sleep_scale_frames(frames)
    if name == 'beg_legacy_dedup':
        # v-samoyed2: ONESHOT全窗一次性=无ping-pong静止感根因, dedup纯删静止帧=节奏加速≠视频, 停用。
        pass
    if name in PINGPONG:
        seq = frames + frames[-2:0:-1]
    elif name in ONESHOT:
        seq = frames          # intro+loop 分段在引擎 ANIMS 的 intro_frames 处理
    if name in ('walk', 'run'):
        if name == 'walk' and len(frames) >= 40:
            # v82b: AI步态无严格周期(取证: lag-diff曲线无周期dip, find_gait_loop
            # T=43错检→44帧单周期循环太短+接缝跳=重复/顿挫感)。整窗长循环+
            # find_loop_pair最优wrap接缝(83f@42ms≈3.5s循环, 防重复原理同v75 3T但不依赖周期)。
            i, j, d = find_loop_pair(frames, min_span_frac=0.7)
            # v85: 旧0.33在66帧profile窗里选25帧短对=1s循环=重复感。0.7→loop≥46帧
            # (≈2s@42ms)接近整窗长循环, wrap接缝仍最优。
            seq = frames[i:j + 1]
            print(f'  walk long-loop pair ({i},{j}) seam={d:.1f} len={len(seq)}', flush=True)
            seq = detrend_seq(seq)
            print(f'  stride1 full-rate sample: {len(seq)} frames', flush=True)
        elif name == 'run':
            # v100: run移植walk v82b长循环——旧find_gait_loop T=35单周期36帧
            # resample 15(2.4:1抽帧)+0.81s短循环=用户报"卡/重复感"。长循环≥25帧原生@42ms。
            i, j, d = find_loop_pair(frames, min_span_frac=0.7)
            seq = frames[i:j + 1]
            print(f'  run long-loop pair ({i},{j}) seam={d:.1f} len={len(seq)}', flush=True)
            seq = detrend_seq(seq)
            print(f'  stride1 full-rate sample: {len(seq)} frames', flush=True)
        else:
            i, j = find_gait_loop(frames)
            T = j - i
            # v79: 门控用窗口长度而非gait起点i(find_walk_loop自扫最优起点w∈[0,n-3T]);
            # 旧条件i+3T<len会把"后段才稳定"的视频误退单周期(9帧循环=发颠)。
            if name == 'walk' and 3 * T + 1 <= len(frames):
                # v75: 3原生周期（v61认可版28帧=3周期@stride2；19帧2周期=用户报
                # "动画重复播放"根因：循环太短1.6s）。3周期≈2.8s循环，重复感减半。
                w, seam = find_walk_loop(frames, T, nperiods=3)
                seq = frames[w:w + 3 * T + 1]
                print(f'  gait seq: {len(seq)} frames = 3 native periods (T={T} start={w} seam={seam:.1f})', flush=True)
                seq = detrend_seq(seq)   # v60: 子窗口残留漂移二次去除(run已认可不动)
                # v82: stride1全帧(废v60d stride2)。用户报"滑行"根因: 隔帧抽样帧间
                # 相位推进过大/帧率不匹配=读作滑动而非流畅迈步。全帧@42ms原生步频。
                print(f'  stride1 full-rate sample: {len(seq)} frames (T={T})', flush=True)
            else:
                seq = frames[i:j + 1]
                if name == 'walk':
                    print(f'  stride1 full-rate sample: {len(seq)} frames (T={T})', flush=True)
                print(f'  gait seq: {len(seq)} frames = 1 native period (T={T})', flush=True)
    else:
        if name in PINGPONG or name in ONESHOT:
            # v-samoyed: ping-pong/oneshot seq 上面已组装(L1276/L1279), 禁被 find_loop_pair
            # 覆盖——萨摩耶idle微幅视频loop pair仅11帧resample 101=9倍重复帧=卡顿。
            # 同v100 roll/kiss死代码修复范式(彼时只修了roll/kiss, ping-pong/oneshot态漏修)。
            print(f'  {name}: keep {"ping-pong" if name in PINGPONG else "oneshot"} seq {len(seq)} frames', flush=True)
        elif name in ('roll', 'kiss'):
            # v88: 灰底重生成版=完整一次性动作(站→仰滚→翻回)。旧loop pair(52,92)
            # 只取41帧中段resample到121=3倍重复帧=卡顿+动作放慢3倍。全窗口
            # 118帧@原生步幅→resample 121≈1:1, 与引擎121@42ms one-shot设计匹配。
            # v100: kiss同roll——1043行ONESHOT分支的seq被本else分支loop pair覆盖(死代码bug)，
            # kiss 42帧resample 121=3倍重复帧，一次性动作必须全窗口原生帧。
            seq = frames
            print(f'  roll full-window oneshot: {len(seq)} native frames', flush=True)
        else:
            # v100: type默认0.33选出24帧短周期, resample 57=2.4x慢动作(违反v53原生速度铁律)。
            # 0.7长循环+下方跳过resample=原生帧@42ms≈24fps原生速度。
            if name == 'type':
                i, j, d = find_loop_pair(frames, min_span_frac=0.7)
                seq = frames[i:j + 1]
                print(f'  type long loop pair ({i},{j}) seam={d:.1f} native={len(seq)}', flush=True)
            else:
                i, j, d = find_loop_pair(frames)
                seq = frames[i:j + 1]
                print(f'  loop pair ({i},{j}) seam={d:.1f}', flush=True)
    if name in RT_FRAMES and name != 'type':
        seq = resample_seq(seq, RT_FRAMES[name])
    if name == 'walk':
        seq = walk_width_norm(seq)   # v85: 尺寸统一, 对齐基线candC宽度712
    for k, f in enumerate(seq):
        im = harden_alpha(f)
        if name == 'bath':
            im = harden_foam(im)
            im = soft_highlight(im)   # v110 #4: 泡沫硬化后白毛过曝(82% v>240)→knee压缩
        im.save(os.path.join(OUT_DIR, f'{name}_{k:02d}.png'))
    # v106: prune旧帧——帧数减少时残留幽灵帧(deploy误读/审计误报)
    for old in glob.glob(os.path.join(OUT_DIR, f'{name}_*.png')):
        try:
            idx = int(os.path.basename(old)[len(name) + 1:-4])
        except ValueError:
            continue
        if idx >= len(seq):
            os.remove(old)
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
