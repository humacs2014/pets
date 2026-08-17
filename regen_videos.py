# -*- coding: utf-8 -*-
"""阶段2: 拉布拉多 16 状态动作视频批量生成（Agnes ti2vid）。
顺序提交间隔>=70s防限流，每个提交后轮询至完成下载。后台运行。
用法: python regen_videos.py [状态名...]（默认全部）
"""
import sys, os, time, json, base64
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))

# ══════════ CONFIG（拉布拉多） ══════════
KEYHEX = os.path.join(ROOT, 'keyhex.txt')
REF_IMAGE = os.path.join(ROOT, 'identity_candidates', 'cand_0.png')  # 身份参考图(视觉10/10)
SUBJ = 'A tiny cute fluffy Yellow Labrador puppy with warm brown eyes.'
VIDEOS_DIR = os.path.join(ROOT, 'videos')

COMMON = (' The subject stays perfectly centered in the same spot the whole time, not moving '
          'forward at all. Extreme wide shot, the subject takes up less than 40 percent of the '
          'frame height with lots of empty white space around it. Static locked camera, pure '
          'white seamless studio background, soft even lighting, photorealistic, sharp crisp '
          'fur detail.')
NEG_BASE = ('cartoon, childish, ugly, extra legs, extra tail, deformed, mutated, subtitles, '
            'watermark, text, logo, blurry, jittery, distorted, inconsistent appearance, '
            'other animals, human, person, cropped, cut off, close up, zoomed in, filling frame, '
            'large subject, moving forward, walking forward, changing position, '
            'adult dog, husky, gray fur, black fur, chocolate color')

