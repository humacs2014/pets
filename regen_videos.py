# -*- coding: utf-8 -*-
"""阶段2: 20状态动作视频批量生成（Agnes ti2vid，金毛+Hoopet背心版）。
金毛幼犬全程穿着Hoopet背心：奶油立领+棕色羊羔绒+黑色拉链+黄色拉绳。
新宠物: CONFIG段(SUBJ/REF_IMAGE/NEG_BREED/COAT_CLAUSE)已定制，ACTIONS动作措辞复用验证版。
用法: env -u PYTHONPATH -u PYTHONHOME <anaconda>/python.exe regen_videos.py [状态名...]
"""
import sys, os, time, json, base64
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))

# ══════════ CONFIG（金毛+Hoopet背心） ══════════
KEYHEX = os.path.join(ROOT, 'keyhex.txt')
# 双参考图：正面朝向用cand_0，侧面朝向用cand_2
# 两图主体高度一致（~40%画布高），确保所有视频体型统一
REF_IMAGE_FRONT = os.path.join(ROOT, 'identity_ref_front.png')
REF_IMAGE_SIDE = os.path.join(ROOT, 'identity_ref_side.png')
REF_IMAGE = REF_IMAGE_FRONT  # 默认用正面（给submit函数做fallback）

# 正面朝向状态使用正面参考图，侧面朝向状态使用侧面参考图
FRONT_VIEW_STATES = {'idle', 'sit', 'dance', 'beg', 'surprised', 'wave', 'pet', 'kiss'}
SIDE_VIEW_STATES = {'bark', 'eat', 'walk', 'run', 'sleep', 'lick', 'happy', 'roll', 'stretch', 'play_dead'}
# type 使用专用首帧锚定图（type_firstframe.png）
# SUBJ: 全局统一逐字复用。金毛奶犬+Hoopet背心，所有动作必须穿着。
# 核心教训：SUBJ 必须简洁（原版金毛仅15词就生成完美奶犬），过度描述反而干扰模型
SUBJ = (
    'A tiny cute chubby short-legged Golden Retriever puppy with a round barrel-shaped body, '
    'warm brown eyes, a solid black nose, soft floppy pendant ears, '
    'straight smooth golden cream fur (never curly or wavy). '
    'The puppy ALWAYS wears a fitted pet vest at ALL times: '
    'cream off-white stand-up collar with bright yellow inner lining, '
    'brown sherpa fleece lower body, black center zipper, '
    'yellow drawstring cords with black toggles, yellow webbing D-ring on back. '
    'The vest stays on the puppy the entire time, never removed, never changing.'
)
VIDEOS_DIR = os.path.join(ROOT, 'videos')
NEG_BREED = (
    'adult dog, mature dog, short-haired, short coat, labrador, husky, samoyed, pomeranian, '
    'curly fur, wavy fur, frizzy fur, wire-haired, '
    'stretched tall, thin body, elongated body, long thin legs, skinny dog, tall dog, '
    'narrow chest, narrow body, long legs, '
    'different dog, changed appearance, wrong breed, '
    'collar, leash, naked dog, dog without vest, dog without clothes, red bandana, bandana, '
    'vest disappearing, vest removed, vest changing color, vest changing shape'
)
COAT_CLAUSE = ' The coat is clean uniform golden cream on every part of the body. The vest stays on at all times.'
# ══════════ CONFIG END ══════════

# COMMON 后缀（质量关键，逐字复用）
COMMON = (' The subject stays perfectly centered in the same spot the whole time, not moving '
          'forward at all. The ENTIRE body from the tip of the ears to the bottom of all four '
          'paws is fully visible inside the frame at ALL times with generous empty margin — '
          'no cropping, no cut-off paws, no half body. Extreme wide shot, the subject takes up '
          'less than 40 percent of the frame height with lots of empty white space around it. '
          'Even when lying down, the body never becomes wider than 55 percent of the frame width. '
          'Static locked camera, pure white seamless studio background, soft even lighting, '
          'photorealistic, sharp crisp fur detail.')
NEG_BASE = ('cartoon, childish, ugly, extra legs, extra tail, deformed, mutated, subtitles, '
            'watermark, text, logo, blurry, jittery, distorted, inconsistent appearance, '
            'other animals, human, person, cropped, cut off, close up, zoomed in, filling frame, '
            'large subject, moving forward, walking forward, changing position, ' + NEG_BREED)

