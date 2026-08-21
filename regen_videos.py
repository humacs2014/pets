# -*- coding: utf-8 -*-
"""阶段2: 16 状态动作视频批量生成（Agnes ti2vid，labrador 最终验证版）。
新宠物: 改 CONFIG 段（SUBJ/REF_IMAGE/NEG_BREED），ACTIONS 动作措辞直接复用。
顺序提交间隔>=70s防限流，每个提交后轮询至完成下载。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe regen_videos.py [状态名...]
"""
import sys, os, time, json, base64
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))

# ══════════ CONFIG（新宠物改这里） ══════════
KEYHEX = os.path.join(ROOT, 'keyhex.txt')
REF_IMAGE = os.path.join(ROOT, 'identity_candidates', 'cand_0.png')  # 身份图铁律: 必须四腿站立+3/4身(对齐拉布拉多认可版cand_0范式), 坐姿/趴姿身份图会带偏所有视频姿态
SUBJ = 'A tiny cute fluffy Golden Retriever puppy with warm brown eyes and soft floppy ears.'
VIDEOS_DIR = os.path.join(ROOT, 'videos')
NEG_BREED = 'adult dog, short-haired, short coat, labrador, husky, gray fur, black fur, chocolate color'  # 品种/毛色排除词
# 毛色一致性子句（防 run 高速运动时毛色斑驳/色漂移）；新宠物按品种毛色改写
COAT_CLAUSE = ' The coat is clean uniform golden cream long fur on every part of the body.'
# ══════════ CONFIG END ══════════

# COMMON 后缀（质量关键，逐字复用）。"lying down ≤55% frame width" 防躺姿撑满画面。
COMMON = (' The subject stays perfectly centered in the same spot the whole time, not moving '\
          'forward at all. Extreme wide shot, the subject takes up less than 40 percent of the '\
          'frame height with lots of empty white space around it. Even when lying down, the '\
          'body never becomes wider than 55 percent of the frame width. Static locked camera, '\
          'pure white seamless studio background, soft even lighting, photorealistic, sharp '\
          'crisp fur detail.')
NEG_BASE = ('cartoon, childish, ugly, extra legs, extra tail, deformed, mutated, subtitles, '\
            'watermark, text, logo, blurry, jittery, distorted, inconsistent appearance, '\
            'other animals, human, person, cropped, cut off, close up, zoomed in, filling frame, '\
            'large subject, moving forward, walking forward, changing position, ' + NEG_BREED)