ACTIONS = {
    'idle':      (' It stands in an EXACT SIDE PROFILE VIEW facing right: the muzzle points to '\
                  'the right, only ONE eye is visible, the tail extends to the left. All four '\
                  'legs straight down and clearly separated, the two hind legs close together '\
                  'and parallel, never splayed wide. The head stays in profile the whole time: '\
                  'it looks around by turning slightly within the side plane only, NEVER turning '\
                  'toward the camera, occasional small ear twitches, gently swaying. The body '\
                  'NEVER turns to a front or three-quarter view, the chest never faces the camera.',
                  ', head turned to camera, looking at viewer, both eyes visible, facing camera, '\
                  'front view, three quarter view, chest toward camera, splayed legs, wide '\
                  'stance, legs apart, five legs, six legs, extra legs'),
    'sit':       (' It calmly sits down facing the camera, tail curled around its paws, '
                  'breathing gently with occasional ear twitches.', ''),
    'sleep':     (' It sits upright, yawns sleepily, then slowly lies down COMPLETELY on its '
                  'side: body fully horizontal on the ground, all four legs stretched out and '
                  'splayed apart in a deeply relaxed way, eyes closed, deep sleep with slow '
                  'gentle breathing, chest rising and falling, head resting on the ground, '
                  'mouth closed. It remains fully side-lying until the end.',
                  ', curled up into a ball, loaf position, sphinx position, paws tucked under '
                  'body, standing up at the end, getting back up, head up, mouth open, tongue '
                  'out, panting'),
    'bark':      (' It stands in an EXACT SIDE PROFILE VIEW facing right: muzzle points right, '\
                  'only ONE eye visible, tail on the left, four legs straight down and clearly '\
                  'separated, the two hind legs close together and parallel. It barks loudly '\
                  'several times while staying in profile: mouth opening and closing rhythmically '\
                  'with the muzzle still pointing right, head lifting slightly with each bark, '\
                  'body energetic. The head NEVER turns toward the camera.',
                  ', head turned to camera, looking at viewer, both eyes visible, facing camera, '\
                  'front view, three quarter view, splayed legs, wide stance, five legs, six '\
                  'legs, extra legs'),
    'lick':      (' It sits and grooms itself: turns its head to lick its own front paw and '
                  'shoulder fur with visible tongue movements, licks repeatedly in a natural '
                  'self-grooming rhythm, occasionally pausing and resuming.', ''),
    'happy':     (' It jumps up and down joyfully with excitement, wagging its tail rapidly, '
                  'bouncing in place.', ''),
    'roll':      (' Seen from the SIDE the whole time, it gently lies down on its side and '\
                  'rolls slowly onto its back for a relaxed happy wiggle with legs loosely in '\
                  'the air, then rolls back to its side and stands up again. The roll stays a '\
                  'gentle partial roll in the side plane, the puppy never turns its back to the '\
                  'camera and is never seen from behind, the body never twists into extreme '\
                  'contorted angles.',
                  ', back facing camera, seen from behind, butt facing camera, extreme twist, '\
                  'contorted body, unnatural twisted pose, spine twisted'),
    'dance':     (' It dances playfully on its hind legs, stepping and bouncing rhythmically '
                  'in place.', ''),
    'stretch':   (' It performs a full body stretch: lowering its front chest to the ground '
                  'with front paws extended forward, rear end up, then slowly standing back up.', ''),
    'beg':       (' It stands up on its hind legs, raising both front paws in a begging pose, '
                  'balancing gently and looking up expectantly.', ''),
    'bath':      (' It sits and gets washed, water splashing gently around it, shaking off '
                  'water with ripples.', ', hand, hands, fingers'),
    'surprised': (' It sits calmly facing the camera, then suddenly gets startled and reacts '
                  'surprised: ears perk straight up, eyes go wide open, mouth opens, head jerks '
                  'back slightly, body recoils and does a small hop, then stays sitting with a '
                  'wide-eyed alert surprised expression. NO human, NO hands, the puppy is '
                  'completely alone.', ', hand, hands, fingers, arm'),
    'play_dead': (' It flops down onto its side and lies completely still, pretending to be '
                  'dead with relaxed legs.', ''),
    'eat':       (' It stands in an EXACT SIDE PROFILE VIEW facing right: only ONE eye is '\
                  'visible, the tail extends to the left, the whole body seen strictly from the '\
                  'side at ALL times, the chest and face NEVER turn toward the camera, front '\
                  'legs vertical and parallel, hind legs close together. It lowers its head to '\
                  'the floor IN PROFILE: the muzzle points down-right and touches the white '\
                  'floor at floor level, still only one eye visible while eating. It eagerly '\
                  'eats kibble scattered on the white floor right in front of its chest, '\
                  'chewing and bobbing at floor level 80 percent of the time, lifting the head '\
                  'only briefly then returning to eat, tail wagging gently, body staying in the '\
                  'same spot. NO bowl, NO food bowl visible, pure white background.',
                  ', bowl, food bowl, dish, plate, front view, facing camera, both eyes '\
                  'visible, three quarter view, chest toward camera, front legs spread, splayed '\
                  'front legs, splayed legs, legs apart, wide stance, head up, looking around, '\
                  'standing alert, sniffing air, head turned to camera, looking at viewer'),
    # walk/run 侧面视角+跑步机范式:位置锁定但腿必须大幅完整步态(旧'in place'措辞
    # 被AI读成压制腿幅=原地踏步,v2修正)
    'walk':      (' It walks on a treadmill in a SIDEWAYS VIEW facing right, performing a FULL '\
                  'natural trot gait cycle with large clear strides: diagonal legs alternating, '\
                  'each paw lifting well off the ground, visible leg extension and fold every '\
                  'step, hind legs moving naturally and staying close under the body, brisk '\
                  'energetic walk, tail gently swaying, body holding the same screen position '\
                  'the whole time.',
                  ', front view, facing camera, standing still, static legs, stiff legs, locked '\
                  'legs, tiny steps, shuffling, legs together, splayed hind legs, twisted legs, '\
                  'unnatural legs, gray smudge, gray blob'),
    # run v5: v4的loop段幅度不足(前爪hop为主、缺完整伸展 strides)→"同一姿势循环"。
    # 改持续全速大步幅gallop, NEG hop/站立
    'run':       (' It runs at FULL SPEED in a SIDEWAYS VIEW facing right on the pure white '\
                  'studio floor, performing CONTINUOUS large-amplitude gallop strides without '\
                  'pause: every single stride the legs stretch far forward and far backward, '\
                  'a clear suspension moment with all four paws off the ground, then legs '\
                  'tucking under the body, stride after stride at the same big amplitude, '\
                  'powerful energetic sprint, ears and fur flowing, body holding the same '\
                  'screen position the whole time. The floor stays pure white and completely '\
                  'empty. The coat is clean uniform golden cream fur on every part of the body.',
                  ', front view, facing camera, standing still, standing, static legs, stiff '\
                  'legs, locked legs, tiny steps, shuffling, legs together, hopping, hop, '\
                  'bouncing in place, treadmill, belt, black strip, dark strip, platform, '\
                  'machine, prop, object on floor, gray smudge, gray blob, gray stripe'),
}
# 2026-08-17: 用户反馈roll/dance/sleep等开头站姿=旧奇怪后腿主体。idle/bark的修腿
# 措辞未覆盖其余含站立段的状态→统一追加(正+负)。
LEGS_POS = (' Whenever the puppy stands or rises on its legs, all four legs are straight down '\
            'and clearly separated, the two hind legs close together and parallel, never '\
            'splayed wide or twisted.')
