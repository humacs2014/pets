# -*- coding: utf-8 -*-
"""
Process darkblue videos: extract frames -> BiRefNet soft alpha -> fg normalize -> bottom anchor -> webp

Pipeline strategy:
- BiRefNet sigmoid soft alpha for ALL states
- DARKBLUE BORDER REMOVAL (fundamental fix — no color-based detection of darkblue pixels):
  After resize, ERODE the alpha mask by 3px. This physically removes the outermost
  layer where darkblue background residue lives, regardless of its RGB values.
  Then apply Gaussian blur (1.5px) to restore soft anti-aliased edges.
  The new soft edge is a blend of foreground + cream (from cream-fill), never darkblue.
  
  Safety: 3px erosion at 1088x832 = 0.36% of frame height — completely invisible.
  Dog interior features (eyes, nose, fur) are deep inside the mask, never touched.
  No RGB modification anywhere — zero risk of white/golden patches.

Usage: python process_darkblue.py [state1 state2 ...]
       python process_darkblue.py              # all darkblue videos
"""
import sys, os, subprocess, numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
VIDEOS_DIR = os.path.join(ROOT, 'videos')
ASSETS_DIR = os.path.join(ROOT, 'assets')
WORK_BASE = os.path.join(ROOT, '_darkblue_work')

TARGET_FG = 186000  # legacy default (not used when UNIFIED_FG is set)
# v111: unified foreground target — all states normalized to same dog size
# idle median_fg ≈ 220K; use this as the standard so all states look consistent
UNIFIED_FG = 220000

# Soft alpha thresholds
SIGMOID_CORE = 0.7
SIGMOID_FLOOR = 0.01

# Darkblue background reference
BG_RGB = np.array([18.0, 37.0, 69.0])
# Cream fill for alpha=0 regions (prevents LANCZOS darkblue interpolation)
CREAM = np.array([200.0, 180.0, 150.0])

# Erosion radius for darkblue border removal
# v110: 4px erosion at 1088x832 = 0.48% of frame height — removes more darkblue residue
# that becomes visible black edges on macOS (Retina renders alpha 1-19 as ~0 RGB)
ERODE_RADIUS = 4
# Gaussian blur sigma for soft edge restoration after erosion
EDGE_BLUR_SIGMA = 1.8


