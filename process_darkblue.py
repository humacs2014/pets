# -*- coding: utf-8 -*-
"""
Process darkblue videos: extract frames -> BiRefNet soft alpha -> fg normalize -> bottom anchor -> webp

Pipeline strategy (post SAM2Matting evaluation):
- BiRefNet sigmoid soft alpha for ALL states (including eat/bath)
- Core entities (sigmoid > 0.7): hard alpha = 255 (must be opaque)
- Shadow/edge areas (0.01 < sigmoid <= 0.7): soft alpha = sigmoid * 255 (allow slight transparency)
- Background (sigmoid <= 0.01): alpha = 0

This replaces the previous SAM2 multi-object + BiRefNet hard alpha approach,
which produced visible holes in bowl interior walls due to hard-threshold
cutting of edge pixels that BiRefNet assigns low but non-zero confidence.

Usage: python process_darkblue.py [state1 state2 ...]
       python process_darkblue.py              # all darkblue videos
"""
import sys, os, subprocess, numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
VIDEOS_DIR = os.path.join(ROOT, 'videos')
ASSETS_DIR = os.path.join(ROOT, 'assets')
WORK_BASE = os.path.join(ROOT, '_darkblue_work')

TARGET_FG = 186000  # walk gold standard target fg pixel count

# Soft alpha thresholds
SIGMOID_CORE = 0.7    # above this: hard alpha=255
SIGMOID_FLOOR = 0.01  # below this: alpha=0 (background)
# Between FLOOR and CORE: soft alpha = sigmoid * 255

