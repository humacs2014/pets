# -*- coding: utf-8 -*-
"""阶段1b: vision 评估4张身份候选图，选最佳作为全部动作的身份参考图。
输出 BEST: N → 将 identity_candidates/cand_N.png 写入 regen_videos.py 的 REF_IMAGE。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe vision_pick.py
"""
import base64, os
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, 'identity_candidates')
tok = bytes.fromhex(open(os.path.join(ROOT, 'keyhex.txt')).read().strip()).decode()

# 审核标准 = SUBJ + 品种/年龄/眼色/白底/清晰度/完整性（gen_identity.py 已存 criteria.txt）
subj, *criteria = open(os.path.join(OUT, 'criteria.txt')).read().strip().split('\n')
criteria_text = '\n'.join(criteria)

imgs = []
for i in range(4):
    p = os.path.join(OUT, f'cand_{i}.png')
    if os.path.exists(p):
        b64 = base64.b64encode(open(p, 'rb').read()).decode()
        imgs.append((i, b64))

content = [{'type': 'text', 'text':
    'You are auditing identity reference images for a desktop pet. '
    f'The target identity is: "{subj}" '
    'Evaluate each of the 4 images (numbered 0-3) against these criteria:\n'
    f'{criteria_text}\n'
    '4) Clean pure white background, no props, no text. '
    '5) Sharp clear quality, good lighting, appealing cute expression. '
    '6) Full body visible, not cropped. '
    'For each image give: a score out of 10 and a 1-line reason. '
    'Then give a FINAL line: "BEST: <number>" with the single best image number for use as '
    'the identity reference image. Be strict: reject anything that does not match the target.'}]
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