def extract_frames(video_path, out_dir, num_frames=121):
    """v110: Highest quality extraction — q:v 1 (best PNG), no scaling, native 1080P"""
    os.makedirs(out_dir, exist_ok=True)
    cmd = [
        'ffmpeg', '-y', '-i', video_path,
        '-vframes', str(num_frames),
        '-q:v', '1',   # v110: highest PNG quality (was 2)
        os.path.join(out_dir, '%05d.png')
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    frames = sorted([f for f in os.listdir(out_dir) if f.endswith('.png')])
    print(f'  Extracted {len(frames)} frames from {os.path.basename(video_path)}')
    return len(frames)


def birefnet_soft_alpha(frames_dir, sigmoid_dir, work_dir):
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
        
        sigmoid_uint16 = (sigmoid * 65535).astype(np.uint16)
        sigmoid_img = Image.fromarray(sigmoid_uint16)
        sigmoid_img = sigmoid_img.resize(img.size, Image.BILINEAR)
        sigmoid_img.save(os.path.join(sigmoid_dir, fn))
        
        if i % 20 == 0:
            print(f'    BiRefNet: {i}/{len(frames)}', flush=True)
    
    del model
    torch.cuda.empty_cache()
    print(f'  BiRefNet soft alpha: {len(frames)} sigmoid maps done')
    return len(frames)


def erode_alpha(alpha_np, radius, protect_mask=None):
    """Morphological erosion of alpha mask. Removes outermost 'radius' pixels.
    If protect_mask is provided, only erode the boundary of protect_mask
    (not interior holes created by darkblue removal)."""
    from scipy import ndimage
    if protect_mask is not None:
        # Only erode the outer boundary of the original foreground
        eroded = ndimage.binary_erosion(protect_mask, iterations=radius)
        outer_strip = protect_mask & ~eroded  # 2px strip at original outer edge
        # Zero alpha only in the outer strip
        result = alpha_np.copy()
        result[outer_strip] = 0
        return result
    else:
        mask = alpha_np > 0
        eroded = ndimage.binary_erosion(mask, iterations=radius)
        return np.where(eroded, alpha_np, 0).astype(np.uint8)


def blur_alpha(alpha_np, sigma):
    """Gaussian blur on alpha to create soft anti-aliased edges."""
    from scipy import ndimage
    blurred = ndimage.gaussian_filter(alpha_np.astype(np.float64), sigma=sigma)
    return np.clip(blurred, 0, 255).astype(np.uint8)


def fg_normalize_and_anchor(frames_dir, sigmoid_dir, out_dir, target_fg=TARGET_FG, state_name=None):
    os.makedirs(out_dir, exist_ok=True)
    frames = sorted([f for f in os.listdir(frames_dir) if f.endswith('.png')])
    
    fgs = []
    for fn in frames:
        img = np.array(Image.open(os.path.join(frames_dir, fn)).convert('RGB'))
        sig_path = os.path.join(sigmoid_dir, fn)
        sig_img = Image.open(sig_path)
        sig_np = np.array(sig_img).astype(np.float64) / 65535.0
        h, w = img.shape[:2]
        if sig_np.shape != (h, w):
            sig_np = np.array(sig_img.resize((w, h), Image.BILINEAR)).astype(np.float64) / 65535.0
        
        # Compute soft alpha from BiRefNet sigmoid (NO modification to sigmoid or RGB)
        # v111: sleep uses higher core threshold to stabilize flickering edges
        core_thresh = 0.85 if state_name == 'sleep' else SIGMOID_CORE
        alpha = np.zeros((h, w), dtype=np.uint8)
        core = sig_np > core_thresh
        alpha[core] = 255
        soft = (~core) & (sig_np > SIGMOID_FLOOR)
        alpha[soft] = np.clip(sig_np[soft] * 255, 1, 254).astype(np.uint8)
        
        # type特殊处理：色差法补充键盘底座（仅修改alpha，不修改RGB）
        if state_name == 'type':
            bg_ref = np.array([18.0, 37.0, 69.0])
            alpha = np.zeros((h, w), dtype=np.uint8)
            alpha[sig_np > 0.5] = 255
            color_dist = np.sqrt(((img.astype(np.float64) - bg_ref) ** 2).sum(axis=2))
            chroma_mask = color_dist > 20
            biref_zero = alpha == 0
            alpha[biref_zero & chroma_mask] = 255
        # eat特殊处理：色差法补充红色食盆+狗粮（BiRefNet把它们当背景抠掉了）
        elif state_name == 'eat':
            bg_ref = np.array([18.0, 37.0, 69.0])
            # Keep BiRefNet core (sigmoid > 0.5) as-is
            alpha = np.zeros((h, w), dtype=np.uint8)
            alpha[sig_np > 0.5] = 255
            # Add back pixels far from darkblue bg (food bowl + kibble = red/brown, far from blue)
            color_dist = np.sqrt(((img.astype(np.float64) - bg_ref) ** 2).sum(axis=2))
            chroma_mask = color_dist > 20
            biref_zero = alpha == 0
            alpha[biref_zero & chroma_mask] = 255
        
        fg = (alpha > 0).sum()
        fgs.append((fn, img, alpha, fg, sig_np))
    
    median_fg = int(np.median([fg for _, _, _, fg, _ in fgs]))
    # v111: ALL states use UNIFIED_FG as target — ensures consistent dog size across all states
    # Old v110 used target_fg=median_fg → fixed_scale=1.0 → sleep/run/roll 3× bigger than idle
    target_fg = UNIFIED_FG
    fixed_scale = np.sqrt(target_fg / median_fg)
    
    global_bottom_ys = []
    if state_name in ('pet', 'kiss', 'type'):
        print(f'  Interaction state: fixed_scale={fixed_scale:.4f} (median_fg={median_fg}, target_fg={target_fg})')
    
    for fn, img, alpha, fg, sig_np_orig in fgs:
        ys = np.where(alpha > 128)[0]
        if len(ys) > 0:
            global_bottom_ys.append(ys.max())
    anchor_y = int(np.median(global_bottom_ys)) if global_bottom_ys else 0
    h0, w0 = fgs[0][1].shape[:2]
    
    for fn, img, alpha, fg, sig_np_orig in fgs:
        if fg < 1000:
            scale = 1.0
        else:
            # v110: ALL states use fixed_scale — no per-frame size variation (eliminates jitter)
            scale = fixed_scale
        
        h, w = img.shape[:2]
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        
        # Cream fill alpha=0 regions before LANCZOS resize
        # Prevents LANCZOS from interpolating darkblue bg into edge semi-transparent pixels
        img_for_resize = img.copy()
        img_for_resize[alpha == 0] = CREAM.astype(np.uint8)
        
        img_pil = Image.fromarray(img_for_resize).resize((new_w, new_h), Image.LANCZOS)
        alpha_pil = Image.fromarray(alpha).resize((new_w, new_h), Image.BILINEAR)
        sig_pil = Image.fromarray((sig_np_orig * 65535).astype(np.uint16), mode='I;16').resize((new_w, new_h), Image.BILINEAR)
        
        img_np = np.array(img_pil)
        alpha_np = np.array(alpha_pil)
        sigmoid_np = np.array(sig_pil).astype(np.float64) / 65535.0
        
        if state_name == 'type':
            # type: same erode+blur approach as other states (no RGB modification)
            # Save original foreground mask BEFORE darkblue removal for protected erode
            orig_fg_mask = alpha_np > 128
            fg_mask = alpha_np > 0
            if fg_mask.any():
                fg_rgb = img_np[fg_mask].astype(np.float64)
                dist_db = np.sqrt(((fg_rgb - BG_RGB) ** 2).sum(axis=1))
                b_minus_g = fg_rgb[:, 2] - fg_rgb[:, 1]
                is_darkblue = (dist_db < 60) & (b_minus_g > 3)
                # Exclude BiRefNet core foreground (sigmoid > 0.5)
                fg_sigmoid = sigmoid_np[fg_mask]
                is_darkblue = is_darkblue & (fg_sigmoid <= 0.5)
                if is_darkblue.any():
                    dark_full = np.zeros(alpha_np.shape, dtype=bool)
                    dark_full[fg_mask] = is_darkblue
                    alpha_np[dark_full] = 0
            alpha_np = erode_alpha(alpha_np, ERODE_RADIUS, protect_mask=orig_fg_mask)
            alpha_np = blur_alpha(alpha_np, EDGE_BLUR_SIGMA)
            alpha_np[alpha_np > 250] = 255
            alpha_np[alpha_np < 10] = 0
        else:
            # ============================================================
            # FUNDAMENTAL FIX: Remove darkblue border (two-pronged approach)
            #
            # Prong 1 — COLOR-BASED ALPHA ZEROING (catches large darkblue patches):
            #   BiRefNet misclassifies large darkblue background areas as foreground.
            #   These pixels retain their darkblue RGB after resize (B>G, blue tint).
            #   Dog dark features always have B<=G (warm tone: black eyes, brown nose).
            #   So: alpha>0 AND dist<60 AND B>G+3 → zero alpha. Zero false positives.
            #
            # Prong 2 — PROTECTED ERODE + BLUR (catches thin darkblue borders):
            #   At the subject edge, LANCZOS mixes darkblue with cream → B>G may fail.
            #   2px erosion removes this thin border. Then 1.5px blur restores soft edge.
            #   IMPORTANT: erode only the OUTER boundary of original BiRefNet foreground,
            #   not interior holes created by darkblue removal (e.g. mouth interior).
            #   Otherwise, erode eats into mouth/tongue → visible parts disappear
            #   after premultiplied alpha compositing (alpha<20 → RGB→0).
            #
            # NEVER modify img_np RGB — prevents white/golden patches.
            # ============================================================
            
            # Save original foreground mask BEFORE darkblue removal for protected erode
            orig_fg_mask = alpha_np > 128
            
            # Prong 1: Color-based alpha zeroing
            # IMPORTANT: only zero darkblue pixels where BiRefNet is NOT confident (sigmoid <= 0.5)
            # BiRefNet core foreground (sigmoid>0.5) at the subject edge may have B>G
            # due to LANCZOS mixing darkblue background with dark fur — these are real
            # dog features (lower jaw, mouth interior), NOT darkblue background.
            fg_mask = alpha_np > 0
            if fg_mask.any():
                fg_rgb = img_np[fg_mask].astype(np.float64)
                dist_db = np.sqrt(((fg_rgb - BG_RGB) ** 2).sum(axis=1))
                b_minus_g = fg_rgb[:, 2] - fg_rgb[:, 1]
                is_darkblue = (dist_db < 60) & (b_minus_g > 3)
                # Exclude BiRefNet core foreground (sigmoid > 0.5)
                fg_sigmoid = sigmoid_np[fg_mask]
                is_darkblue = is_darkblue & (fg_sigmoid <= 0.5)
                if is_darkblue.any():
                    dark_full = np.zeros(alpha_np.shape, dtype=bool)
                    dark_full[fg_mask] = is_darkblue
                    alpha_np[dark_full] = 0
            
            # Prong 2: Protected erode + blur for thin border cleanup
            # v110: Use ERODE_RADIUS (4) instead of hardcoded 2 for better darkblue border removal
            alpha_np = erode_alpha(alpha_np, ERODE_RADIUS, protect_mask=orig_fg_mask)
            alpha_np = blur_alpha(alpha_np, EDGE_BLUR_SIGMA)
            
            # Core restore (blur may soften alpha=255 pixels)
            alpha_np[alpha_np > 250] = 255
            # v110: Remove low-alpha fringe that becomes visible black edges on macOS
            # Qt premultiplied alpha: alpha 1-19 → RGB rendered as ≈0 (black fringe)
            alpha_np[alpha_np < 10] = 0
        
        # Remove isolated tiny speckle components
        from scipy import ndimage
        mask_bool = alpha_np > 0
        labeled, num_features = ndimage.label(mask_bool)
        if num_features > 0:
            sizes = ndimage.sum(mask_bool, labeled, range(1, num_features + 1))
            keep = set(i + 1 for i, s in enumerate(sizes) if s >= 100)
            mask_bool = np.isin(labeled, list(keep)) if keep else np.zeros_like(mask_bool)
        alpha_np[~mask_bool] = 0
        
        # Build RGBA (NEVER modify img_np — no white/golden patches)
        rgba = np.zeros((new_h, new_w, 4), dtype=np.uint8)
        rgba[:,:,:3] = img_np
        rgba[:,:,3] = alpha_np
        rgba_img = Image.fromarray(rgba)
        
        # Find bottom of subject
        ys = np.where(alpha_np > 128)[0]
        if len(ys) > 0:
            scaled_bottom = ys.max()
        else:
            scaled_bottom = new_h - 1
        
        canvas = np.zeros((h0, w0, 4), dtype=np.uint8)
        
        paste_y = anchor_y - scaled_bottom - 1
        if paste_y < 0:
            shrink = new_h / (new_h + abs(paste_y))
            new_h2 = max(1, int(new_h * shrink))
            new_w2 = max(1, int(new_w * shrink))
            rgba_img = rgba_img.resize((new_w2, new_h2), Image.LANCZOS)
            if state_name == 'type':
                # type secondary resize: same color+erode approach (no RGB modification)
                arr2 = np.array(rgba_img)
                a2 = arr2[:,:,3]
                fg2 = a2 > 0
                if fg2.any():
                    rgb2 = arr2[:,:,:3][fg2].astype(np.float64)
                    d3 = np.sqrt(((rgb2 - BG_RGB)**2).sum(1))
                    bmg3 = rgb2[:,2] - rgb2[:,1]
                    dk3 = (d3 < 60) & (bmg3 > 3)
                    if dk3.any():
                        dk3_full = np.zeros(a2.shape, dtype=bool)
                        dk3_full[fg2] = dk3
                        a2[dk3_full] = 0
                a2 = erode_alpha(a2, ERODE_RADIUS)
                a2 = blur_alpha(a2, EDGE_BLUR_SIGMA)
                a2[a2 > 250] = 255
                a2[a2 < 10] = 0
                arr2[:,:,3] = a2
                rgba_img = Image.fromarray(arr2)
            mask_np2 = np.array(rgba_img)[:,:,3]
            ys2 = np.where(mask_np2 > 128)[0]
            scaled_bottom = ys2.max() if len(ys2) else new_h2 - 1
            paste_y = anchor_y - scaled_bottom - 1
            if paste_y < 0:
                paste_y = 0
            new_w, new_h = new_w2, new_h2
        # v110: COM (center-of-mass) horizontal centering — prevents canvas shift on idle
        # bbox centering causes horizontal jitter when frame width varies (breathing animation)
        final_arr = np.array(rgba_img)
        final_a = final_arr[:,:,3]
        com_weights = final_a.astype(np.float64)
        com_weights[com_weights < 128] = 0  # only count solid foreground
        com_sum = com_weights.sum()
        if com_sum > 0:
            com_x = (com_weights * np.arange(final_a.shape[1])).sum() / com_sum
            paste_x = int(w0 / 2 - com_x)
        else:
            paste_x = (w0 - new_w) // 2
        
        temp = Image.new('RGBA', (w0, h0), (0, 0, 0, 0))
        temp.paste(rgba_img, (paste_x, paste_y))
        temp.save(os.path.join(out_dir, fn))
    
    print(f'  soft alpha + fg normalize+anchor: {len(frames)} frames, target_fg={target_fg}, anchor_y={anchor_y}')
    print(f'  thresholds: core>{SIGMOID_CORE}→255, floor>{SIGMOID_FLOOR}→soft, else→0')
    if state_name != 'type':
        print(f'  darkblue fix: erode={ERODE_RADIUS}px, blur={EDGE_BLUR_SIGMA}px')
    return len(frames)


def to_webp(frames_dir, state_name, num_frames=None):
    import time as _time
    frames = sorted([f for f in os.listdir(frames_dir) if f.endswith('.png')])
    if num_frames:
        frames = frames[:num_frames]
    
    os.makedirs(ASSETS_DIR, exist_ok=True)
    for fn in frames:
        idx = int(fn.replace('.png', '')) - 1
        img = Image.open(os.path.join(frames_dir, fn))
        out_path = os.path.join(ASSETS_DIR, f'{state_name}_{idx:03d}.webp')
        for attempt in range(5):
            try:
                # Q80+α100: RGB lossy Q80, alpha lossless 100
                # Prevents white dots and missing parts (alpha 100% intact)
                # method=4: good balance of speed vs compression (method=6 too slow)
                img.save(out_path, 'WEBP', quality=80, lossless=False,
                         method=4, alpha_quality=100)
                break
            except OSError:
                _time.sleep(0.5 * (attempt + 1))
        else:
            print(f'  WARN: failed to save {out_path} after 5 retries')
    
    print(f'  Converted {len(frames)} {state_name} frames -> assets/')
    return len(frames)


def process_state(state_name, num_frames=None):
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
    
    if not os.path.exists(os.path.join(frames_dir, '00001.png')):
        extract_frames(video_path, frames_dir)
    
    if not os.path.exists(os.path.join(sigmoid_dir, '00001.png')):
        birefnet_soft_alpha(frames_dir, sigmoid_dir, work_dir)
    
    fg_normalize_and_anchor(frames_dir, sigmoid_dir, final_dir, state_name=state_name)
    
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
