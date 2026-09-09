"""Regen kiss + dance with better i2i base images."""
import base64, json, requests, time, cv2, numpy as np
from rembg import remove

KEYHEX = 'keyhex.txt'
tok = bytes.fromhex(open(KEYHEX).read().strip()).decode()
BASE = 'https://api.agnes-ai.cn'
HDR = {'Authorization': tok, 'Content-Type': 'application/json'}

# kiss: use identity_ref_front (same standing pose as idle)
with open('identity_ref_front.png', 'rb') as f:
    kiss_b64 = base64.b64encode(f.read()).decode()

# dance: use beg_ref (same upright pose, already approved)
with open('identity_candidates/beg_ref.png', 'rb') as f:
    dance_b64 = base64.b64encode(f.read()).decode()

COAT = ('WARM GOLDEN-CREAM fur, NOT white, NOT pale cream, the coat has a clear WARM GOLDEN '
        'tone on the head, ears and back, transitioning to lighter cream-gold on the chest and legs. '
        'The ears are SOFT FLOPPY with ample feathery golden fur, NOT small, NOT flat. '
        'The muzzle is medium length with a black nose. Deep brown warm eyes. ')

BODY = ('The body is SLENDER and ELONGATED with a LONG torso and relatively short legs, '
        'a typical young Golden Retriever puppy build. '
        'NOT barrel-shaped, NOT chubby, NOT round. Lean and leggy. ')

tasks = {
    'kiss': {
        'ref_b64': kiss_b64,
        'prompt': ('A young Golden Retriever puppy with light golden-cream fluffy fur. '
                   + COAT +
                   'The puppy wears a fitted pet vest: cream off-white stand-up collar with bright yellow '
                   'inner lining, brown sherpa fleece lower body, black center zipper, yellow drawstring '
                   'cords with black toggles, yellow webbing D-ring on back. '
                   'It stands facing the camera with an affectionate expression, looking directly at the '
                   'viewer with warm brown eyes, pink tongue slightly out. '
                   + BODY +
                   'Pure white seamless studio background, soft even lighting, photorealistic.'),
    },
    'dance': {
        'ref_b64': dance_b64,
        'prompt': ('A young Golden Retriever puppy with light golden-cream fluffy fur. '
                   + COAT +
                   'The puppy wears a fitted pet vest: cream off-white stand-up collar with bright yellow '
                   'inner lining, brown sherpa fleece lower body, black center zipper, yellow drawstring '
                   'cords with black toggles, yellow webbing D-ring on back. '
                   'It dances playfully balanced upright on its hind legs, both front paws raised waving '
                   'in the air. '
                   + BODY +
                   'Pure white seamless studio background, soft even lighting, photorealistic.'),
    },
}

IDLE_SUB_H = 433

for name, task in tasks.items():
    payload = {
        'model': 'agnes-image-2.1-flash',
        'prompt': task['prompt'],
        'size': '1024x1024',
        'image': f'data:image/png;base64,{task["ref_b64"]}'
    }
    print(f'Generating {name}...', flush=True)
    r = None
    for attempt in range(3):
        try:
            r = requests.post(f'{BASE}/v1/images/generations', headers=HDR, json=payload, timeout=300)
            if r.status_code == 200:
                break
            time.sleep(5)
        except Exception:
            time.sleep(5)
    if not r or r.status_code != 200:
        print(f'{name} FAILED')
        continue
    d = r.json()
    item = d['data'][0]
    raw_path = f'identity_candidates/{name}_ref_raw.png'
    if item.get('b64_json'):
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(base64.b64decode(item['b64_json']))).convert('RGB')
        img.save(raw_path)
    elif item.get('url'):
        resp = requests.get(item['url'], timeout=120)
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(resp.content)).convert('RGB')
        img.save(raw_path)
    print(f'{name} raw saved')

    cv_img = cv2.imread(raw_path)
    rgba = remove(cv_img)
    alpha = rgba[:, :, 3]
    ys, xs = np.where(alpha >= 200)
    if len(ys) == 0:
        print(f'{name}: no subject')
        continue
    top, bot = ys.min(), ys.max()
    left, right = xs.min(), xs.max()
    sub_h = bot - top + 1
    sub_w = right - left + 1
    print(f'  raw: {sub_w}x{sub_h}, aspect={sub_h/sub_w:.2f}')

    scale = IDLE_SUB_H / sub_h
    new_w = int(sub_w * scale)
    new_h = IDLE_SUB_H

    crop = rgba[top:bot+1, left:right+1].copy()
    crop[crop[:, :, 3] < 200, 3] = 0
    resized = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_AREA)

    canvas = np.ones((1024, 1024, 4), dtype=np.uint8) * 255
    canvas[:, :, 3] = 255
    x_off = (1024 - new_w) // 2
    y_off = (1024 - new_h) // 2
    dh = min(new_h, 1024 - y_off)
    dw = min(new_w, 1024 - x_off)
    da = resized[:dh, :dw, 3].astype(float) / 255.0
    for c in range(3):
        canvas[y_off:y_off+dh, x_off:x_off+dw, c] = (
            canvas[y_off:y_off+dh, x_off:x_off+dw, c] * (1 - da) +
            resized[:dh, :dw, c] * da
        ).astype(np.uint8)

    final_path = f'identity_candidates/{name}_ref.png'
    cv2.imwrite(final_path, canvas[:, :, :3])

    # cleanup raw
    import os
    os.remove(raw_path)

    check = cv2.imread(final_path)
    c_rgba = remove(check)
    c_alpha = c_rgba[:, :, 3]
    cys, cxs = np.where(c_alpha >= 200)
    if len(cys) > 0:
        ch = cys.max() - cys.min() + 1
        cw = cxs.max() - cxs.min() + 1
        print(f'  final: {cw}x{ch}, aspect={ch/cw:.2f}, h_ratio={ch/1024*100:.1f}%')

    time.sleep(2)

print('ALL DONE')
