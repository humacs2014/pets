#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate walk darkblue video using correct ref_side.png and v4 prompts."""
import sys, os, time, json, base64, requests

ROOT = os.path.dirname(os.path.abspath(__file__))
KEYHEX = os.path.join(ROOT, 'keyhex.txt')
REFS_DIR = os.path.join(ROOT, 'darkblue_refs_wide')
VIDEOS_DIR = os.path.join(ROOT, 'videos')
os.makedirs(VIDEOS_DIR, exist_ok=True)

hx = open(KEYHEX).read().strip()
tok = ''.join(chr(int(hx[i:i+2],16)) for i in range(0,len(hx),2))
BASE = 'https://api.agnes-ai.cn/v1'
HDR = {'Authorization': tok, 'Content-Type': 'application/json'}

# ═══ Subject description (from gen_videos_v4.py — DO NOT MODIFY) ═══
SUBJ = (
    'A Golden Retriever puppy with an irresistibly cute face: '
    'round dome-shaped head, very large round dark brown puppy-dog eyes '
    'with bright catchlights, short small muzzle, big round black nose, '
    'puffy chubby cheeks that make the face look round and soft, '
    'EXACTLY two soft floppy pendant ears that hang low and forward, no extra ears. '
    'fluffy soft wispy puppy fur that is puffy and cloud-like around the head and neck. '
    'The body is that of a young Golden Retriever with well-proportioned athletic build, '
    'legs are proportionally long and slender for a Golden, not stubby. '
    'The overall body shape is lean and elegant, only the face has adorable puppy roundness. '
    'EXACTLY four legs, no extra legs or ghost limbs. '
    'The dog ALWAYS wears a fitted pet vest at ALL times: '
    'cream off-white stand-up collar with bright yellow inner lining, '
    'brown sherpa fleece lower body, black center zipper, '
    'yellow drawstring cords with black toggles, yellow webbing D-ring on back. '
    'The vest stays on the dog the entire time, never removed, never changing.'
)

FRAMING = (
    ' EXTREME WIDE SHOT: the camera is very far away so the ENTIRE dog '
    'from the very top of its ears to the very bottom of all four paws is completely visible, '
    'with massive empty dark blue space above the head and below the paws. '
    'The dog takes up only about 20 to 25 percent of the frame height — '
    'the dog must look small in the center of a large frame. '
    'There must be at least as much empty space above the ears as the dog is tall. '
    'All four paws are clearly visible at the bottom with lots of space below. '
    'The tail tip is visible. Nothing is cropped or cut off. '
    'Centered full-body portrait with enormous breathing room all around.'
)

COMMON = (
    ' Static locked camera, solid dark blue studio background '
    '(dark navy blue, color #172A49, RGB 23 42 73), soft even lighting, '
    'photorealistic, sharp crisp fur detail.'
    ' The subject stays perfectly centered in the same spot the whole time. '
    ' The dog maintains a consistent body size throughout — '
    'no zooming in or out, no getting closer or farther.'
)

NEG = (
    'cartoon, childish, ugly, deformed, mutated, subtitles, '
    'watermark, text, logo, blurry, jittery, distorted, inconsistent appearance, '
    'other animals, human, person, '
    'close-up, portrait, headshot, bust, cropped, cut off, filling frame, '
    'large subject, zoomed in, tight framing, body cut by frame edge, '
    'paws out of frame, feet out of frame, paws cropped, '
    'zoom in, zoom out, getting closer, getting farther, size change, '
    'long muzzle, long snout, adult dog face, mature face, angular face, narrow face, '
    'flat expression, dull stare, lifeless eyes, angry, scared, '
    'tiny puppy body, chubby body, fat body, barrel-shaped body, round body, '
    'stubby legs, short legs, dwarf legs, corgi legs, '
    'labrador, husky, samoyed, pomeranian, '
    'curly fur, wavy fur, frizzy fur, wire-haired, '
    'different dog, changed appearance, wrong breed, '
    'collar, leash, naked dog, dog without vest, '
    'vest disappearing, vest removed, vest changing, '
    'front view, facing camera, head-on view, '
    'extra legs, five legs, six legs, extra ears, three ears, four ears, standing ears, '
    'ghost paw, ghost limb, afterimage, duplicate paw, leftover paw, '
    'pink skin artifact, pink groin, pink belly patch, '
    'different background color, white background, green background'
)

# Walk action prompt — SIDE VIEW walking
WALK_ACTION = (
    ' The dog walks at a steady relaxed pace in a SIDE VIEW facing right, '
    'showing a natural four-beat walking gait: each leg lifts and steps forward one at a time '
    'in the sequence left-hind, left-front, right-hind, right-front, '
    'with smooth weight transfer and a gentle head bob. '
    'The tail hangs naturally with a slight sway. '
    'The dog walks in place without actually moving across the frame — '
    'the body stays centered in frame the whole time, only the legs cycle through the walk gait. '
    'The dog looks slightly ahead in the direction of travel with a calm content expression.'
)

def submit_video(prompt, neg, ref_image):
    img = base64.b64encode(open(ref_image, 'rb').read()).decode()
    r = requests.post(f'{BASE}/video/generations', headers=HDR, json={
        'model': 'agnes-video-v2.0', 'prompt': prompt, 'negative_prompt': neg,
        'image': f'data:image/png;base64,{img}',
        'num_frames': 121, 'frame_rate': 24}, timeout=180)
    if r.status_code != 200:
        return None, r.text[:300]
    d = r.json()
    return d.get('video_id') or d.get('task_id'), None

def poll_video(video_id, timeout_s=1800):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            d = requests.get('https://api.agnes-ai.cn/agnesapi',
                            params={'video_id': video_id},
                            headers={'Authorization': tok}, timeout=60).json()
        except Exception:
            time.sleep(15); continue
        st = (d.get('status') or '').lower()
        if st == 'completed':
            return d.get('url'), None
        if st == 'failed':
            return None, json.dumps(d.get('error'), ensure_ascii=False)[:300]
        print(f'    {st} {d.get("progress", "")}%', flush=True)
        time.sleep(20)
    return None, 'poll timeout'

if __name__ == '__main__':
    ref_path = os.path.join(REFS_DIR, 'ref_side.png')
    assert os.path.exists(ref_path), f'Ref not found: {ref_path}'
    
    prompt = SUBJ + WALK_ACTION + FRAMING + COMMON
    print(f'walk: prompt={len(prompt)} chars, ref=ref_side.png', flush=True)
    
    vid, err = submit_video(prompt, NEG, ref_path)
    for attempt in range(6):
        if vid: break
        wait = 75 * (2 ** attempt)
        print(f'  [retry {attempt+1}/6] {err} — wait {wait}s', flush=True)
        time.sleep(wait)
        vid, err = submit_video(prompt, NEG, ref_path)
    
    if not vid:
        print(f'FAIL submit: {err}', flush=True)
        sys.exit(1)
    
    print(f'  video_id={vid}, polling...', flush=True)
    url, err = poll_video(vid)
    if not url:
        print(f'FAIL poll: {err}', flush=True)
        sys.exit(1)
    
    out = os.path.join(VIDEOS_DIR, 'walk_darkblue_v4.mp4')
    data = requests.get(url, timeout=300).content
    with open(out, 'wb') as f:
        f.write(data)
    sz = len(data) // 1024
    print(f'✓ Saved: {out} ({sz}KB)', flush=True)
