# GoldenVestPet Bug Tracker

## 待解决

### BUG-1: 动作幅度大时帧出现运动模糊（happy/dance/stretch头部最严重）
- **状态**: 搁置
- **根因**: AI视频生成(agnes-video-v2.0)在动作幅度大时产生运动模糊，直接体现在frames_raw原始帧。happy头部sharpness最差37 vs 最佳230（6.2x差距），dance/stretch同样严重。
- **验证**: frames_raw与mp4直接提取帧sharpness完全一致(diff=0)，确认是源视频问题，非抽帧/处理导致。
- **候选方案**: 
  1. AI去模糊模型(Real-ESRGAN/NAFNet)对模糊帧修复（未安装，需pip install realesrgan）
  2. 重新生成视频时prompt加"slow motion"降低运动速度
  3. 帧插值替换模糊帧（不适用于大幅动作）
- **影响状态**: happy, dance, stretch, run（头部运动大的帧）

### BUG-2: walk循环感/跳变 (v112部分改善)
- **状态**: 用户验收"还可以"，接受当前版本
- **已做**: 
  1. v3: 强化prompt"ALREADY WALKING from VERY FIRST FRAME"+用侧面行走帧作参考图替代原ref_walk.png
  2. AI视频仍有前~20帧轻微过渡（头未完全侧面），但整体可接受
  3. 尝试了dissolve crossfade消除循环接缝→产生重影，用户拒绝
  4. 最终采用原始121帧直接播放，用户验收通过
- **残留**: 循环播放时首尾不衔接会有轻微跳感（AI视频固有局限），运动模糊见BUG-1
- **备注**: 循环感根治需AI模型能生成首尾完美衔接的循环视频，当前模型不支持

## 已解决

### FIX-0: 内存占用5GB+ (v112)
- **根因**: 
  1. 启动时preload全部20个状态(2420帧)到内存
  2. 镜像帧(frames_m)缓存导致内存翻倍
  3. 无sprite_meta.json，legacy加载路径峰值极高
  4. LRU keep=2实际未生效(全部预加载后都在_loaded_order里)
- **修复**:
  1. 生成sprite_meta.json，streaming路径逐帧加载(峰值<10MB/状态)
  2. 删除启动preload，严格按需加载(ensure_state: 5帧同步+后台全帧)
  3. 镜像帧不缓存，paint时img.mirrored()实时生成(0.04ms/帧)
  4. 严格LRU keep=2，仅保留当前+最近1个状态
- **效果**: 内存从5GB降至<300MB(DPR1.5), <200MB(DPR1.0)

### FIX-1: walk/run模糊+抖动 (v110)
- **根因**: process_darkblue.py逐帧scale=√(target_fg/fg)，walk/run腿展开时fg大→缩小多→帧间尺寸抖动
- **修复**: 所有状态统一使用fixed_scale（v111改为UNIFIED_FG）

### FIX-2: idle画布平移 (v110)
- **根因**: bbox居中(w-new_w)//2，呼吸动画帧宽微变→水平位置微变→画布平移
- **修复**: COM质心水平居中替代bbox居中

### FIX-3: eat食盆被抠掉 (v110)
- **根因**: BiRefNet把红色食盆当背景抠掉
- **修复**: eat加入色差法补充(color_dist>20)

### FIX-4: 动作时长不足 (v110)
- **根因**: oneshot状态duration=5.08秒=1轮
- **修复**: 所有菜单动作至少2轮(10.16秒)，roll/dance/bath 3轮(15.24秒)

### FIX-5: 各动作狗大小不一致 (v111)
- **根因**: v110使用target_fg=median_fg→fixed_scale=1.0，不同状态median_fg差异大（idle 220K vs sleep 625K vs run 340K）
- **修复**: 统一UNIFIED_FG=220000作为所有状态的target，fixed_scale=√(UNIFIED_FG/median_fg)

### FIX-6: sleep边缘闪烁 (v111)
- **根因**: BiRefNet对sleep帧的边缘判定不稳定，帧间soft/hard alpha切换导致轮廓闪烁（alpha diff sum最高4.3M）
- **修复**: sleep使用更高的SIGMOID_CORE阈值(0.85)，让更多边缘像素变硬，减少soft区域帧间抖动
