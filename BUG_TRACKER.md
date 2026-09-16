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

### FIX-7: Desktop Fixed模式下walk动作失效 (v113)
- **根因**: 菜单手动选walk时没有设置`roam_target`，而`_do_walk`在desktop模式+`roam_target is None`时立即减速切idle。同时AI决策（`_do_ai`）在desktop模式下完全排除walk，只做原地动作。
- **修复**: 
  1. 菜单选walk时，desktop模式下生成`roam_target`（向walk_dir方向走300-600像素距离）
  2. AI决策中desktop模式也有12%概率触发walk（不再完全排除）
- **预防铁律**: 任何模式切换需验证walk/run等移动状态是否受`roam_target`/目标位置逻辑影响，不能假设"有状态就能动"

### FIX-8: 右键菜单外左键点击无法关闭 (v113)
- **根因**: 点击空白桌面时，Windows不会把事件发给任何Qt窗口（没有widget在该坐标），所以QApplication级别的eventFilter根本收不到该点击事件。`QApplication.mouseButtons()`在模态QEventLoop中也不会更新（因为没有Qt鼠标事件被处理）。
- **修复**: 在`exec_menu`的QEventLoop中加100ms QTimer轮询，使用Win32 API `GetAsyncKeyState(1)`直接读取鼠标物理按键状态（绕过Qt事件系统），左键按下+光标在所有菜单rect外→`close_all()`
- **预防铁律**: Qt模态循环中检测外部输入不能依赖Qt事件系统，必须用平台原生API（Windows=GetAsyncKeyState）做兜底

### FIX-9: macOS置顶窗口抢焦点 (v113)
- **根因**: `_ensure_visible`中使用`NSStatusWindowLevel`（状态栏级别太高），且未禁止窗口接受焦点。macOS会把焦点给高level窗口，点击其他应用时焦点被抢回。同时spec未打包pyobjc，运行时`import objc`失败→fallback `raise_()`更严重地抢焦点
- **修复**: 
  1. 改用`NSFloatingWindowLevel`（浮动层，不抢焦点但保持置顶）
  2. `ns_win.setCanBecomeKey_(False)` + `setCanBecomeMainWindow_(False)` 禁止窗口成为key
  3. spec加`objc, AppKit, Foundation`到hiddenimports + CI装`pyobjc-core pyobjc-framework-Cocoa`
- **预防铁律**: macOS窗口level选择：NSFloatingWindowLevel（置顶不抢焦点）优于NSStatusWindowLevel（置顶抢焦点）。pyobjc必须打包否则原生API不可用

### FIX-10: macOS DMG无经典双栏拖拽布局 (v113)
- **根因**: 纯`hdiutil create -srcfolder`只生成文件夹视图，不设置`.DS_Store`元数据（图标位置、窗口大小、背景图等）。AppleScript操作Finder在CI headless环境必失败
- **修复**: 使用`dmgbuild`（纯Python库，无需Finder/AppleScript）生成含`.DS_Store`元数据的美化DMG：背景图(Pillow内联生成1200×800 @2x深色+箭头)、图标位置(app左+Applications右)、窗口600×400点、128pt图标
- **预防铁律**: CI中DMG美化只能用dmgbuild，禁AppleScript（无Finder）

### FIX-11: macOS内存3GB+ (v113，根治方案已实施)
- **根因(深入静态分析确认)**：引擎代码内存模型无问题（理论峰值RSS ~550MB: 帧数据~452MB + 框架~100MB）。3GB+来自PyInstaller打包膨胀：
  1. **QtWebEngine泄漏(最致命)**：PyInstaller的hook-PyQt5.py通过QtWebChannel间接拉入QtWebEngine(Chromium ~300-500MB)，spec的excludes对hook不总生效
  2. **CI全局site-packages**：pip装到全局，PyInstaller发现numpy/PIL等并自动包含
  3. **excludes不够彻底**：缺少QtWebEngineCore/Widgets + Qt3D等
