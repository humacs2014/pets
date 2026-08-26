# -*- coding: utf-8 -*-
"""阶段2: 20 状态动作视频批量生成（Agnes ti2vid，labrador 最终验证版）。
新宠物: 改 CONFIG 段（SUBJ/REF_IMAGE/NEG_BREED），ACTIONS 动作措辞直接复用。
kiss/wave/type 三动作为 mochi(柴犬) v100/v102/v117 验证版移植（白底版措辞）。
顺序提交间隔>=70s防限流，每个提交后轮询至完成下载。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe regen_videos.py [状态名...]
"""
import sys, os, time, json, base64
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))

# ══════════ CONFIG（新宠物改这里） ══════════
KEYHEX = os.path.join(ROOT, 'keyhex.txt')
REF_IMAGE = os.path.join(ROOT, 'identity_ref_comp.png')  # 构图校正版v2: rembg净抠+纯白底+主体55%高（v1的40%身份锚太弱致画风不统一；旧版画布带原图米色背景致开头帧复制截图背景）
SUBJ = ('A fluffy adult white Samoyed dog EXACTLY identical to the dog in the reference image — '
        'same face, same body proportions, same thick pure white double coat: gentle smiling '
        'expression with slightly upturned black lips, erect triangular ears, dark almond-shaped '
        'eyes, black nose, plume tail curled over the back.')
VIDEOS_DIR = os.path.join(ROOT, 'videos')
NEG_BREED = 'golden retriever, labrador, husky, malamute, brown fur, black fur, gray fur, yellow fur, cream fur, chocolate color, floppy ears, short-haired, short coat'  # 品种/毛色排除词
# 毛色一致性子句（防 run 高速运动时毛色斑驳/色漂移）；新宠物按品种毛色改写
COAT_CLAUSE = ' The coat is clean uniform pure white thick double fur on every part of the body.'
# ══════════ CONFIG END ══════════

# COMMON 后缀（质量关键，逐字复用）。"lying down ≤55% frame width" 防躺姿撑满画面。
# v2: 主体占比 40%→55%（用户报各状态大小不一致：40%下身份锚太弱模型自由发挥），
# 并追加全片尺寸/画风锁定子句保证 17 个状态视觉统一。
COMMON = (' The subject stays perfectly centered in the same spot the whole time, not moving '\
          'forward at all. Extreme wide shot, the subject takes up about 55 percent of the '\
          'frame height — the SAME apparent size as in the reference image, exactly the same '\
          'size in every shot — with generous empty white space around it. Even when lying '\
          'down, the body never becomes wider than 55 percent of the frame width. Static '\
          'locked camera, pure white seamless studio background, soft even lighting, '\
          'photorealistic, sharp crisp fur detail, the same photorealistic style, the same '\
          'single dog throughout.')
NEG_BASE = ('cartoon, childish, ugly, extra legs, extra tail, deformed, mutated, subtitles, '\
            'watermark, text, logo, blurry, jittery, distorted, inconsistent appearance, '\
            'other animals, human, person, cropped, cut off, close up, zoomed in, filling frame, '\
            'large subject, moving forward, walking forward, changing position, '\
            'different dog, another dog, changed appearance, wrong breed, size change, '\
            'scale change, illustration, 3d render, cgi, animation style, anime, low quality, ' + NEG_BREED)

# ── kiss 专用 COMMON/NEG（mochi v102 移植，白底版）──
# kiss 需要"由远及近走近+脸部特写"，与通用 COMMON（禁止前进/55%恒定）和 NEG_BASE
# （moving forward/close up/size change）直接冲突，必须用独立措辞对。
COMMON_KISS = (' The ENTIRE background and floor is one UNIFORM SOLID pure white seamless studio '\
                'backdrop, with soft even lighting, photorealistic, sharp crisp fur detail, the '\
                'same photorealistic style, the same single dog throughout. Static locked camera '\
                'at the dog\'s eye level: the camera never moves or zooms; any change in subject '\
                'size comes ONLY from the dog walking closer to or farther from the camera.')
NEG_KISS = ('cartoon, childish, ugly, extra legs, extra tail, deformed, mutated, subtitles, '\
            'watermark, text, logo, blurry, jittery, distorted, inconsistent appearance, '\
            'other animals, human, person, '\
            'different dog, another dog, changed appearance, wrong breed, '\
            'illustration, 3d render, cgi, animation style, anime, low quality, ' + NEG_BREED)

