# -*- coding: utf-8 -*-
"""阶段1a: 身份候选图生成（Agnes t2i）。4个候选（不同姿态/朝向），供 vision_pick.py 挑选。
新宠物: 改 CONFIG 的 SUBJ / NEG 品种排除词。复制到新项目根目录运行。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe gen_identity.py
"""
import base64, json, os, io, time
from PIL import Image
import requests

BASE = 'https://api.agnes-ai.cn'
ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, 'identity_candidates')
os.makedirs(OUT, exist_ok=True)

# ══════════ CONFIG（新宠物改这里） ══════════
KEYHEX = os.path.join(ROOT, 'keyhex.txt')
# SUBJ 措辞: 全局统一逐字复用。年龄词(puppy/adult)必须与目标形象一致——写adult整批显老。
SUBJ = ('An adorable tiny fluffy Shiba Inu puppy with round chubby cheeks, small triangular '
        'erect ears, big dark sparkling round eyes, a tiny black nose, soft cream and warm orange '
        'fur with white chest and belly markings, and a fluffy curled tail.')
NEG_BREED = ('adult dog, long silky fur, golden retriever, labrador, husky, gray fur, black fur, '
             'brown coat, floppy ears, droopy ears, collar, leash, skinny, thin')  # 品种/毛色排除词,按宠物改
# 身份图姿态铁律: 全部候选必须四腿站立（坐姿图会拖拽所有动作视频姿态）
VARIANTS = [
    ' It stands on all four paws facing slightly to the side in a three-quarter view, looking at '
    'the camera with a gentle happy expression, tongue slightly out, tail curled happily.',
    ' It stands on all four paws facing the camera in a front three-quarter view, head tilted '
    'slightly, curious friendly expression, soft cream and orange fur catching the light.',
    ' It stands on all four paws in a side profile view facing right, alert and cheerful, little '
    'triangular ears slightly forward, sturdy compact puppy build with fluffy curled tail.',
    ' It stands on all four paws in a side profile view facing left, looking back over its shoulder '
    'at the camera with an adorable smile, cheeks puffy and round, tail curled up.',
]
# vision_pick.py 的审核标准文本（品种/毛色/眼色必须与 SUBJ 一致）
PICK_CRITERIA = ('1) Must be a SHIBA INU with triangular erect ears, a curled tail, and cream-and-'
    'orange fur with white chest markings (not golden retriever, not labrador, not husky, no '
    'floppy ears, no gray/black fur). '
    '2) Must look like a YOUNG PUPPY (small, cute, round chubby cheeks, fluffy), not an adult dog. '
    '3) Big dark round eyes (not blue, not light colored). ')
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
    payload = {'model': 'agnes-image-2.1-flash', 'prompt': prompt,
               'negative_prompt': NEG, 'size': '1024x1024',
               'extra_body': {'response_format': 'b64_json'}}
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
# 保存挑选标准供 vision_pick.py 复用
with open(os.path.join(OUT, 'criteria.txt'), 'w') as f:
    f.write(SUBJ + '\n' + PICK_CRITERIA)
print('\nDONE:', len(results), 'candidates', flush=True)