def extract_frames(video_path, out_dir, num_frames=121):
    """Extract raw frames from video using ffmpeg."""
    os.makedirs(out_dir, exist_ok=True)
    cmd = [
        'ffmpeg', '-y', '-i', video_path,
        '-vframes', str(num_frames),
        '-q:v', '2',
        os.path.join(out_dir, '%05d.png')
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    frames = sorted([f for f in os.listdir(out_dir) if f.endswith('.png')])
    print(f'  Extracted {len(frames)} frames from {os.path.basename(video_path)}')
    return len(frames)

def birefnet_soft_alpha(frames_dir, sigmoid_dir, work_dir):
    """BiRefNet soft alpha: save sigmoid maps (0.0-1.0) as uint16 PNG.
    
    Each pixel stores sigmoid * 65535 to preserve precision.
    Later stages interpret these as soft alpha values.
    """
    import torch
    from transformers import AutoModelForImageSegmentation
    from torchvision import transforms
    
    local_path = os.path.expanduser(
        '~/.cache/huggingface/hub/models--zhengpeng7--BiRefNet/snapshots/'
        'e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4'
    )
    if os.path.isdir(local_path):
        model = AutoModelForImageSegmentation.from_pretrained(
            local_path, trust_remote_code=True, local_files_only=True
        ).cuda().eval()
    else:
        model = AutoModelForImageSegmentation.from_pretrained(
            'ZhengPeng7/BiRefNet-matting', trust_remote_code=True
        ).cuda().eval()
    
    tf = transforms.Compose([
        transforms.Resize((1024, 1024)),
        transforms.ToTensor(),
        transforms.Normalize([0.485,0.456,0.406],[0.229,0.224,0.225]),
    ])
    
    os.makedirs(sigmoid_dir, exist_ok=True)
    frames = sorted([f for f in os.listdir(frames_dir) if f.endswith('.png')])
    
    for i, fn in enumerate(frames):
        img = Image.open(os.path.join(frames_dir, fn)).convert('RGB')
        inp = tf(img).unsqueeze(0).cuda()
        with torch.no_grad():
            sigmoid = model(inp)[-1].sigmoid().squeeze().cpu().numpy()
        
        # Save sigmoid as uint16 PNG (preserves full precision)
        sigmoid_uint16 = (sigmoid * 65535).astype(np.uint16)
        sigmoid_img = Image.fromarray(sigmoid_uint16)
        # Resize to original frame size
        sigmoid_img = sigmoid_img.resize(img.size, Image.BILINEAR)
        # Save as 16-bit PNG
        sigmoid_img.save(os.path.join(sigmoid_dir, fn))
        
        if i % 20 == 0:
            print(f'    BiRefNet: {i}/{len(frames)}', flush=True)
    
    # Free GPU
    del model
    torch.cuda.empty_cache()
    
    print(f'  BiRefNet soft alpha: {len(frames)} sigmoid maps done')
    return len(frames)

def fg_normalize_and_anchor(frames_dir, sigmoid_dir, out_dir, target_fg=TARGET_FG, state_name=None):
    """Apply soft alpha + fg normalization + bottom anchor to each frame.
    
    Soft alpha logic:
    - sigmoid > SIGMOID_CORE (0.7): alpha = 255 (core entities, must be opaque)
    - SIGMOID_FLOOR (0.01) < sigmoid <= SIGMOID_CORE: alpha = sigmoid * 255 (soft edge/shadow)
    - sigmoid <= SIGMOID_FLOOR: alpha = 0 (background)
    
    fg normalization counts pixels with alpha > 0 (including soft alpha).
    """
    os.makedirs(out_dir, exist_ok=True)
    frames = sorted([f for f in os.listdir(frames_dir) if f.endswith('.png')])
    
    # Load all frames + sigmoid maps, compute alpha and fg counts
    fgs = []
    for fn in frames:
        img = np.array(Image.open(os.path.join(frames_dir, fn)).convert('RGB'))
        sig_path = os.path.join(sigmoid_dir, fn)
        sig_img = Image.open(sig_path)
        # Read as uint16, convert to float sigmoid [0,1]
        sig_np = np.array(sig_img).astype(np.float64) / 65535.0
        h, w = img.shape[:2]
        if sig_np.shape != (h, w):
            sig_np = np.array(sig_img.resize((w, h), Image.BILINEAR)).astype(np.float64) / 65535.0
        
        # Compute soft alpha
        alpha = np.zeros((h, w), dtype=np.uint8)
        core = sig_np > SIGMOID_CORE
        alpha[core] = 255
        soft = (~core) & (sig_np > SIGMOID_FLOOR)
        alpha[soft] = np.clip(sig_np[soft] * 255, 1, 254).astype(np.uint8)
        
        # v107: type硬alpha+柔和边缘方案
        # 根治光晕：源alpha用硬二值（BiRefNet>0.5→255，色差法→255），杜绝帧间半透明波动
        # 柔和边缘：resize前把alpha=0区域RGB填充为cream，LANCZOS插值产生柔和半透明
        #   但半透明像素RGB=cream+前景混合→不含darkblue→无光晕
        # resize后再做最终defringe清理残留darkblue半透明
        if state_name == 'type':
            bg_ref = np.array([18.0, 37.0, 69.0])
            cream_ref = np.array([200.0, 180.0, 150.0])
            # Step 1: BiRefNet硬阈值
            alpha = np.zeros((h, w), dtype=np.uint8)
            alpha[sig_np > 0.5] = 255
            # Step 2: 色差法补充键盘底座（硬阈值）
            color_dist = np.sqrt(((img.astype(np.float64) - bg_ref) ** 2).sum(axis=2))
            chroma_mask = color_dist > 20
            biref_zero = alpha == 0
            alpha[biref_zero & chroma_mask] = 255
            # Step 3: alpha=0区域RGB填充cream，使LANCZOS插值不含darkblue
            img_mod = img.copy()
            img_mod[alpha == 0] = cream_ref.astype(np.uint8)
            # Step 4: alpha=255但RGB≈darkblue的BiRefNet误判像素也改为cream
            # （这些像素虽然不可见，但resize时LANCZOS会用它们插值产生边缘半透明）
            fg_dark = (alpha == 255)
            fg_rgb = img_mod[fg_dark].astype(np.float64)
            if fg_dark.any() and len(fg_rgb) > 0:
                fg_dist = np.sqrt(((fg_rgb - bg_ref) ** 2).sum(axis=1))
                very_dark = fg_dist < 50
                if very_dark.any():
                    dark_full = np.zeros((h, w), dtype=bool)
                    dark_full[fg_dark] = very_dark
                    img_mod[dark_full] = cream_ref.astype(np.uint8)
            img = img_mod
        
        fg = (alpha > 0).sum()
        fgs.append((fn, img, alpha, fg))
    
    # v100-fix: Use per-state median_fg as target (not global TARGET_FG=186K).
    # States like type (fg≈130K) were over-scaled to 186K, causing content to exceed frame bounds.
    # pet is special: hand entering/leaving causes fg jumps → per-frame scale → visual sliding,
    # so pet uses a single fixed scale (all frames scaled by same ratio = median_fg/median_fg = 1.0).
    median_fg = int(np.median([fg for _, _, _, fg in fgs]))
    if state_name in ('pet',):
        target_fg = median_fg  # fixed_scale=1.0, no per-frame variation
    elif target_fg == TARGET_FG:
        target_fg = median_fg  # per-state normalization, no over-scaling
    
    # Find global bottom anchor Y (using alpha > 128 for reliable bottom detection)
    # For interaction states (pet/kiss/type) where external elements (hand) enter/leave,
    # fg area changes dramatically mid-action → per-frame scale causes visual "sliding".
    # Fix: compute a single fixed scale for the entire action (based on first frame or median).
    global_bottom_ys = []
    
    if state_name in ('pet',):
        # pet: hand enters from above, fg area jumps mid-action
        # Fixed scale prevents visual "sliding" when hand enters/leaves
        # v100: fixed_scale=1.0 (target_fg=median_fg), frames keep original size
        fixed_scale = np.sqrt(target_fg / median_fg)
        print(f'  Interaction state: fixed_scale={fixed_scale:.4f} (median_fg={median_fg}, target_fg={target_fg})')
    
    for fn, img, alpha, fg in fgs:
        ys = np.where(alpha > 128)[0]
        if len(ys) > 0:
            global_bottom_ys.append(ys.max())
    anchor_y = int(np.median(global_bottom_ys)) if global_bottom_ys else 0
    h0, w0 = fgs[0][1].shape[:2]
    
    for fn, img, alpha, fg in fgs:
        if fg < 1000:
            scale = 1.0
        elif state_name in ('pet',):
            # Fixed scale for pet — hand entering/leaving causes fg jumps
            scale = fixed_scale
        else:
            scale = np.sqrt(target_fg / fg)
        
        h, w = img.shape[:2]
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        
        # v107: type用LANCZOS产生柔和边缘（alpha=0区域已填充cream，插值不含darkblue）
        img_pil = Image.fromarray(img).resize((new_w, new_h), Image.LANCZOS)
        alpha_pil = Image.fromarray(alpha).resize((new_w, new_h), Image.BILINEAR)
        
        img_np = np.array(img_pil)
        alpha_np = np.array(alpha_pil)
        
        # v107: type resize后最终defringe——清理残留darkblue半透明
        if state_name == 'type':
            bg_ref2 = np.array([18.0, 37.0, 69.0])
            cream2 = np.array([200.0, 180.0, 150.0])
            semi = (alpha_np > 0) & (alpha_np < 255)
            if semi.any():
                semi_rgb = img_np[semi].astype(np.float64)
                dist2 = np.sqrt(((semi_rgb - bg_ref2) ** 2).sum(axis=1))
                dark_semi = dist2 < 50
                if dark_semi.any():
                    # darkblue半透明→替换为cream
                    dark_full2 = np.zeros(alpha_np.shape, dtype=bool)
                    dark_full2[semi] = dark_semi
                    img_np[dark_full2] = cream2.astype(np.uint8)
            # 也清理alpha=255中RGB≈darkblue的像素（BiRefNet误判）
            core = alpha_np == 255
            if core.any():
                core_rgb = img_np[core].astype(np.float64)
                core_dist = np.sqrt(((core_rgb - bg_ref2) ** 2).sum(axis=1))
                dark_core = core_dist < 50
                if dark_core.any():
                    dark_core_full = np.zeros(alpha_np.shape, dtype=bool)
                    dark_core_full[core] = dark_core
                    img_np[dark_core_full] = cream2.astype(np.uint8)
            # alpha极低噪点清零（不影响视觉但减少帧间波动）
            alpha_np[alpha_np < 5] = 0
            # core恢复
            alpha_np[alpha_np > 250] = 255
        else:
            # After resize, re-enforce soft alpha logic (resize interpolation can blur values)
            # Values > 250 that should be 255 (core) get rounded back
            alpha_np[alpha_np > 250] = 255
            # Remove near-zero speckle noise from resize interpolation
            alpha_np[alpha_np < 3] = 0
        
        # Remove isolated tiny speckle components (keep only main subject)
        from scipy import ndimage
        mask_bool = alpha_np > 0
        labeled, num_features = ndimage.label(mask_bool)
        if num_features > 0:
            sizes = ndimage.sum(mask_bool, labeled, range(1, num_features + 1))
            keep = set(i + 1 for i, s in enumerate(sizes) if s >= 100)
            mask_bool = np.isin(labeled, list(keep)) if keep else np.zeros_like(mask_bool)
        # Zero out alpha for removed speckles
        alpha_np[~mask_bool] = 0
        
        # Build RGBA
        rgba = np.zeros((new_h, new_w, 4), dtype=np.uint8)
        rgba[:,:,:3] = img_np
        rgba[:,:,3] = alpha_np
        rgba_img = Image.fromarray(rgba)
        
        # Find bottom of subject in scaled frame (use alpha > 128 for reliable detection)
        ys = np.where(alpha_np > 128)[0]
        if len(ys) > 0:
            scaled_bottom = ys.max()
        else:
            scaled_bottom = new_h - 1
        
        # Paste onto canvas with bottom anchored at anchor_y
        canvas = np.zeros((h0, w0, 4), dtype=np.uint8)
        
        paste_y = anchor_y - scaled_bottom - 1
        if paste_y < 0:
            shrink = new_h / (new_h + abs(paste_y))
            new_h2 = max(1, int(new_h * shrink))
            new_w2 = max(1, int(new_w * shrink))
            rgba_img = rgba_img.resize((new_w2, new_h2), Image.LANCZOS)
            # v107: type二次resize后defringe清理darkblue半透明
            if state_name == 'type':
                arr2 = np.array(rgba_img)
                bg3 = np.array([18.0, 37.0, 69.0])
                cream3 = np.array([200.0, 180.0, 150.0])
                a2 = arr2[:,:,3]
                semi2 = (a2 > 0) & (a2 < 255)
                if semi2.any():
                    rgb2 = arr2[:,:,:3][semi2].astype(np.float64)
                    d3 = np.sqrt(((rgb2 - bg3)**2).sum(1))
                    dk3 = d3 < 50
                    if dk3.any():
                        dk3_full = np.zeros(a2.shape, dtype=bool)
                        dk3_full[semi2] = dk3
                        arr2[:,:,:3][dk3_full] = cream3.astype(np.uint8)
                a2[a2 < 5] = 0
                a2[a2 > 250] = 255
                rgba_img = Image.fromarray(arr2)
            mask_np2 = np.array(rgba_img)[:,:,3]
            ys2 = np.where(mask_np2 > 128)[0]
            scaled_bottom = ys2.max() if len(ys2) else new_h2 - 1
            paste_y = anchor_y - scaled_bottom - 1
            if paste_y < 0:
                paste_y = 0
            new_w, new_h = new_w2, new_h2
        paste_x = (w0 - new_w) // 2
        
        temp = Image.new('RGBA', (w0, h0), (0, 0, 0, 0))
        temp.paste(rgba_img, (paste_x, paste_y))
        temp.save(os.path.join(out_dir, fn))
    
    # Report stats
    core_count = sum(1 for _, _, a, _ in fgs for _ in [] )  # placeholder
    print(f'  soft alpha + fg normalize+anchor: {len(frames)} frames, target_fg={target_fg}, anchor_y={anchor_y}')
    print(f'  thresholds: core>{SIGMOID_CORE}→255, floor>{SIGMOID_FLOOR}→soft, else→0')
    return len(frames)

def to_webp(frames_dir, state_name, num_frames=None):
    """Convert processed RGBA PNGs to webp assets."""
    import time as _time
    frames = sorted([f for f in os.listdir(frames_dir) if f.endswith('.png')])
    if num_frames:
        frames = frames[:num_frames]
    
    os.makedirs(ASSETS_DIR, exist_ok=True)
    for fn in frames:
        idx = int(fn.replace('.png', '')) - 1  # 1-indexed filenames -> 0-indexed assets
        img = Image.open(os.path.join(frames_dir, fn))
        out_path = os.path.join(ASSETS_DIR, f'{state_name}_{idx:03d}.webp')
        for attempt in range(5):
            try:
                img.save(out_path, 'WEBP', lossless=True)
                break
            except OSError:
                _time.sleep(0.5 * (attempt + 1))
        else:
            print(f'  WARN: failed to save {out_path} after 5 retries')
    
    print(f'  Converted {len(frames)} {state_name} frames -> assets/')
    return len(frames)

def process_state(state_name, num_frames=None):
    """Full pipeline for one state."""
    # Prefer latest video version
    for ver in ['v7', 'v6', 'v5', 'v4', 'v3', 'v2']:
        v_path = os.path.join(VIDEOS_DIR, f'{state_name}_darkblue_{ver}.mp4')
        if os.path.exists(v_path):
            video_path = v_path
            print(f'  Using {ver} video')
            break
    else:
        v1_path = os.path.join(VIDEOS_DIR, f'{state_name}_darkblue.mp4')
        video_path = v1_path
    if not os.path.exists(video_path):
        print(f'[SKIP] {state_name}: no darkblue video found')
        return False
    
    work_dir = os.path.join(WORK_BASE, state_name)
    frames_dir = os.path.join(work_dir, 'frames_raw')
    sigmoid_dir = os.path.join(work_dir, 'birefnet_sigmoid')
    final_dir = os.path.join(work_dir, 'frames_final')
    
    # Step 1: Extract frames (skip if already done)
    if not os.path.exists(os.path.join(frames_dir, '00001.png')):
        n = extract_frames(video_path, frames_dir)
    
    # Step 2: BiRefNet soft alpha for ALL states
    if not os.path.exists(os.path.join(sigmoid_dir, '00001.png')):
        birefnet_soft_alpha(frames_dir, sigmoid_dir, work_dir)
    
    # Step 3: Soft alpha + fg normalize + bottom anchor
    fg_normalize_and_anchor(frames_dir, sigmoid_dir, final_dir, state_name=state_name)
    
    # Step 4: Convert to webp assets
    to_webp(final_dir, state_name, num_frames=num_frames)
    
    return True

if __name__ == '__main__':
    states = sys.argv[1:] if len(sys.argv) > 1 else [
        f.replace('_darkblue.mp4', '') 
        for f in os.listdir(VIDEOS_DIR) 
        if f.endswith('_darkblue.mp4')
    ]
    
    print(f'Processing {len(states)} states: {states}')
    done = 0
    for state in states:
        print(f'\n=== {state} ===')
        if process_state(state):
            done += 1
    print(f'\nDone: {done}/{len(states)} states processed')
