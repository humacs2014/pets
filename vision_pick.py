# -*- coding: utf-8 -*-
"""阶段1b: vision 评估4张身份候选图，选最佳。"""
import base64, os, json
import requests

ROOT = r'D:\Hermes workspace\labrador_pet'
OUT = os.path.join(ROOT, 'identity_candidates')
hx = open(os.path.join(ROOT, 'keyhex.txt')).read().strip()
tok = bytes.fromhex(hx).decode()

imgs = []
for i in range(4):
    p = os.path.join(OUT, f'cand_{i}.png')
    if os.path.exists(p):
        b64 = base64.b64encode(open(p, 'rb').read()).decode()
        imgs.append((i, b64))

content = [{'type': 'text', 'text':
    'You are auditing identity reference images for a desktop pet. '
    'The target identity is: "A tiny cute fluffy Yellow Labrador puppy with warm brown eyes." '
    'Evaluate each of the 4 images (numbered 0-3) against these criteria: '
    '1) Must be a YELLOW/CREAM Labrador (not chocolate, not black, not husky). '
    '2) Must look like a YOUNG PUPPY (small, cute, fluffy), not an adult dog. '
    '3) Warm brown eyes (not blue). '
    '4) Clean pure white background, no props, no text. '
    '5) Sharp clear quality, good lighting, appealing cute expression. '
    '6) Full body visible, not cropped. '
    'For each image give: a score out of 10 and a 1-line reason. '
    'Then give a FINAL line: "BEST: <number>" with the single best image number for use as '
    'the identity reference image. Be strict: reject anything that is not clearly a yellow lab puppy.'}]
for i, b64 in imgs:
    content.append({'type': 'text', 'text': f'Image {i}:'})
    content.append({'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{b64}'}})

r = requests.post('https://api.agnes-ai.cn/v1/chat/completions',
                  headers={'Authorization': tok, 'Content-Type': 'application/json'},
                  json={'model': 'agnes-2.5-flash', 'messages': [{'role': 'user', 'content': content}],
                        'max_tokens': 4000}, timeout=300)
d = r.json()
msg = d['choices'][0]['message']
print('=== VISION RESULT ===')
print(msg.get('content') or '(empty content)')
print('=== END ===')