LEGS_NEG = (', splayed legs, wide stance, legs apart, five legs, six legs, extra legs, '\
            'splayed hind legs, twisted legs, unnatural legs')
for _k in ('sleep', 'roll', 'dance', 'stretch', 'happy', 'beg', 'play_dead', 'eat'):
    _d, _n = ACTIONS[_k]
    ACTIONS[_k] = (_d + LEGS_POS, _n + LEGS_NEG)
# ══════════ CONFIG END ══════════

BASE = 'https://api.agnes-ai.cn/v1'
tok = bytes.fromhex(open(KEYHEX).read().strip()).decode()
HDR = {'Authorization': tok, 'Content-Type': 'application/json'}  # 裸key勿加Bearer

def submit(prompt, neg):
    img = base64.b64encode(open(REF_IMAGE, 'rb').read()).decode()
    r = requests.post(f'{BASE}/video/generations', headers=HDR, json={
        'model': 'agnes-video-v2.0', 'prompt': prompt, 'negative_prompt': neg,
        'image': f'data:image/png;base64,{img}',
        'num_frames': 121, 'frame_rate': 24}, timeout=180)
    if r.status_code != 200:
        return None, r.text[:300]
    d = r.json()
    return d.get('video_id') or d.get('task_id'), None

def poll(video_id, timeout_s=1800):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            d = requests.get('https://api.agnes-ai.cn/agnesapi', params={'video_id': video_id},
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
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    done = {f.replace('.mp4', '') for f in os.listdir(VIDEOS_DIR) if f.endswith('.mp4')}
    only = sys.argv[1:] or list(ACTIONS)
    n = len([x for x in only if x not in done])
    print(f'[start] {n} videos to generate', flush=True)
    k = 0
    for name in only:
        if name in done:
            print(f'[skip] {name} 已存在', flush=True); continue
        k += 1
        if k > 1:
            print('  ... waiting 70s for rate limit ...', flush=True)
            time.sleep(70)
        desc, extra_neg = ACTIONS[name]
        vid, err = submit(SUBJ + desc + COMMON, NEG_BASE + extra_neg)
        if not vid:
            print(f'[FAIL submit] {name}: {err}', flush=True); continue
        print(f'[submit] {name} video_id={vid}', flush=True)
        url, err = poll(vid)
        if not url:
            print(f'[FAIL poll] {name}: {err}', flush=True); continue
        r = requests.get(url, timeout=300)
        open(os.path.join(VIDEOS_DIR, name + '.mp4'), 'wb').write(r.content)
        print(f'  SAVED {name}.mp4 ({len(r.content)} bytes)', flush=True)
    print('VIDEOS_DONE', flush=True)
