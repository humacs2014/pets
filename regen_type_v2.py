# -*- coding: utf-8 -*-
"""type v2: 参考图直改首帧（真键盘+萨摩耶化）→ ti2v 重生成。"""
import base64, os, sys, time, json
import requests

BASE = 'https://api.agnes-ai.cn/v1'
hx = open('keyhex.txt').read().strip()
tok = ''.join(chr(int(hx[i:i+2],16)) for i in range(0,len(hx),2))
HDR = {'Authorization': tok, 'Content-Type': 'application/json'}
REF = 'type_firstframe_v2.png'
OUT = 'videos/type_v2.mp4'

PROMPT = ('The fluffy white Samoyed dog shown in the first frame stays exactly the same dog '\
          'in every frame — same pure white fluffy fur, same face, same body. It happily types '\
          'on the keyboard with both front paws: the paws alternately lift and press down on the '\
          'round colorful keycaps, left paw taps then right paw, playful rhythmic typing motion, '\
          'head gently bobbing as it looks at the keys, mouth slightly open with pink tongue, '\
          'cheerful. The keyboard with cream-white base, round pastel macaron keycaps (mint green, '\
          'light blue, soft pink, pale yellow), paw-print and bone decorations on the front edge, '\
          'stays PERFECTLY STABLE and identical in every frame — same shape, same colors, same '\
          'position. Pure solid white background, unchanged. Camera completely static.')
NEG = ('orange fur, brown fur, tan fur, red fur, shiba inu, different dog, changed appearance, '\
       'keyboard morphing, melting keyboard, warping keyboard, changing keycap colors, beads, '\
       'pearls, extra paws, five legs, six legs, human, person, hands, text, watermark, '\
       'camera movement, zoom, pan, background change')

img = base64.b64encode(open(REF,'rb').read()).decode()
r = requests.post(f'{BASE}/video/generations', headers=HDR, json={
    'model':'agnes-video-v2.0','prompt':PROMPT,'negative_prompt':NEG,
    'image':f'data:image/png;base64,{img}','num_frames':121,'frame_rate':24}, timeout=180)
print('submit status', r.status_code, flush=True)
if r.status_code != 200:
    print('ERR', r.text[:400], flush=True); sys.exit(1)
vid = r.json().get('video_id') or r.json().get('task_id')
print('video_id', vid, flush=True)

t0 = time.time(); url = None
while time.time()-t0 < 1800:
    try:
        d = requests.get('https://api.agnes-ai.cn/agnesapi', params={'video_id':vid},
                         headers={'Authorization':tok}, timeout=60).json()
    except Exception as e:
        print('poll exc', e, flush=True); time.sleep(15); continue
    st = (d.get('status') or '').lower()
    if st == 'completed':
        url = d.get('url'); break
    if st == 'failed':
        print('FAILED', json.dumps(d.get('error'), ensure_ascii=False)[:300], flush=True); sys.exit(2)
    print(f'  {st} {d.get("progress","")}%', flush=True)
    time.sleep(20)
if not url:
    print('poll timeout', flush=True); sys.exit(3)
r = requests.get(url, timeout=300)
open(OUT,'wb').write(r.content)
print(f'SAVED {OUT} ({len(r.content)} bytes)', flush=True)

# 自验：5帧缩略
import cv2, numpy as np
cap = cv2.VideoCapture(OUT)
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
os.makedirs('_probe', exist_ok=True)
tiles = []
for i in (0,30,60,90,120):
    cap.set(cv2.CAP_PROP_POS_FRAMES, min(i,n-1))
    ok,f = cap.read()
    if ok: tiles.append(cv2.resize(f,(272,208)))
sheet = np.hstack(tiles)
cv2.imwrite('_probe/v2_video_check.png', sheet)
print('check sheet saved, frames:', n, flush=True)
print('ALL_DONE', flush=True)