# roll专用COMMON（深灰背景让rembg能精确区分白毛和背景——纯白/浅灰都不够）
COMMON_ROLL = (' The subject stays perfectly centered in the same spot the whole time, not moving '
               'forward at all. The ENTIRE body from the tip of the ears to the bottom of all four '
               'paws is fully visible inside the frame at ALL times with generous empty margin — '
               'no cropping, no cut-off paws, no half body. Extreme wide shot, the subject takes up '
               'less than 40 percent of the frame height with lots of empty space around it. Even when '
               'lying down, the body never becomes wider than 55 percent of the frame width. Static '
               'locked camera, LIGHT GRAY seamless studio background (clearly distinct from the '
               'golden cream fur), soft even lighting, photorealistic, sharp crisp fur detail.')

# walk专用COMMON（删除"not moving forward"——walk需要真实步态位移，相机跟随保持居中）
COMMON_WALK = (' The ENTIRE body from the tip of the ears to the bottom of all four '
               'paws is fully visible inside the frame at ALL times with generous empty margin — '
               'no cropping, no cut-off paws, no half body. Extreme wide shot, the subject takes up '
               'less than 40 percent of the frame height with lots of empty white space around it. '
               'The camera pans smoothly at the same speed as the dog, keeping the dog centered in '
               'the frame at all times. Static locked camera height, pure white seamless studio '
               'background, soft even lighting, photorealistic, sharp crisp fur detail.')

# kiss专用措辞（必须独立，与通用COMMON/NEG_BASE冲突：kiss需要走近+特写）
COMMON_KISS = (' The ENTIRE background and floor is one UNIFORM SOLID pure white seamless studio '
               'backdrop, with soft even lighting, photorealistic, sharp crisp fur detail. '
               'Static locked camera at the dog\'s eye level: the camera never moves or zooms; '
               'any change in subject size comes ONLY from the dog walking closer to or farther '
               'from the camera.')
NEG_KISS = ('cartoon, childish, ugly, extra legs, extra tail, deformed, mutated, subtitles, '
            'watermark, text, logo, blurry, jittery, distorted, inconsistent appearance, '
            'other animals, human, person, '
            'different dog, another dog, changed appearance, wrong breed, '
            'illustration, 3d render, cgi, animation style, anime, low quality, ' + NEG_BREED)

