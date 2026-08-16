# -*- coding: utf-8 -*-
"""快速核验：idle 视频帧与身份参考图是否同一只拉布拉多幼犬。"""
import base64, json
import requests

ROOT = r'D:\Hermes workspace\labrador_pet'
hx = open(f'{ROOT}\\keyhex.txt').read().strip()
KEY = bytes.fromhex(hx).decode()

def b64(p):
    return base64.b64encode(open(p, 'rb').read()).decode()

img_ref = b64(f'{ROOT}\\identity_candidates\\cand_0.png')
img_v = b64(f'{ROOT}\\_idle_check.png')

r = requests.post('https://api.agnes-ai.cn/v1/chat/completions',
    headers={'Authorization': KEY, 'Content-Type': 'application/json'},
    json={'model': 'agnes-2.5-flash', 'messages': [{'role': 'user', 'content': [
        {'type': 'text', 'text': '第一张图是身份参考图（Yellow Labrador puppy）。第二张图是同一视频的第10/60/110帧拼接。请严格判断：1) 视频帧中的狗是否与参考图是同一只（毛色/眼睛颜色/体型/年龄感）；2) 三帧之间身份是否一致无漂移；3) 背景是否纯白、主体是否居中且占画面高度<40%；4) 是否有变形/多余肢体。每项给结论，最后给1-10分。'},
        {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{img_ref}'}},
        {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{img_v}'}},
    ]}], 'max_tokens': 500}, timeout=120)
print(r.status_code)
print(r.json()['choices'][0]['message']['content'])
