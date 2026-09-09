# -*- coding: utf-8 -*-
"""阶段1a: 身份候选图生成（Agnes t2i）。4个候选（不同姿态/朝向），供 vision_pick.py 挑选。
金毛+Hoopet背心版：所有动作必须穿着背心，身份图即穿着背心。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe gen_identity.py
"""
import base64, json, os, io, time
from PIL import Image
import requests

BASE = 'https://api.agnes-ai.cn'
ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, 'identity_candidates')
os.makedirs(OUT, exist_ok=True)

# ══════════ CONFIG（金毛+背心） ══════════
KEYHEX = os.path.join(ROOT, 'keyhex.txt')

# SUBJ: 全局统一逐字复用。金毛奶犬+Hoopet背心。
# 核心教训：SUBJ 必须简洁（原版金毛仅15词就生成完美奶犬），过度描述反而干扰模型
SUBJ = (
    'A tiny cute chubby short-legged Golden Retriever puppy with a round barrel-shaped body, '
    'warm brown eyes and soft floppy ears. '
    'The puppy wears a fitted pet vest at all times: '
    'cream off-white stand-up collar with bright yellow inner lining, '
    'brown sherpa fleece lower body, black center zipper, '
    'yellow drawstring cords with black toggles, yellow webbing D-ring on back.'
)

NEG_BREED = (
    'adult dog, mature dog, short-haired, short coat, labrador, husky, samoyed, pomeranian, '
    'collar, leash, naked dog, dog without vest, dog without clothes, red bandana, bandana'
)

# 身份图姿态铁律: 全部候选必须四腿站立，且腿部解剖正确
VARIANTS = [
    ' It stands on all four paws in a three-quarter view facing slightly right, looking at '
    'the camera with a gentle happy expression, tongue slightly out. Four clearly separated '
    'straight legs: two front legs under the shoulders, two hind legs under the hips, '
    'each leg has one paw with four toes, exactly four legs total, no extra legs or paws.',
    ' It stands on all four paws facing slightly left, head tilted, curious friendly '
    'expression, golden cream fur, vest clearly visible. Four clearly separated '
    'straight legs visible, exactly four paws total, no extra limbs.',
    ' It stands on all four paws in a side profile view facing right, alert and cheerful, '
    'floppy ears slightly forward, sturdy compact puppy build, vest visible from the side. '
    'All four legs clearly visible and anatomically correct, no extra legs or paws.',
    ' It stands on all four paws facing the camera, adorable expression, warm brown eyes, '
    'golden cream fur, vest clearly visible from the front. Four straight legs clearly '
    'visible under the body, exactly four paws on the ground, no extra legs or deformities.',
]

PICK_CRITERIA = (
    '1) Must be a GOLDEN RETRIEVER PUPPY with warm golden cream fluffy fur and soft floppy ears. '
    '2) Must look like a tiny cute fluffy puppy, not an adult dog. '
    '3) Warm brown eyes (not blue). '
    '4) MUST be wearing a pet vest with: cream off-white stand-up collar, brown sherpa fleece lower body, '
    'black center zipper, yellow drawstring cords with black toggles. The vest must be clearly visible. '
    '5) Must be standing on all four legs (not sitting, not lying down). '
    '6) The entire body from nose to tail must be fully visible inside the frame. '
    '7) CRITICAL: Must have exactly FOUR legs with correct anatomy — two front legs under shoulders, '
    'two hind legs under hips, four paws total, no extra legs, no extra paws, no deformed leg joints. '
    'If the image has 5+ legs or malformed leg connections, REJECT immediately.'
)
# ══════════ CONFIG END ══════════

COMMON = (' The subject stays perfectly centered in the same spot. Extreme wide shot, the subject '
          'takes up less than 40 percent of the frame height with lots of empty white space around '
          'it. Static locked camera, pure white seamless studio background, soft even lighting, '
          'photorealistic, sharp crisp fur detail.')
NEG = ('cartoon, childish, ugly, extra legs, extra tail, deformed, mutated, subtitles, watermark, '
       'text, logo, blurry, jittery, distorted, inconsistent appearance, other animals, human, '
       'person, cropped, cut off, close up, zoomed in, filling frame, large subject, ' + NEG_BREED)

tok = bytes.fromhex(open(KEYHEX).read().strip()).decode()
HDR = {'Authorization': tok, 'Content-Type': 'application/json'}  # 裸key勿加Bearer

results = []
for i, desc in enumerate(VARIANTS):
    prompt = SUBJ + desc + COMMON
    print(f'Generating candidate {i}...', flush=True)
    # text2image API does not support negative_prompt — fold key exclusion words into the prompt
    payload = {'model': 'agnes-image-2.1-flash', 'prompt': prompt,
               'size': '1024x1024',
               'response_format': 'b64_json'}
    r = None
    for attempt in range(3):
        try:
            r = requests.post(f'{BASE}/v1/images/generations', headers=HDR,
                              json=payload, timeout=300)
            break
        except Exception as e:
            print(f'  retry {attempt+1}: {e}', flush=True)
            time.sleep(3)
    if r is None or r.status_code != 200:
        print(f'  HTTP {r.status_code if r else "?"}: {(r.text[:200] if r else "no response")}', flush=True)
        continue
    d = r.json()
    b64 = d.get('data', [{}])[0].get('b64_json')
    if not b64:
        print(f'  no b64: {json.dumps(d)[:200]}', flush=True)
        continue
    img = Image.open(io.BytesIO(base64.b64decode(b64))).convert('RGBA')
    path = os.path.join(OUT, f'cand_{i}.png')
    img.save(path)
    print(f'  saved {path} {img.size}', flush=True)
    results.append({'i': i, 'path': path})
    time.sleep(2)

with open(os.path.join(OUT, 'results.json'), 'w') as f:
    json.dump(results, f, indent=1)
with open(os.path.join(OUT, 'criteria.txt'), 'w') as f:
    f.write(SUBJ + '\n' + PICK_CRITERIA)
print('\nDONE:', len(results), 'candidates', flush=True)
