# -*- coding: utf-8 -*-
"""type v2: 截图样式键盘首帧 i2v 重生成源视频（mochi v117 验证版移植，萨摩耶版）。
首帧=make_type_firstframe.py 合成（干净sit帧+截图键盘+搭键爪构图）。
prompt 只描述动画行为+键盘外观锚定（首帧已含键盘，模型延续该样式渲染）。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe regen_type_samoyed.py
"""
import base64, json, os, sys, time
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
KEYHEX = os.path.join(ROOT, 'keyhex.txt')
BASE = 'https://api.agnes-ai.cn/v1'
tok = bytes.fromhex(open(KEYHEX).read().strip()).decode()
HDR = {'Authorization': tok, 'Content-Type': 'application/json'}

SUBJ = ('A fluffy adult white Samoyed dog EXACTLY identical to the dog in the reference image — '
        'same face, same body proportions, same thick pure white double coat: gentle smiling '
        'expression with slightly upturned black lips, erect triangular ears, dark almond-shaped '
        'eyes, black nose, plume tail curled over the back.')

# v117 范式：首帧已含真键盘+搭键爪，prompt 描述场景延续+纯动画行为（键盘外观锚定防重画）
DESC = (' The scene is EXACTLY as in the reference image: the Samoyed sits behind the SAME cream '
        'toy keyboard with ROUND MACARON-COLORED keycaps (mint green, baby blue, pale pink, cream '
        'round keys in neat even rows, paw and bone decorations on the cream base edge), with '
        'BOTH front paws already resting on the keycaps. The video shows ONLY this animation: the '
        'two front paws ALTERNATE PRESSING THE KEYS in a clear rhythmic left-right-left-right '
        'tapping — one paw presses down while the other lifts slightly, then they swap, a gentle '
        'typing bounce several times per second. The paws stay OPAQUE and SOLID, always visibly '
        'IN FRONT of the keycaps, never transparent, never ghosting through the keyboard. The '
        'head is slightly lowered watching the keys with a happy focused expression, pink tongue '
        'slightly out, tail wagging gently. The FACE AND EYES stay PERFECTLY STABLE in every '
        'frame: eye shape, eye size, pupil position and the white catchlight inside each eye stay '
        'IDENTICAL frame after frame, only a rare slow natural blink, no eye flicker, no shimmer. '
        'The dog body stays CALM AND MOSTLY STILL: no big bouncing, no head swinging, only the '
        'small alternating paw tapping. The keyboard and EVERY keycap stay PERFECTLY STATIC AND '
        'IDENTICAL in size and position in every single frame: the keyboard never grows, never '
        'shrinks, never moves, never morphs, no keys appearing or disappearing. The dog stays in '
        'the same spot the entire video.'
        ' The coat is clean uniform pure white thick double fur on every part of the body.'
        ' The ENTIRE background and floor is one UNIFORM SOLID pure white seamless studio '
        'backdrop, with soft even lighting, photorealistic, sharp crisp fur detail. Static locked '
        'camera.')

NEG = ('cartoon, childish, ugly, extra legs, extra tail, deformed, mutated, subtitles, '
       'watermark, text, logo, blurry, jittery, distorted, inconsistent appearance, '
       'other animals, human, person, cropped, cut off, close up, zoomed in, filling frame, '
       'large subject, moving forward, walking forward, changing position, '
       'different dog, another dog, changed appearance, wrong breed, '
       'illustration, 3d render, cgi, animation style, anime, low quality, '
       'golden retriever, labrador, husky, malamute, brown fur, black fur, gray fur, yellow fur, '
       'chocolate color, floppy ears, short-haired, short coat'
       ', keyboard reversed, keyboard upside down, keyboard moving, sliding keyboard, floating '
       'keyboard, multiple keyboards, giant keyboard, keyboard bigger than the dog, keyboard '
       'wider than the dog, morphing keyboard, changing key layout, flickering keys, keys '
       'appearing and disappearing, keyboard growing, keyboard shrinking, changing keyboard size, '
       'paws off keyboard, paws in air, transparent paws, semi-transparent paws, ghost paws, '
       'see-through paws, paws blending into keyboard, big bouncing, wild head swinging, '
       'exaggerated motion, standing up, walking, turning away, back to camera, lying down on '
       'keyboard, chewing keyboard, biting keyboard, flickering eyes, shimmering eyes, changing '
       'eye shape, shifting catchlights, sparkling changing eyes, frozen paws, static paws, '
       'motionless paws, paws not moving'
       ', splayed legs, wide stance, legs apart, five legs, six legs, extra legs, splayed hind '
       'legs, twisted legs, unnatural legs')

def main():
    img = base64.b64encode(open(os.path.join(ROOT, 'type_firstframe.png'), 'rb').read()).decode()
    prompt = SUBJ + DESC
    r = requests.post(f'{BASE}/video/generations', headers=HDR, json={
        'model': 'agnes-video-v2.0', 'prompt': prompt, 'negative_prompt': NEG,
        'image': f'data:image/png;base64,{img}',
        'num_frames': 121, 'frame_rate': 24}, timeout=180)
    if r.status_code != 200:
        print('SUBMIT FAIL', r.status_code, r.text[:300]); sys.exit(1)
    vid = r.json().get('video_id') or r.json().get('task_id')
    print('[submit] type video_id=' + str(vid), flush=True)
    t0 = time.time()
    while time.time() - t0 < 1800:
        try:
            d = requests.get('https://api.agnes-ai.cn/agnesapi', params={'video_id': vid},
                             headers={'Authorization': tok}, timeout=60).json()
        except Exception:
            time.sleep(15); continue
        st = (d.get('status') or '').lower()
        if st == 'completed':
            url = d.get('url')
            rr = requests.get(url, timeout=300)
            open(os.path.join(ROOT, 'videos', 'type.mp4'), 'wb').write(rr.content)
            print(f'SAVED videos/type.mp4 ({len(rr.content)} bytes)'); return
        if st == 'failed':
            print('FAILED', json.dumps(d.get('error'), ensure_ascii=False)[:300]); sys.exit(1)
        print(f'    {st} {d.get("progress", "")}%', flush=True)
        time.sleep(20)
    print('POLL TIMEOUT'); sys.exit(1)

if __name__ == '__main__':
    main()