# ── 动作措辞（labrador 验证版，逐字复用；侧面朝向与 walk/run 保持一致）──
ACTIONS = {
    # idle/bark/eat 严格侧视 + 站姿腿约束（防 3/4 正面张腿"多腿"主体）
    'idle':      (' It stands UPRIGHT in an EXACT SIDE PROFILE VIEW facing right: the muzzle '\
                  'points to the right, only ONE eye is visible, the tail extends to the left. '\
                  'All four legs straight down and clearly separated, the two hind legs close '\
                  'together and parallel, never splayed wide, chest high and belly well above '\
                  'the floor the whole time. The head stays in profile the whole time: it looks '\
                  'around by turning slightly within the side plane only, NEVER turning toward '\
                  'the camera, occasional small ear twitches, gently swaying. The body NEVER '\
                  'turns to a front or three-quarter view, the chest never faces the camera.',
                  ', head turned to camera, looking at viewer, both eyes visible, facing camera, '\
                  'front view, three quarter view, chest toward camera, splayed legs, wide '\
                  'stance, lying down, lying, prone, crouching, belly on floor, sitting down, '\
                  'sitting, butt on floor, hindquarters on floor, legs apart, five legs, six '\
                  'legs, extra legs'),
    'sit':       (' It calmly sits down facing the camera, tail curled around its paws, '\
                  'breathing gently with occasional ear twitches.', ''),
    # sleep: 全程侧视 + 紧凑蜷缩（头低/腿收/身体小），防大体型和平铺。
    # 开头仍可能出现正面站/坐过渡帧 → 抽帧阶段用 _front_standing 剔除。
    'sleep':     (' Seen in an EXACT SIDE PROFILE VIEW the whole time, it sits down compactly '\
                  'with the hind legs tucked under the body, yawns sleepily, then slowly curls '\
                  'down into a compact relaxed ball on the ground: legs folded CLOSE under the '\
                  'body, tail wrapped around, head resting low, the lying body small and '\
                  'compact. Eyes closed, deep sleep with slow gentle breathing, chest rising '\
                  'and falling. It remains curled and compact until the end.',
                  ', splayed legs, legs stretched out wide, legs apart, wide stance, body '\
                  'stretched out long, sprawling flat, lying elongated, front view, facing '\
                  'camera, both eyes visible, chest toward camera, standing up at the end, '\
                  'getting back up, head up, mouth open, tongue out, panting'),
    'bark':      (' It stands UPRIGHT on all four straight legs in an EXACT SIDE PROFILE VIEW '\
                  'facing right: muzzle points right, only ONE eye visible, tail on the left, '\
                  'four legs straight down and clearly separated, the two hind legs close '\
                  'together and parallel. It barks loudly several times while staying upright in '\
                  'profile: mouth wide open and closing rhythmically with the muzzle still '\
                  'pointing right, head lifting slightly with each bark, body energetic, chest '\
                  'high, belly well above the floor. The head NEVER turns toward the camera.',
                  ', head turned to camera, looking at viewer, both eyes visible, facing camera, '\
                  'front view, three quarter view, splayed legs, wide stance, five legs, six '\
                  'legs, extra legs, lying down, lying, prone, crouching, belly on floor, chest '\
                  'on floor, sitting down, sitting, closed mouth, mouth shut'),
    'lick':      (' It sits and grooms itself in a natural self-cleaning pose: it raises ONE '\
                  'front paw close to its chest, bends its head DOWN so the open mouth is pressed '\
                  'right against the raised paw, and the pink tongue VISIBLY TOUCHES and strokes '\
                  'the paw fur, licking the paw repeatedly. Then it turns its head sideways and '\
                  'buries the muzzle into the shoulder and side fur, tongue extended and clearly '\
                  'in contact with the coat, licking the shoulder and flank fur with rhythmic '\
                  'tongue movements. The mouth and tongue always stay in physical contact with '\
                  'the body or paw while licking, no gap between tongue and fur, occasionally '\
                  'pausing and resuming.',
                  ', licking the air, tongue not touching body, mouth away from body, gap '\
                  'between mouth and fur, paw raised away from mouth, waving paw, panting with '\
                  'head up, tongue hanging out'),
    'happy':     (' It hops up and down joyfully in place with a gentle SLOW bounce, seen in an '
                  'EXACT SIDE PROFILE VIEW facing right the whole time (muzzle right, one eye '
                  'visible, tail left), wagging its tail rapidly, all four legs clearly defined, '
                  'crisp sharp fur texture, slow smooth graceful motion, staying compact in one '
                  'spot.',
                  ', motion blur, blurry, soft focus, out of focus, smeared fur, fast frantic '
                  'motion, head turned to camera, both eyes visible, facing camera, front view, '
                  'three quarter view'),
    'roll':      (' Seen from the SIDE the whole time, it gently lies down on its side and '\
                  'rolls slowly onto its back for a relaxed happy wiggle with legs loosely in '\
                  'the air, then rolls back to its side and stands up again. The roll stays a '\
                  'gentle partial roll in the side plane, the puppy never turns its back to the '\
                  'camera and is never seen from behind, the body never twists into extreme '\
                  'contorted angles.',
                  ', back facing camera, seen from behind, butt facing camera, extreme twist, '\
                  'contorted body, unnatural twisted pose, spine twisted'),
    'dance':     (' It dances playfully BALANCED UPRIGHT on its hind legs the whole time, body '\
                  'vertical with chest high and both front paws raised waving in the air, '\
                  'stepping and bouncing rhythmically in place. It never lies down, its belly '\
                  'never touches the floor.',
                  ', lying down, lying, prone, belly on floor, chest on floor, crouching, '\
                  'sitting down, sitting'),
    'stretch':   (' It performs a full body stretch: lowering its front chest to the ground '\
                  'with front paws extended forward, rear end up, then slowly standing back up.', ''),
    'beg':       (' It stands up on its hind legs, raising both front paws in a begging pose, '\
                  'balancing gently and looking up expectantly. The ENTIRE body stays inside '\
                  'the frame at ALL times: the whole puppy from the top of the head to BOTH '\
                  'hind paws is fully visible with clear margin around it; the hind paws stay '\
                  'well above the bottom edge of the frame and never touch or leave it.',
                  ', feet cut off, paws out of frame, cropped feet, body cut by frame edge, '\
                  'cropped body, half body out of frame, body outside frame'),
    # bath v71: 针对v70源视频三缺陷重写——①毛发全干蓬松→湿毛贴服；②头顶泡沫白帽贴纸感→
    # 泡沫融化进湿毛软边过渡；③趴盆沿姿态→深坐盆中央泡沫线裹胸。
    'bath':      (' It sits DEEP INSIDE a small blue plastic baby bathtub placed on the white '\
                  'floor, the tub resting firmly on the floor. The tub is filled to the rim with '\
                  'thick soft white soap foam; the lower body and legs are fully submerged under '\
                  'the foam so only the chest, front legs and head rise above the foam line, the '\
                  'foam wrapping snugly around the chest like a soft white blanket. The fur is '\
                  'VISIBLY WET everywhere: damp clumped strands sticking to the body, darker '\
                  'soaked golden coat on the head, ears and back, clearly wet and sleek, never '\
                  'dry or fluffy. The foam clings to the wet fur and melts softly into it: a '\
                  'soft foam mound on top of the head blends into the damp hair with soft blurry '\
                  'edges, and a few small foam patches on the back and chest fade gradually into '\
                  'the wet coat, no hard outline anywhere. It wiggles gently in the foam, the '\
                  'foam surface rippling softly, then shakes its head once sending tiny water '\
                  'droplets flying, the blue tub and the foam staying in the exact same spot the '\
                  'whole time.',
                  ', dry fur, fluffy dry coat, standing dry fur, foam hat, white cap on '\
                  'head, foam sticker, hard-edged foam patch, detached foam, floating foam '\
                  'clumps, paws on tub rim, front paws over rim, leaning on rim, lying on rim, '\
                  'empty tub, no foam, no bubbles, dry body, hand, hands, fingers, person, '\
                  'human, floating tub, moving tub, multiple tubs, giant tub',),
    # pet=独立摸摸头互动（菜单"摸摸头"专用，与舔毛lick严格区分）：人手从上方轻抚头顶，
    # 小狗闭眼享受+摇尾。neg 需豁免 NEG_BASE 的 human/person（手必须出现）。
    'pet':       (' It sits calmly in a gentle three-quarter view, eyes closed with a content '\
                  'relaxed happy expression, tail wagging. A single human hand reaches in from '\
                  'above and slowly strokes the top of its head and between its ears in repeated '\
                  'gentle petting motions; the puppy leans its head into the palm, enjoying the '\
                  'petting, ears relaxing back, tail wagging faster with joy, body staying compact '\
                  'in the same spot the whole time.',
                  ', biting hand, licking hand, mouth open, teeth, fearful, scared, cowering, '\
                  'aggressive, growling, two hands, multiple hands, hand under chin'),
    'surprised': (' It sits calmly facing the camera, then suddenly gets startled and reacts '\
                  'surprised: ears perk straight up, eyes go wide open, mouth opens, head jerks '\
                  'back slightly, body recoils and does a small hop, then stays sitting with a '\
                  'wide-eyed alert surprised expression. NO human, NO hands, the puppy is '\
                  'completely alone.', ', hand, hands, fingers, arm'),
    'play_dead': (' It flops down onto its side and lies completely still, pretending to be '\
                  'dead with relaxed legs.', ''),
    # eat = 模型原生渲染红碗 + 嘴入碗（铁律：道具交互动作必须模型原生渲染，
    # 禁"无碗视频+后贴碗sprite"路线——碗悬空/嘴舔地/粮渣永远不自然）。
    # 朝向与 walk/run 侧面一致。
    'eat':       (' It stands in an EXACT SIDE PROFILE VIEW facing right: only ONE eye is '\
                  'visible, the tail extends to the left, the whole body seen strictly from the '\
                  'side at ALL times, the chest and face NEVER turn toward the camera, front '\
                  'legs vertical and parallel, hind legs close together. A small red plastic '\
                  'food bowl filled with kibble sits on the white floor right in front of its '\
                  'chest, resting firmly on the floor at floor level. It lowers its head IN '\
                  'PROFILE and eats FROM the bowl: the muzzle goes down INTO the red bowl, the '\
                  'nose disappearing inside the bowl rim while chewing, head bobbing at bowl '\
                  'level 80 percent of the time, lifting the head only briefly with a piece of '\
                  'kibble in the mouth then returning into the bowl, tail wagging gently, the '\
                  'body and the bowl staying in the exact same spot the whole time.',
                  ', food scattered on floor, kibble on ground, eating from floor, licking '\
                  'floor, crumbs on floor, floating bowl, bowl in air, moving bowl, multiple '\
                  'bowls, giant bowl, empty floor, front view, facing camera, both eyes '\
                  'visible, three quarter view, chest toward camera, front legs spread, splayed '\
                  'front legs, splayed legs, legs apart, wide stance, head up, looking around, '\
                  'standing alert, sniffing air, head turned to camera, looking at viewer'),
    # walk/run: 跑步机/原地全速范式——位置锁定但腿必须大幅完整步态。
    # （旧'in place'措辞会被模型读成压制腿幅=原地踏步。）
    'walk':      (' It walks in an EXACT SIDE PROFILE VIEW facing right: the muzzle points to '\
                  'the right, only ONE eye is visible, the tail extends to the left. It walks on '\
                  'the pure white studio floor, performing a FULL natural trot gait cycle with '\
                  'large clear strides: diagonal legs alternating, each paw lifting well off the '\
                  'ground, visible leg extension and fold every step, hind legs moving naturally '\
                  'and staying close under the body, brisk energetic walk, tail gently swaying, '\
                  'body holding the same screen position the whole time. The head and back stay '\
                  'level and horizontal the entire time; the dog stays UPRIGHT on all four '\
                  'straight legs, chest high, belly well above the floor.',
                  ', front view, facing camera, standing still, static legs, stiff legs, locked '\
                  'legs, tiny steps, shuffling, legs together, splayed hind legs, twisted legs, '\
                  'unnatural legs, gray smudge, gray blob, treadmill, belt, black strip, dark '\
                  'strip, platform, machine, equipment, prop, object on floor, lying down, lying, '\
                  'prone, crouching, belly on floor, chest on floor, sitting down, head down, '\
                  'head lowered, butt up, rear raised, play bow, bowing, sniffing floor, nose to '\
                  'floor, head turned to camera, looking at viewer, both eyes visible'),
    'run':       (' It runs at FULL SPEED in an EXACT SIDE PROFILE VIEW facing right: the muzzle '\
                  'points to the right, only ONE eye is visible, the tail extends to the left. On '\
                  'the pure white studio floor it performs CONTINUOUS large-amplitude gallop '\
                  'strides without pause: every single stride the legs stretch far forward and '\
                  'far backward, a clear suspension moment with all four paws off the ground, '\
                  'then legs tucking under the body, stride after stride at the same big '\
                  'amplitude, powerful energetic sprint, ears and fur flowing, body holding the '\
                  'same screen position the whole time. The head and back stay level and '\
                  'horizontal the entire time. The floor stays pure white and completely '\
                  'empty.' + COAT_CLAUSE,
                  ', front view, facing camera, standing still, standing, static legs, stiff '\
                  'legs, locked legs, tiny steps, shuffling, legs together, hopping, hop, '\
                  'bouncing in place, treadmill, belt, black strip, dark strip, platform, '\
                  'machine, prop, object on floor, gray smudge, gray blob, gray stripe, head '\
                  'down, head lowered to floor, butt up, rear raised, play bow, bowing, '\
                  'stretching down, sniffing floor, sniffing ground, nose to floor, lying down, '\
                  'lying, prone, sitting down, head turned to camera, looking at viewer, both '\
                  'eyes visible'),
}
# 站姿腿约束统一追加到所有含站立段的状态（防开头"奇怪后腿"主体）：
# 只修被点名的状态=下一轮其他状态仍报同样问题，必须全覆盖。
LEGS_POS = (' Whenever the puppy stands or rises on its legs, all four legs are straight down '\
            'and clearly separated, the two hind legs close together and parallel, never '\
            'splayed wide or twisted.')
LEGS_NEG = (', splayed legs, wide stance, legs apart, five legs, six legs, extra legs, '\
            'splayed hind legs, twisted legs, unnatural legs')
for _k in ('sleep', 'roll', 'dance', 'stretch', 'happy', 'beg', 'play_dead', 'eat'):
    _d, _n = ACTIONS[_k]
    ACTIONS[_k] = (_d + LEGS_POS, _n + LEGS_NEG)

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
        neg = NEG_BASE + extra_neg
        if name == 'pet':
            # 摸摸头互动必须有人手出现——豁免 NEG_BASE 的 human/person 排除词
            neg = neg.replace('human, person, ', '').replace(', human, person', '')
        vid, err = submit(SUBJ + desc + COMMON, neg)
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