# ── 动作措辞（labrador 验证版，逐字复用；侧面朝向与 walk/run 保持一致）──
ACTIONS = {
    # v73: idle 改正面朝向为主体（用户要求开屏正面迎向用户；旧严格侧视是防多腿的历史
    # 约束，现用"exactly four legs"+neg five/six legs 约束替代）。
    'idle':      (' It stands UPRIGHT in a FRONT VIEW facing the camera the whole time: the chest '\
                  'faces the viewer, both eyes visible, looking directly at the camera, head up '\
                  'and alert. Exactly four legs, all straight down: the two front legs vertical '\
                  'and parallel in the center, the two hind legs just visible at the sides, never '\
                  'splayed wide, belly well above the floor. The body stays facing the camera the '\
                  'whole time, gently swaying, occasional small ear twitches and slight head '\
                  'tilts, tail curled up visible at one side.',
                  ', side profile view, side view, profile view, muzzle pointing left, muzzle '\
                  'pointing right, lying down, lying, prone, crouching, belly on floor, sitting '\
                  'down, sitting, butt on floor, hindquarters on floor, legs apart, five legs, '\
                  'six legs, extra legs'),
    'sit':       (' It calmly sits down facing the camera within the first second and then REMAINS '
                  'SITTING for the entire rest of the video: butt firmly on the floor, hind legs '
                  'folded under the body, front legs straight down, tail curled around its paws, '
                  'chest up, breathing gently with occasional ear twitches. It never lies down, '
                  'never stretches out on the ground, never stands up and never moves from the '
                  'sitting pose.',
                  ', lying down, lying, prone, lying flat, belly on floor, stretching out on '
                  'ground, sprawling, standing up, getting up, rising, walking, moving around'),
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
                  'pausing and resuming. While grooming it ALWAYS rests on EXACTLY THREE legs '\
                  'on the ground (the raised paw never becomes an extra fifth leg): the two hind '\
                  'legs folded under the sitting body plus the ONE remaining front leg, never '\
                  'more than three contact points on the floor at any moment.',
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
    'stretch':   (' Seen in an EXACT SIDE PROFILE VIEW the whole time, it performs a full body '
                  'stretch: lowering its front chest to the ground with front paws extended '
                  'forward, rear end raised high, holding the stretch briefly, then slowly '
                  'standing back up. It never turns toward the camera and stays in side '
                  'profile the entire video.',
                  ', front view, facing camera, facing viewer, looking at camera, turning '
                  'toward camera'),
    'beg':       (' It stands up on its hind legs, raising both front paws in a begging pose, '\
                  'balancing gently and looking up expectantly. The ENTIRE body stays inside '\
                  'the frame at ALL times: the whole puppy from the top of the head to BOTH '\
                  'hind paws is fully visible with clear margin around it; the hind paws stay '\
                  'well above the bottom edge of the frame and never touch or leave it. While '\
                  'upright the body shows EXACTLY FOUR limbs total — the two raised front paws '\
                  'plus the two hind legs supporting the body — and never a fifth limb or any '\
                  'extra leg appears at any frame.',
                  ', feet cut off, paws out of frame, cropped feet, body cut by frame edge, '\
                  'cropped body, half body out of frame, body outside frame'),
    # bath v71: 针对v70源视频三缺陷重写——①毛发全干蓬松→湿毛贴服；②头顶泡沫白帽贴纸感→
    # 泡沫融化进湿毛软边过渡；③趴盆沿姿态→深坐盆中央泡沫线裹胸。
    'bath':      (' It sits DEEP INSIDE a small blue plastic baby bathtub placed on the white '\
                  'floor, the tub resting firmly on the floor. The tub is filled to the rim with '\
                  'thick soft white soap foam; the lower body and legs are fully submerged under '\
                  'the foam so only the chest, front legs and head rise above the foam line, the '\
                  'foam wrapping snugly around the chest like a soft white blanket. The fur is '
                  'VISIBLY WET everywhere: damp clumped strands sticking to the body, darker '
                  'soaked coat on the head, ears and back, clearly wet and sleek, never '
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
                  'chest, resting firmly on the floor at floor level; the bowl is small enough '\
                  'that its ENTIRE outline — full rim, both sides and bottom — stays COMPLETELY '\
                  'inside the frame with clear white margin around it at every single frame, '\
                  'never touching any frame edge. It lowers its head IN '\
                  'PROFILE and eats FROM the bowl: the muzzle goes down INTO the red bowl, the '\
                  'nose disappearing inside the bowl rim while chewing, head bobbing at bowl '\
                  'level 80 percent of the time, lifting the head only briefly with a piece of '\
                  'kibble in the mouth then returning into the bowl, tail wagging gently, the '\
                  'body and the bowl staying in the exact same spot the whole time.',
                  ', food scattered on floor, kibble on ground, eating from floor, licking '\
                  'floor, crumbs on floor, floating bowl, bowl in air, moving bowl, multiple '\
                  'bowls, giant bowl, oversized bowl, bowl cut off, bowl out of frame, bowl '\
                  'touching frame edge, partial bowl, empty floor, front view, facing camera, both eyes '\
                  'visible, three quarter view, chest toward camera, front legs spread, splayed '\
                  'front legs, splayed legs, legs apart, wide stance, head up, looking around, '\
                  'standing alert, sniffing air, head turned to camera, looking at viewer'),
    # walk/run: 跑步机/原地全速范式——位置锁定但腿必须大幅完整步态。
    # （旧'in place'措辞会被模型读成压制腿幅=原地踏步。）
    # v77: walk重生成——v76源视频狗真实横穿画面(质心漂移1648px)且折返，线性去趋势
    # 救不回(残差648→宽度钳制压死→仅268/560)。根因=模型把"walk"读成空间位移。
    # 强化位置锁定：显式"原地踏步/跑步机式/身体完全不横移"，neg增加折返/横移/换向。
    'walk':      (' ALREADY in a full EXACT SIDE PROFILE VIEW from the VERY FIRST FRAME (no '\
                  'front-facing approach, no turning toward the camera at any moment), the muzzle points to '\
                  'the right, only ONE eye is visible, the tail extends to the left. The camera '\
                  'sees the dog in a PERFECT 90-DEGREE SIDE PROFILE the ENTIRE video: the full length '\
                  'of the body from chest to tail is visible, the body silhouette looks WIDE and '\
                  'ELONGATED horizontally (clearly wider than tall), absolutely NO three-quarter '\
                  'view, NO oblique angle, NO chest or face turning toward the viewer at any '\
                  'moment. The dog looks exactly like the same Samoyed from the reference image '\
                  '— same face, same proportions, same photorealistic style as every other shot. The dog '\
                  'walks IN PLACE in the EXACT CENTER of the frame, like walking on a treadmill: '\
                  'ALL the movement is in the legs while the torso and body stay completely '\
                  'STATIONARY in the middle of the frame, never drifting left or right, never '\
                  'moving across the frame, never changing position or direction, always facing '\
                  'the same way to the right the whole time. It performs a FULL natural trot '\
                  'gait cycle with large clear strides: diagonal legs alternating, each paw '\
                  'lifting well off the ground, visible leg extension and fold every step, hind '\
                  'legs moving naturally and staying close under the body, brisk energetic walk, '\
                  'tail gently swaying. The head and back stay level and horizontal the entire '\
                  'time; the dog stays UPRIGHT on all four straight legs, chest high, belly well '\
                  'above the floor. The dog keeps WALKING CONTINUOUSLY without stopping: no '\
                  'pausing, no standing still, no sitting, no hopping, every single frame of the '\
                  'video shows active stride motion with legs swinging, from the first frame to '\
                  'the last frame, an unbroken rhythmic trot.',
                  ', front view, facing camera, standing still, static legs, stiff legs, locked '\
                  'legs, tiny steps, shuffling, legs together, splayed hind legs, twisted legs, '\
                  'unnatural legs, moving across the frame, drifting right, drifting left, '\
                  'moving left, moving right, turning back, turning around, changing direction, '\
                  'walking backward, horizontal drift, position shifting, traveling, gray smudge, '\
                  'gray blob, treadmill, belt, black strip, dark '\
                  'strip, platform, machine, equipment, prop, object on floor, lying down, lying, '\
                  'prone, crouching, belly on floor, chest on floor, sitting down, head down, '\
                  'head lowered, butt up, rear raised, play bow, bowing, sniffing floor, nose to '\
                  'floor, head turned to camera, looking at viewer, both eyes visible, stopping, '\
                  'pause, paused, standing up, standing upright, standing, hop, hopping, jumping, '\
                  'jump, bouncing, freeze, frozen, idle, resting, waiting'),
    'run':       (' It runs at FULL SPEED in an EXACT SIDE PROFILE VIEW facing right: the muzzle '\
                  'points to the right, only ONE eye is visible, the tail extends to the left. It '\
                  'looks exactly like the same Samoyed from the reference image — same face, same '\
                  'proportions, same photorealistic style as every other shot. On '\
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
    # ── 以下三动作为 mochi(柴犬) v100/v102/v117 验证版移植（用户要求与旧项目动作集一致）──
    # 亲亲我（mochi v102）：由远及近走向镜头→脸凑近舔镜头→稍退。用独立 COMMON_KISS/NEG_KISS
    # （允许走近+特写），见 __main__ 分发。
    'kiss':      (' The video starts with the dog FAR from the camera: a small full-body Samoyed '\
                  'taking up about 25 percent of the frame height, with lots of empty white '\
                  'floor and backdrop around it. Then it WALKS DIRECTLY TOWARD THE CAMERA with a '\
                  'happy bouncy trot, growing MUCH BIGGER frame after frame across the whole '\
                  'video, until its muzzle and face become a LARGE CLOSE-UP taking about 70 '\
                  'percent of the frame height, face proportions and ear size staying perfectly '\
                  'natural. At the closest point it gives several affectionate licks toward the '\
                  'camera lens: the pink tongue VISIBLY EXTENDS reaching out and licking toward '\
                  'the viewer in a kissing motion, eyes warm and loving, ears perked. After the '\
                  'kisses it steps back to medium distance and wags its plume tail happily.' + COAT_CLAUSE,
                  ', sitting the whole time, never approaching, staying far away, same size '\
                  'forever, turning away, back to camera, lying down, lying, prone, closed mouth '\
                  'forever, tongue hidden, head down, sniffing floor, side view, profile view'),
    # 挥挥手（mochi v100）：坐姿正面+反复抬一只前爪左右挥。
    'wave':      (' It sits calmly facing the camera the whole time: butt firmly on the floor, '\
                  'chest up, looking directly at the viewer with bright friendly eyes, tail '\
                  'wagging. Then it raises ONE front paw high up beside its head and waves it '\
                  'side to side toward the viewer in a friendly waving hello gesture: the paw is '\
                  'clearly lifted off the floor and swings left and right several times, then '\
                  'lowers briefly and raises again to wave once more, head slightly tilted, '\
                  'expression cheerful. The other three legs stay firmly on the floor. It never '\
                  'stands up and never leaves its sitting spot.',
                  ', standing up, standing, walking, moving around, turning away, back to '\
                  'camera, lying down, lying, prone, both paws raised, two paws in air, begging '\
                  'with both paws, head down, sniffing floor'),
    # 敲键盘（mochi v100/v104）：小型复古机械键盘马卡龙色圆键帽。视频模型对"小狗敲键盘"有
    # 圆珠先验——prompt 顺势引导马卡龙圆键帽而非压制；帧阶段另有 make_keyboard 合成兜底。
    'type':      (' It sits behind a SMALL RETRO mechanical computer keyboard with ROUND '\
                  'MACARON-COLORED keycaps: the keycaps are soft pastel colored circles (mint '\
                  'green, baby blue, pale pink, cream) arranged in NEAT EVEN ROWS on a cream '\
                  'beige keyboard base, exactly like a vintage macaron keyboard. The keyboard is '\
                  'SMALLER than the dog, about 60 percent of the dog body width, placed right in '\
                  'front of its chest on the pure white studio floor, the keycap rows facing '\
                  'TOWARD THE DOG like a person sitting at a desk. Both front paws rest on the '\
                  'nearest keycap rows and ALTERNATE PRESSING THE KEYS in a clear rhythmic '\
                  'left-right-left-right tapping: one paw presses down while the other lifts '\
                  'slightly, then they swap, a visible gentle typing bounce several times per '\
                  'second, head slightly lowered watching the keys with a happy focused '\
                  'expression, pink tongue slightly out, tail wagging gently. The FACE AND EYES '\
                  'stay PERFECTLY STABLE in every frame: the eye shape, eye size, pupil position '\
                  'and the white catchlight highlight inside each eye stay IDENTICAL frame after '\
                  'frame, only a rare slow natural blink, no eye flicker, no shimmering eyes, no '\
                  'shifting catchlights. The dog body stays CALM AND MOSTLY STILL: no big '\
                  'bouncing, no head swinging, only the small alternating paw tapping motion. '\
                  'The keyboard and EVERY keycap stay PERFECTLY STATIC AND IDENTICAL in every '\
                  'single frame: no morphing, no keys appearing or disappearing, the keyboard '\
                  'never moves, the keycaps stay perfectly round and evenly spaced like beads on '\
                  'a clean grid. The dog stays in the same spot the entire video.' + COAT_CLAUSE,
                  ', keyboard reversed, keyboard upside down, keycaps facing camera away from '\
                  'dog, puppy at the far edge of the keyboard, paws on the far row, keyboard '\
                  'moving, sliding keyboard, floating keyboard, multiple keyboards, giant '\
                  'keyboard, keyboard bigger than the dog, keyboard wider than the dog, plain '\
                  'white keycaps, rectangular keycaps, morphing keyboard, changing key layout, '\
                  'flickering keys, scattered random beads, keys melting together, keys appearing '\
                  'and disappearing, paws off keyboard, paws in air, big bouncing, wild head '\
                  'swinging, exaggerated motion, standing up, walking, turning away, back to '\
                  'camera, lying down on keyboard, chewing keyboard, biting keyboard, flickering '\
                  'eyes, shimmering eyes, changing eye shape, shifting catchlights, sparkling '\
                  'changing eyes, frozen paws, static paws, motionless paws, paws not moving'),
}
# 站姿腿约束统一追加到所有含站立段的状态（防开头"奇怪后腿"主体）：
# 只修被点名的状态=下一轮其他状态仍报同样问题，必须全覆盖。
LEGS_POS = (' Whenever the puppy stands or rises on its legs, all four legs are straight down '\
            'and clearly separated, the two hind legs close together and parallel, never '\
            'splayed wide or twisted.')
LEGS_NEG = (', splayed legs, wide stance, legs apart, five legs, six legs, extra legs, '\
            'splayed hind legs, twisted legs, unnatural legs')
for _k in ('sleep', 'roll', 'dance', 'stretch', 'happy', 'play_dead', 'eat'):
    _d, _n = ACTIONS[_k]
    ACTIONS[_k] = (_d + LEGS_POS, _n + LEGS_NEG)
# lick/beg: 抬腿姿态与 LEGS_POS"四腿垂直向下"矛盾会诱导第五腿——只加 NEG（desc 自带腿数约束）
for _k in ('lick', 'beg'):
    _d, _n = ACTIONS[_k]
    ACTIONS[_k] = (_d, _n + LEGS_NEG)
# wave: 坐姿抬单爪（与 beg 同类抬爪姿态）——只加 NEG 防第五腿
_d, _n = ACTIONS['wave']
ACTIONS['wave'] = (_d, _n + LEGS_NEG)

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
    # 覆盖模式（用户要求）：重生成直接覆盖旧视频，便于对比源视频质量；不做已存在跳过。
    only = sys.argv[1:] or list(ACTIONS)
    n = len(only)
    print(f'[start] {n} videos to generate (overwrite mode)', flush=True)
    k = 0
    for name in only:
        k += 1
        if k > 1:
            print('  ... waiting 70s for rate limit ...', flush=True)
            time.sleep(70)
        desc, extra_neg = ACTIONS[name]
        if name == 'kiss':
            # kiss 专用措辞对：允许走近+特写（通用 COMMON/NEG_BASE 与之冲突）
            prompt = SUBJ + desc + COMMON_KISS
            neg = NEG_KISS + extra_neg
        else:
            prompt = SUBJ + desc + COMMON
            neg = NEG_BASE + extra_neg
        if name == 'pet':
            # 摸摸头互动必须有人手出现——豁免 NEG_BASE 的 human/person 排除词
            neg = neg.replace('human, person, ', '').replace(', human, person', '')
        vid, err = submit(prompt, neg)
        for _retry in range(6):
            if vid: break
            print(f'  [retry {_retry+1}/6] submit failed: {err[:120]} — waiting 75s', flush=True)
            time.sleep(75)
            vid, err = submit(prompt, neg)
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