# ── 动作措辞（labrador验证版，逐字复用；侧面朝向与walk/run保持一致）──
ACTIONS = {
    'idle':      (' TINY PUPPY SEEN FROM VERY FAR AWAY, extreme wide shot. It stands UPRIGHT '
                  'facing the camera the whole time, gently swaying '
                  'with occasional small ear twitches, tail curled up. Both eyes visible, '
                  'looking directly at the camera. The body is SHORT and COMPACT with a round '
                  'chubby barrel-shaped chest and belly, a typical baby puppy build. Four legs '
                  'straight down, belly well above the floor. '
                  'CRITICAL SIZE CONSTRAINT: the entire dog is VERY SMALL in the frame, taking up '
                  'less than 35 percent of the frame height, with LOTS of empty white space above '
                  'the head and below the paws. The ears, all four paws and the tail tip are ALL '
                  'fully visible inside the frame with generous margin. The paws never touch or '
                  'leave the bottom edge, the ears never touch the top edge.',
                  ', side profile view, side view, profile view, '
                  'lying down, lying, prone, crouching, belly on floor, sitting '
                  'down, sitting, butt on floor, hindquarters on floor, legs apart, five legs, '
                  'six legs, extra legs, slim, lean, '
                  'stretched tall, thin body, elongated body, long thin legs, '
                  'skinny dog, tall dog, narrow chest, narrow body, '
                  'feet cut off, paws out of frame, cropped feet, body cut by frame edge, '
                  'cropped body, half body out of frame'),
    'sit':       (' TINY PUPPY SEEN FROM VERY FAR AWAY, extreme wide shot. It calmly sits down facing the camera within the first second and then REMAINS '
                  'SITTING for the entire rest of the video: butt firmly on the floor, hind legs '
                  'folded under the body, front legs straight down, tail curled around its paws, '
                  'chest up, body SHORT and COMPACT with a round chubby barrel-shaped chest and belly, a typical baby puppy build. '
                  'breathing gently with occasional ear twitches. It never lies down, '
                  'never stretches out on the ground, never stands up and never moves from the '
                  'sitting pose. '
                  'FULL BODY VISIBLE AT ALL TIMES: the entire dog from the tip of the ears to the '
                  'bottom of all four paws is completely visible inside the frame with generous empty '
                  'margin above the head and below the paws. The subject takes up less than 35 percent '
                  'of the frame height.',
                  ', lying down, lying, prone, lying flat, belly on floor, stretching out on '
                  'ground, sprawling, standing up, getting up, rising, walking, moving around, '
                  'feet cut off, paws out of frame, cropped feet, body cut by frame edge, '
                  'cropped body, half body out of frame, large subject, filling frame, '
                  'slim, lean, stretched tall, thin body, elongated body, long thin legs, '
                  'skinny dog, tall dog, narrow chest, narrow body'),
    'sleep':     (' Seen in an EXACT SIDE PROFILE VIEW the whole time, it sits down compactly '
                  'with the hind legs tucked under the body, yawns sleepily, then slowly curls '
                  'down into a compact relaxed ball on the ground: legs folded CLOSE under the '
                  'body, tail wrapped around, head resting low, the lying body small and '
                  'compact. Eyes closed, deep sleep with slow gentle breathing, chest rising '
                  'and falling. It remains curled and compact until the end.',
                  ', splayed legs, legs stretched out wide, legs apart, wide stance, body '
                  'stretched out long, sprawling flat, lying elongated, front view, facing '
                  'camera, both eyes visible, chest toward camera, standing up at the end, '
                  'getting back up, head up, mouth open, tongue out, panting'),
    'bark':      (' It stands UPRIGHT on all four straight legs in an EXACT SIDE PROFILE VIEW '
                  'facing right: muzzle points right, only ONE eye visible, tail on the left, '
                  'four legs straight down and clearly separated, the two hind legs close '
                  'together and parallel. It barks loudly several times while staying upright in '
                  'profile: mouth wide open and closing rhythmically with the muzzle still '
                  'pointing right, head lifting slightly with each bark, body energetic, chest '
                  'high, belly well above the floor. The head NEVER turns toward the camera.',
                  ', head turned to camera, looking at viewer, both eyes visible, facing camera, '
                  'front view, three quarter view, splayed legs, wide stance, five legs, six '
                  'legs, extra legs, lying down, lying, prone, crouching, belly on floor, chest '
                  'on floor, sitting down, sitting, closed mouth, mouth shut'),
    'lick':      (' It sits and grooms itself in a natural self-cleaning pose: it raises ONE '
                  'front paw close to its chest, bends its head DOWN so the open mouth is pressed '
                  'right against the raised paw, and the pink tongue VISIBLY TOUCHES and strokes '
                  'the paw fur, licking the paw repeatedly. Then it turns its head sideways and '
                  'buries the muzzle into the shoulder and side fur, tongue extended and clearly '
                  'in contact with the coat, licking the shoulder and flank fur with rhythmic '
                  'tongue movements. The mouth and tongue always stay in physical contact with '
                  'the body or paw while licking, no gap between tongue and fur, occasionally '
                  'pausing and resuming.',
                  ', licking the air, tongue not touching body, mouth away from body, gap '
                  'between mouth and fur, paw raised away from mouth, waving paw, panting with '
                  'head up, tongue hanging out'),
    'happy':     (' It hops up and down joyfully in place with a gentle SLOW bounce, seen in an '
                  'EXACT SIDE PROFILE VIEW facing right the whole time (muzzle right, one eye '
                  'visible, tail left), wagging its tail rapidly, all four legs clearly defined, '
                  'crisp sharp fur texture, slow smooth graceful motion, staying compact in one '
                  'spot. The body ALWAYS has EXACTLY FOUR LEGS, never five or six. '
                  'FULL BODY VISIBLE AT ALL TIMES: the entire dog from the tip of the ears to the '
                  'bottom of all four paws is completely visible inside the frame with generous '
                  'empty margin above the head and below the paws. CONSISTENT STABLE FRAMING '
                  'throughout, camera angle stays FIXED, never zooming in or out, never panning, '
                  'never changing perspective. The paws never touch or leave the bottom edge.',
                  ', motion blur, blurry, soft focus, out of focus, smeared fur, fast frantic '
                  'motion, head turned to camera, both eyes visible, facing camera, front view, '
                  'three quarter view, five legs, six legs, extra legs, more than four legs, '
                  'multiple front legs, multiple hind legs, extra paws, zooming, zoom in, zoom '
                  'out, camera pan, camera move, changing camera angle, feet cut off, paws out '
                  'of frame, cropped feet, body cut by frame edge, half body out of frame'),
    'roll':      (' Seen from the SIDE the whole time, it gently lies down on its side and '
                  'rolls slowly onto its back for a relaxed happy wiggle with legs loosely in '
                  'the air, then rolls back to its side and stands up again. The roll stays a '
                  'gentle partial roll in the side plane, the puppy never turns its back to the '
                  'camera and is never seen from behind. '
                  'The fur color and vest color remain perfectly consistent in every single frame '
                  'with zero flickering or color shift. Smooth steady motion with '
                  'no jerky or sudden changes between frames.',
                  ', back facing camera, seen from behind, butt facing camera, extreme twist, '
                  'contorted body, unnatural twisted pose, spine twisted, '
                  'two tails, extra tail, duplicate tail, forked tail, '
                  'five legs, six legs, extra legs, more than four legs'),
    'dance':     (' TINY PUPPY SEEN FROM VERY FAR AWAY, extreme wide shot. It dances playfully BALANCED UPRIGHT on its hind legs the whole time, body '
                  'vertical with chest high and both front paws raised waving in the air, '
                  'stepping and bouncing rhythmically in place. The body is SHORT and COMPACT '
                  'with a round chubby barrel-shaped chest and belly, a typical baby puppy build. '
                  'CRITICAL SIZE CONSTRAINT: the entire dog is VERY SMALL in the frame, taking up '
                  'less than 35 percent of the frame height, with LOTS of empty white space above '
                  'the head and below the paws. It never lies down, its belly '
                  'never touches the floor. '
                  'The body ALWAYS has EXACTLY FOUR LEGS: two hind legs on the ground, two front paws raised.',
                  ', lying down, lying, prone, belly on floor, chest on floor, crouching, '
                  'sitting down, sitting, '
                  'slim, lean, stretched tall, thin body, elongated body, long thin legs, '
                  'skinny dog, tall dog, narrow chest, narrow body'),
    'stretch':   (' Seen in an EXACT SIDE PROFILE VIEW the whole time, it performs a full body '
                  'stretch: lowering its front chest to the ground with front paws extended '
                  'forward, rear end raised high, holding the stretch briefly, then slowly '
                  'standing back up. It never turns toward the camera and stays in side '
                  'profile the entire video.',
                  ', front view, facing camera, facing viewer, looking at camera, turning '
                  'toward camera'),
    'beg':       (' TINY PUPPY SEEN FROM VERY FAR AWAY, extreme wide shot. It is ALREADY standing up on its hind legs holding a begging pose, '
                  'both front paws raised and staying STILL in that position, '
                  'looking up expectantly. It HOLDS this begging pose in place without moving forward or backward. '
                  'The body is SLENDER and ELONGATED with a LONG torso and relatively short legs, '
                  'a typical young Golden Retriever puppy build, NOT barrel-shaped, NOT chubby, NOT round. '
                  'CRITICAL SIZE CONSTRAINT: the entire dog is VERY SMALL in the frame, taking up '
                  'less than 35 percent of the frame height, with LOTS of empty white space above '
                  'the head and below the paws. The ENTIRE body stays inside '
                  'the frame at ALL times: the whole puppy from the top of the head to BOTH '
                  'hind paws is fully visible with clear margin around it; the hind paws stay '
                  'well above the bottom edge of the frame and never touch or leave it. '
                  'CONSISTENT STABLE FRAMING throughout, camera angle stays FIXED, never zooming '
                  'in or out, never panning, never changing perspective. The dog stays at the SAME distance from the camera for the entire video. '
                  'The dog NEVER walks toward the camera, NEVER approaches the camera, NEVER gets closer. '
                  'The body ALWAYS has EXACTLY FOUR LEGS: two hind legs on the ground, two front paws raised.',
                  ', feet cut off, paws out of frame, cropped feet, body cut by frame edge, '
                  'cropped body, half body out of frame, body outside frame, '
                  'slim, lean, stretched tall, thin body, elongated body, long thin legs, '
                  'skinny dog, tall dog, narrow chest, narrow body, '
                  'walking toward camera, approaching camera, getting closer, zooming in, growing bigger'),
    'bath':      (' It sits DEEP INSIDE a small white plastic baby bathtub placed on the white '
                  'floor, the tub resting firmly on the floor. The tub is filled to the rim with '
                  'thick soft white soap foam; the lower body and legs are fully submerged under '
                  'the foam so only the chest, front legs and head rise above the foam line, the '
                  'foam wrapping snugly around the chest like a soft white blanket. The fur is '
                  'VISIBLY WET everywhere: damp clumped strands sticking to the body, darker '
                  'soaked golden coat on the head, ears and back, clearly wet and sleek, never '
                  'dry or fluffy. The foam clings to the wet fur and melts softly into it: a '
                  'soft foam mound on top of the head blends into the damp hair with soft blurry '
                  'edges, and a few small foam patches on the back and chest fade gradually into '
                  'the wet coat, no hard outline anywhere. It wiggles gently in the foam, the '
                  'foam surface rippling softly, then shakes its head once sending tiny water '
                  'droplets flying, the white tub and the foam staying in the exact same spot the '
                  'whole time.',
                  ', dry fur, fluffy dry coat, standing dry fur, foam hat, white cap on '
                  'head, foam sticker, hard-edged foam patch, detached foam, floating foam '
                  'clumps, paws on tub rim, front paws over rim, leaning on rim, lying on rim, '
                  'empty tub, no foam, no bubbles, dry body, '
                  'blue foam, blue-gray foam, gray foam, colored foam, '
                  'foam same color as fur, '
                  'hand, hands, fingers, person, '
                  'human, floating tub, moving tub, multiple tubs, giant tub'),
    'pet':       (' TINY PUPPY SEEN FROM VERY FAR AWAY, extreme wide shot. It sits calmly in a gentle three-quarter view, eyes closed with a content '
                  'relaxed happy expression, tail wagging. The body is SHORT and COMPACT with a round chubby barrel-shaped chest and belly, a typical baby puppy build. A single human hand reaches in from '
                  'above and slowly strokes the top of its head and between its ears in repeated '
                  'gentle petting motions; the puppy leans its head into the palm, enjoying the '
                  'petting, ears relaxing back, tail wagging faster with joy, body staying compact '
                  'in the same spot the whole time. '
                  'The subject takes up less than 35 percent of the frame height.',
                  ', biting hand, licking hand, mouth open, teeth, fearful, scared, cowering, '
                  'aggressive, growling, two hands, multiple hands, hand under chin, '
                  'slim, lean, stretched tall, thin body, elongated body, long thin legs, '
                  'skinny dog, tall dog, narrow chest, narrow body'),
    'surprised': (' TINY PUPPY SEEN FROM VERY FAR AWAY, extreme wide shot. It sits calmly facing the camera, then suddenly gets startled and reacts '
                  'surprised: ears perk straight up, eyes go wide open, mouth opens, head jerks '
                  'back slightly, body recoils and does a small hop, then stays sitting with a '
                  'wide-eyed alert surprised expression. The body is SHORT and COMPACT with a round chubby barrel-shaped chest and belly, a typical baby puppy build. The subject takes up less than 35 percent of the frame height. '
                  'NO human, NO hands, the puppy is '
                  'completely alone.', ', hand, hands, fingers, arm, '
                  'slim, lean, stretched tall, thin body, elongated body, long thin legs, '
                  'skinny dog, tall dog, narrow chest, narrow body'),
    'play_dead': (' It flops down onto its side and lies completely still, pretending to be '
                  'dead with relaxed legs.', ''),
    'eat':       (' It stands in an EXACT SIDE PROFILE VIEW facing right: only ONE eye is '
                  'visible, the tail extends to the left, the whole body seen strictly from the '
                  'side at ALL times, the chest and face NEVER turn toward the camera, front '
                  'legs vertical and parallel, hind legs close together. A small red plastic '
                  'food bowl filled with brown kibble sits on the white floor right in front of its '
                  'chest, resting firmly on the floor at floor level. It lowers its head IN '
                  'PROFILE and eats FROM the bowl: the muzzle goes down INTO the red bowl, the '
                  'nose disappearing inside the bowl rim while chewing, head bobbing at bowl '
                  'level 80 percent of the time, lifting the head only briefly with a piece of '
                  'kibble in the mouth then returning into the bowl, tail wagging gently, the '
                  'body and the bowl staying in the exact same spot the whole time.',
                  ', food scattered on floor, kibble on ground, eating from floor, licking '
                  'floor, crumbs on floor, floating bowl, bowl in air, moving bowl, multiple '
                  'bowls, giant bowl, empty floor, front view, facing camera, both eyes '
                  'visible, three quarter view, chest toward camera, front legs spread, splayed '
                  'front legs, splayed legs, legs apart, wide stance, head up, looking around, '
                  'standing alert, sniffing air, head turned to camera, looking at viewer, '
                  'white food, milk, white liquid in bowl, shrinking bowl, changing bowl size, '
                  'bowl morphing'),
    'walk':      (' ALREADY in a full EXACT SIDE PROFILE VIEW from the VERY FIRST FRAME (no '
                  'front-facing approach, no turning toward the camera at any moment), the muzzle points to '
                  'the right, only ONE eye is visible, the tail extends to the left. The camera '
                  'sees the dog in a PERFECT 90-DEGREE SIDE PROFILE the ENTIRE video: the full length '
                  'of the body from chest to tail is visible, the body silhouette looks WIDE and '
                  'ELONGATED horizontally (clearly wider than tall), absolutely NO three-quarter '
                  'view, NO oblique angle, NO chest or face turning toward the viewer at any '
                  'moment. The dog '
                  'performs a FULL natural trot gait with large clear strides: '
                  'diagonal legs alternating — when the left front and right hind lift together, '
                  'the right front and left hind push off the ground, creating a clear rhythmic '
                  'trot pattern. Each paw lifts well off the ground with visible leg extension '
                  'and fold every step, hind legs pushing off firmly behind the hip with a wide '
                  'stride. Brisk energetic walk with natural leg swing. The camera pans at the '
                  'same speed as the dog, keeping it centered in the frame the entire time. '
                  'Tail gently swaying. The head and back stay level and horizontal the entire '
                  'time; the dog stays UPRIGHT on all four straight legs, chest high, belly well '
                  'above the floor. The dog keeps WALKING CONTINUOUSLY without stopping: no '
                  'pausing, no standing still, no sitting, no hopping, every single frame of the '
                  'video shows active stride motion with legs swinging, from the first frame to '
                  'the last frame, an unbroken rhythmic trot. '
                  'The fur color and vest color remain perfectly consistent in every single frame '
                  'with zero flickering or color shift. The coat is clean uniform golden cream on '
                  'every part of the body throughout the entire video. Smooth steady motion with '
                  'no jerky or sudden changes between frames. Exactly ONE tail, never two tails.',
                  ', front view, facing camera, standing still, static legs, stiff legs, locked '
                  'legs, tiny steps, shuffling, legs together, splayed hind legs, twisted legs, '
                  'unnatural legs, moving across the frame, drifting right, drifting left, '
                  'moving left, moving right, turning back, turning around, changing direction, '
                  'walking backward, horizontal drift, position shifting, traveling, '
                  'gray smudge, gray blob, gray halo, gray fringe, gray shadow, '
                  'gray edge on neck, gray edge on tail, flickering fur, shimmering coat, '
                  'inconsistent fur color, fur color changing between frames, '
                  'gray tinge on white fur, shadow on neck, shadow on tail, '
                  'two tails, extra tail, duplicate tail, forked tail, '
                  'jerky motion, sudden brightness change, frame flicker, color pop, '
                  'treadmill, belt, black strip, dark '
                  'strip, platform, machine, equipment, prop, object on floor, lying down, lying, '
                  'prone, crouching, belly on floor, chest on floor, sitting down, head down, '
                  'head lowered, butt up, rear raised, play bow, bowing, sniffing floor, nose to '
                  'floor, head turned to camera, looking at viewer, both eyes visible, stopping, '
                  'pause, paused, standing up, standing upright, standing, hop, hopping, jumping, '
                  'jump, bouncing, freeze, frozen, idle, resting, waiting'),
    'run':       (' It runs at FULL SPEED in an EXACT SIDE PROFILE VIEW facing right: the muzzle '
                  'points to the right, only ONE eye is visible, the tail extends to the left. On '
                  'the pure white studio floor it performs CONTINUOUS large-amplitude gallop '
                  'strides without pause: every single stride the legs stretch far forward and '
                  'far backward, a clear suspension moment with all four paws off the ground, '
                  'then legs tucking under the body, stride after stride at the same big '
                  'amplitude, powerful energetic sprint, ears and fur flowing, body holding the '
                  'same screen position the whole time. The head and back stay level and '
                  'horizontal the entire time. The floor stays pure white and completely '
                  'empty.' + COAT_CLAUSE,
                  ', front view, facing camera, standing still, standing, static legs, stiff '
                  'legs, locked legs, tiny steps, shuffling, legs together, hopping, hop, '
                  'bouncing in place, treadmill, belt, black strip, dark strip, platform, '
                  'machine, prop, object on floor, gray smudge, gray blob, gray stripe, head '
                  'down, head lowered to floor, butt up, rear raised, play bow, bowing, '
                  'stretching down, sniffing floor, sniffing ground, nose to floor, lying down, '
                  'lying, prone, sitting down, head turned to camera, looking at viewer, both '
                  'eyes visible'),
    # ── 交互三态（mochi v100/v102/v117验证，金毛移植版）──
    'kiss':      (' The video starts with the puppy FAR from the camera: a small full-body '
                  'golden puppy taking up about 25 percent of the frame height, standing in a '
                  'gentle three-quarter view on a pure white seamless studio backdrop. It then '
                  'WALKS DIRECTLY TOWARD THE CAMERA with a happy bouncy trot, growing MUCH BIGGER '
                  'frame after frame, until its muzzle and face become a LARGE CLOSE-UP taking '
                  'about 70 percent of the frame height. It looks directly at the camera with '
                  'bright warm brown eyes and gives several affectionate licks toward the camera lens: '
                  'the pink tongue VISIBLY EXTENDS from the mouth and touches toward the lens '
                  'several times. After licking, it steps back to medium distance and wags its '
                  'tail happily.' + COAT_CLAUSE,
                  ', sitting the whole time, never approaching, staying far away, same size '
                  'forever, turning away, back to camera, lying down, prone, closed mouth '
                  'forever, tongue hidden, head down, sniffing floor, side view, profile view'),
    'wave':      (' It sits calmly facing the camera the whole time: butt firmly on the floor, '
                  'hind legs tucked under, chest up, tail curled beside it. The body is SHORT and '
                  'COMPACT, a round chubby puppy build. It raises ONE front '
                  'paw beside its head and waves it side to side toward the viewer in a '
                  'friendly greeting: the paw goes left and right several times in a clear waving '
                  'motion, then lowers briefly and raises again to wave once more, head slightly '
                  'tilted with a happy expression. The other three legs stay firmly on the '
                  'floor. The raised paw moves in SLOW SMOOTH clean arcs with NO trailing ghost '
                  'or afterimage, the paw is always a single clean paw shape with crisp edges. '
                  'Only the wrist and paw move, the arm stays at the same height, the paw never '
                  'extends stiffly upward or points upward like a pointing gesture, the paw '
                  'always faces sideways toward the viewer with paw pad visible. '
                  'FULL BODY VISIBLE AT ALL TIMES: the entire dog from the tip of the ears to the '
                  'bottom of all paws is completely visible inside the frame with generous empty '
                  'margin above the head and below the paws. CONSISTENT STABLE FRAMING '
                  'throughout, camera angle stays FIXED, never zooming in or out, never panning, '
                  'never changing perspective. The paws never touch or leave the bottom edge.',
                  ', standing up, walking, moving around, turning away, back to camera, lying '
                  'down, prone, both paws raised, two paws in air, begging with both paws, head '
                  'down, sniffing floor, '
                  'splayed legs, wide stance, legs apart, five legs, six '
                  'legs, extra legs, zooming, zoom in, zoom out, camera pan, camera move, '
                  'changing camera angle, feet cut off, paws out of frame, cropped, body cut by '
                  'frame edge, half body out of frame, motion blur on paw, trailing paw, ghost '
                  'paw, afterimage, duplicate paw, blurred paw, finger pointing up, single '
                  'finger raised, middle finger gesture'),
    'type':      (' TINY PUPPY SEEN FROM VERY FAR AWAY, extreme wide shot. It sits behind a MINI RETRO TYPEWRITER-STYLE MECHANICAL KEYBOARD with ROUND PASTEL MACARON-COLORED KEYCAPS: each keycap is a small PERFECT CIRCLE like a candy, arranged in neat even rows on a cream white keyboard base. The keycaps are in soft pastel colors: pale pink, butter yellow, mint green, baby blue, and cream white, arranged randomly in a sweet candy-like pattern. The spacebar is a longer OBLONG PILL-SHAPE in pale pink. The keyboard is COMPACT and sits on the white floor in front of the puppy, SMALLER than the dog body. Both front paws rest on the nearest keycap rows and ALTERNATE PRESSING THE KEYS in a clear rhythmic left-right-left-right tapping motion: first the left paw presses down on a key, then the right paw presses, repeating continuously. The head is slightly lowered watching the keys with a focused expression. The FACE AND EYES stay PERFECTLY STABLE the whole time, no eye flicker or shifting catchlights. The keyboard and EVERY keycap stay PERFECTLY STATIC AND IDENTICAL in every single frame: same size, same position, same colors, same shape, never moving, never growing or shrinking, never morphing or changing. '
                  'The entire dog AND keyboard together are VERY SMALL in the frame with LOTS of '
                  'empty white space above the head and below the keyboard. The ears never touch '
                  'the top edge, the keyboard never touches the bottom edge.' + COAT_CLAUSE,
                  ', keyboard reversed, keyboard facing camera, keyboard moving, keyboard growing, keyboard shrinking, morphing keyboard, changing keyboard, floating keyboard, multiple keyboards, giant keyboard, paws off keyboard, transparent paws, ghost paws, frozen paws, paws not moving, flickering eyes, shifting catchlights, glowing eyes, bright eyes, standing up, walking, moving around, turning away, back to camera, lying down, prone, slim, lean, '
                  'square keycaps, rectangular keycaps, black keyboard, dark keyboard, realistic keyboard, standard keyboard, beads, beads toy, pearl beads, bead string'),
}
# 站姿腿约束统一追加到所有含站立段的状态
LEGS_POS = (' Whenever the puppy stands or rises on its legs, all four legs are straight down '
            'and clearly separated, the two hind legs close together and parallel, never '
            'splayed wide or twisted.')
