# -*- coding: utf-8 -*-
"""阶段1a: 拉布拉多身份候选图生成（t2i）。4个候选，后续vision挑选。"""
import base64, json, os, io, time
from PIL import Image
import requests

BASE = 'https://api.agnes-ai.cn'
ROOT = r'D:\Hermes workspace\labrador_pet'
OUT = os.path.join(ROOT, 'identity_candidates')
os.makedirs(OUT, exist_ok=True)

hx = open(os.path.join(ROOT, 'keyhex.txt')).read().strip()
tok = bytes.fromhex(hx).decode()

# SUBJ 措辞（拉布拉多版，全局统一，逐字复用）
SUBJ = 'A tiny cute fluffy Yellow Labrador puppy with warm brown eyes.'

COMMON = (' The subject stays perfectly centered in the same spot. Extreme wide shot, the subject '
          'takes up less than 40 percent of the frame height with lots of empty white space around '
          'it. Static locked camera, pure white seamless studio background, soft even lighting, '
          'photorealistic, sharp crisp fur detail.')
NEG = ('cartoon, childish, ugly, extra legs, extra tail, deformed, mutated, subtitles, watermark, '
       'text, logo, blurry, jittery, distorted, inconsistent appearance, other animals, human, '
       'person, cropped, cut off, close up, zoomed in, filling frame, large subject, '
       'adult dog, chocolate color, black fur, collar, leash')

VARIANTS = [
    ' It stands on all four paws facing slightly to the side in a three-quarter view, looking at '
    'the camera with a gentle happy expression, tongue slightly out, tail relaxed.',
    ' It stands facing the camera in a front three-quarter view, head tilted slightly, curious '
    'friendly expression, soft golden cream fur catching the light.',
    ' It stands in a side profile view facing right, alert and cheerful, ears slightly forward, '
    'sturdy compact puppy build with fluffy golden coat.',
    ' It sits facing the camera with head slightly tilted, big warm brown eyes looking up, '
    'adorable pleading expression, fluffy cream colored fur.',
]

results = []
for i, desc in enumerate(VARIANTS):
    prompt = SUBJ + desc + COMMON
    print(f'Generating candidate {i}...', flush=True)
    payload = {'model': 'agnes-image-2.1-flash', 'prompt': prompt,
               'negative_prompt': NEG, 'size': '1024x1024',
               'extra_body': {'response_format': 'b64_json'}}
    r = None
    for attempt in range(3):
        try:
            r = requests.post(f'{BASE}/v1/images/generations',
                              headers={'Authorization': tok, 'Content-Type': 'application/json'},
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
print('\nDONE:', len(results), 'candidates', flush=True)