- **修复**：
  1. 自定义空hook覆盖PyInstaller默认hook（`hooks/hook-PyQt5.QtWebEngine*.py`），spec设`hookspath=['hooks']`
  2. CI改用虚拟环境（`python -m venv build_env`），只装实际依赖
  3. spec大幅扩充excludes（+QtWebEngine系列 +Qt3D +cmake/ninja等CI环境库）
  4. CI构建后打印Top-20最大文件 + .app大小检查
- **预防铁律**：macOS打包必须①用venv隔离 ②自定义hook阻止QtWebEngine ③验证.app<80MB

### FIX-12: macOS窗口侵占其他应用 (v113)
- **根因**: `_ensure_visible`每1秒调用`orderFrontRegardless()`+`setLevel_(NSFloatingWindowLevel)`，持续把宠物窗口推到所有应用前面，导致Chrome/其他窗口无法点击
- **修复**: `orderFrontRegardless`和`setLevel_`只在窗口从隐藏/最小化恢复时调用，窗口已可见时不做任何macOS原生API调用
- **预防铁律**: macOS浮动窗口不要在定时器中反复调用orderFrontRegardless，只在恢复时用

### FIX-13: 集成显卡卡顿 (v113)
- **根因**: 三层叠加瓶颈——①帧存QImage(CPU),drawImage每帧CPU→GPU传输30MB/s ②macOS透明窗口backing store每帧全窗口上传1.6MB@Retina ③粒子变化触发全窗口重绘(而非仅粒子区域)
- **修复**: 三层优化——①QPixmap懒缓存:首次draw时fromImage转GPU,后续drawPixmap零拷贝blit ②脏矩形update(QRect):帧不变+仅粒子活跃时只标记粒子区域,backing store上传从1.6MB→~50KB ③paintEvent裁剪event.rect()跳过非脏区域绘制
- **预防铁律**: 高频动画帧必须用QPixmap缓存+drawPixmap;透明窗口必须用脏矩形update而非全窗口;paintEvent必须clip event.rect()

### FIX-14: macOS启动加载验证慢 (v113)
- **根因**: ad-hoc签名(`codesign --sign -`)没有Hardened Runtime(`--options runtime`)，macOS把.app视为完全未签名，每次启动都执行Gatekeeper全文件quarantine扫描
- **修复**: ①codesign加`--options runtime`启用Hardened Runtime + entitlements.plist，macOS缓存签名检查结果 ②Release说明明确xattr -cr一次性解除quarantine ③用户拖到/Applications而非从DMG直接运行
- **预防铁律**: macOS分发必须①codesign带--options runtime ②提供entitlements ③告知用户xattr -cr

### FIX-15: 动作头几帧循环卡顿 (v113)
- **根因**: 增量加载首屏仅5帧(0.2s循环)，chunk追加帧时raw_idx % new_count跳帧（如5→25帧时从第4帧跳到第20帧）
- **修复**: ①同步首屏从5帧增至25帧(~1s@24fps) ②frame_idx限制在已加载帧数内循环 ③chunk追加时重置anim_elapsed=frame_idx*frame_ms平滑过渡
- **预防铁律**: 增量加载首屏至少1秒帧数；chunk追加必须同步重置anim_elapsed

### FIX-16: loop=False动作播完不回idle (v113)
- **根因**: happy/roll/stretch等loop=False状态播完121帧后frame_idx停在最后一帧，但state_duration(如roll=10.16秒)未到期，视觉卡死5秒
- **修复**: loop=False状态播到最后一帧时立即回idle，不等duration到期
- **预防铁律**: loop=False状态的duration只用于防止AI打断，播完帧应立即回idle

### FIX-17: macOS切应用后宠物消失 (v113)
- **根因**: Qt.Tool窗口在macOS上自动跟随应用前台状态——切到其他应用时Tool窗口隐藏
- **修复**: 改用Qt.Window + Qt.WindowDoesNotAcceptFocus + LSUIElement=True(Info.plist)，宠物始终可见不出现在Dock/Cmd+Tab
- **预防铁律**: macOS桌面宠物禁用Qt.Tool(会跟随应用隐藏)，用Qt.Window+LSUIElement替代