LEGS_NEG = (', splayed legs, wide stance, legs apart, five legs, six legs, extra legs, '
            'splayed hind legs, twisted legs, unnatural legs')
for _k in ('sleep', 'roll', 'dance', 'stretch', 'happy', 'beg', 'play_dead', 'eat'):
    _d, _n = ACTIONS[_k]
    ACTIONS[_k] = (_d + LEGS_POS, _n + LEGS_NEG)

BASE = 'https://api.agnes-ai.cn/v1'
tok = bytes.fromhex(open(KEYHEX).read().strip()).decode()
HDR = {'Authorization': tok, 'Content-Type': 'application/json'}  # 裸key勿加Bearer

def submit(prompt, neg, ref_image=None):
    img_path = ref_image or REF_IMAGE
    img = base64.b64encode(open(img_path, 'rb').read()).decode()
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
        # kiss使用专用措辞（需要走近+特写，与通用COMMON/NEG_BASE冲突）
        if name == 'kiss':
            prompt = SUBJ + desc + COMMON_KISS
            neg = NEG_KISS + extra_neg
        elif name in ('sleep', 'stretch'):
            # sleep/stretch用灰色背景——白色背心/白毛在纯白背景上rembg无法区分
            prompt = SUBJ + desc + COMMON_ROLL
            neg = NEG_BASE + extra_neg
        elif name == 'walk':
            # walk用专用COMMON——允许真实步态位移，相机跟随居中
            prompt = SUBJ + desc + COMMON_WALK
            # 删掉NEG_BASE中禁止行走的词（walk需要真实步态）
            neg = (NEG_BASE + extra_neg).replace('moving forward, walking forward, changing position, ', '')
        else:
            prompt = SUBJ + desc + COMMON
            neg = NEG_BASE + extra_neg
        if name == 'pet':
            # 摸摸头互动必须有人手出现——豁免 NEG_BASE 的 human/person 排除词
            neg = neg.replace('human, person, ', '').replace(', human, person', '')
        # 参考图分发：t2i专用参考图（rembg提取+缩放~59%+纯白画布）优先于通用正面/侧面参考图
        # type/beg/dance/surprised/wave/pet/kiss用专用参考图
        SPECIAL_REFS = {
            'type': 'type_ref.png',
            'beg': 'beg_ref.png',
            'dance': 'dance_ref.png',
            'surprised': 'surprised_ref.png',
            'wave': 'wave_ref.png',
            'pet': 'pet_ref.png',
            # kiss不用t2i专用参考图——正面站立用identity_ref_front即可
            # t2i生成的正面站立图后腿分太开导致视觉6条腿
        }
        if name in SPECIAL_REFS:
            ref_image = os.path.join(ROOT, 'identity_candidates', SPECIAL_REFS[name])
        elif name in FRONT_VIEW_STATES:
            ref_image = REF_IMAGE_FRONT  # cand_0 正面朝向
        else:
            ref_image = REF_IMAGE_SIDE   # cand_2 侧面朝向
        vid, err = submit(prompt, neg, ref_image=ref_image)

        # 提交重试(金毛+背心实测): 429/限流/503 单次失败即 continue = 该状态永久跳过且不补跑。
        # 6次指数退避重试(75s起)覆盖推理槽位占用期; 全部失败才跳过并显著报错。
        # ⚠️ 修复: kiss 重试必须用 COMMON_KISS（v130d教训: 用通用COMMON导致kiss重试
        #    提交了错误措辞，生成出非走近而是原地不动的视频）
        for _attempt in range(6):
            if vid:
                break
            wait = 75 * (2 ** _attempt)
            print(f'  [retry {_attempt + 1}/6] submit failed: {err} — waiting {wait}s', flush=True)
            time.sleep(wait)
            # kiss 用专用措辞重试，其余用通用 COMMON
            if name == 'kiss':
                _retry_prompt = SUBJ + desc + COMMON_KISS
            else:
                _retry_prompt = SUBJ + desc + COMMON
            vid, err = submit(_retry_prompt, neg, ref_image=ref_image)
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
