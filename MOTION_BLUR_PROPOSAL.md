# 运动模糊引擎方案文档

## 一、现状分析

### 渲染管线现状
| 属性 | 值 |
|------|-----|
| 帧分辨率 | 1664×1216 RGBA (Premultiplied ARGB32) |
| 帧率 | 24fps (42ms/帧) |
| 渲染频率 | 60fps (16ms timer)，sprite每2.6个tick换一次帧 |
| 每状态帧数 | 121帧，20个状态 |
| 渲染方式 | 单帧 `drawPixmap` (zero-copy GPU blit) |
| 帧缓存 | QPixmap滑动窗口缓存，QImage常驻 |

### 运动幅度实测
| 状态 | 帧间像素差 | 像素位移率 | 运动强度 |
|------|-----------|-----------|---------|
| run | 35.8 | 56% (max 82%) | ⚡极强 |
| dance | 34.6 | 55% (max 84%) | ⚡极强 |
| happy | 34.6 | 55% (max 78%) | 🔴强 |
| walk | 28.4 | 56% (max 61%) | 🔴强 |
| roll | 23.2 | 38% (max 84%) | 🟡中 |
| bark | 19.4 | 35% (max 58%) | 🟡中 |
| idle | 18.2 | 33% (max 51%) | 🟢低 |

### 核心问题
当前每帧是一个**瞬时快照**（instant snapshot），而非**曝光积累**（shutter exposure）。真实摄像机在1/24s快门时间内积累光量，产生自然运动模糊；而我们的帧是0时刻的切片，24fps下高速运动的肢体（run/dance的腿部）出现**频闪感**（temporal aliasing），与24fps电影的流畅感有本质差距。

---

## 二、方案穷举与排除

### ❌ 方案A：全帧高斯模糊 (QGraphicsBlurEffect)
- 均匀模糊，无法做到**方向性**（运动方向）
- 1664×1216 CPU卷积 → 8MB/帧 → 严重卡顿
- 对透明背景区域产生光晕溢色
- **排除原因：性能不可行 + 效果错误**

### ❌ 方案B：多帧残影叠加 (Classic Ghosting)
- 保留前N帧以递减alpha叠加
- 24fps下残影间距42ms → **明显分阶/多腿幻觉**
- Shawn Hargreaves明确指出此技术需60fps才有效
- **排除原因：24fps下效果差**

### ❌ 方案C：离线预生成混合帧
- 预计算相邻帧混合图，存为新资产
- 磁盘翻倍(123→246MB)、内存翻倍(帧数121→241)
- 混合比例固定，无法自适应运动幅度
- 需重跑管线，违背"不重新生成视频"原则
- **排除原因：资源翻倍 + 不灵活 + 违背约束**

### ❌ 方案D：方向性卷积模糊 (自定义shader/CPU)
- 需要逐像素运动向量 → 无法从2D sprite获取深度/运动信息
- 实现复杂度极高，与PyQt5 QPainter管线不兼容
- **排除原因：架构不兼容 + 无法获取运动向量**

---

## 三、最优方案：运动自适应双帧Alpha混合

### 核心原理
模拟摄像机**快门曝光**：在相邻两个ANIMATION帧之间，按sub-frame时间比例做Alpha加权混合，使运动区域在帧内产生自然模糊。

### 为什么这是最优
1. **零资产改动**：不重新生成视频，不增加磁盘/内存
2. **零架构颠覆**：在现有`paintEvent`中加入~20行渲染代码
3. **零性能代价**：额外1次`drawPixmap`（GPU blit ~0.1ms）+ 1次`bank.get()`（O(1)缓存命中）
4. **物理正确**：静止区域帧间无差异→混合=原图(无损)；运动区域→自然曝光模糊
5. **自适应**：idle/sleep等低运动状态自动关闭；run/dance等高强度状态全量启用

### 具体实现设计

#### 1. Sub-frame ratio计算（game_loop中，~5行）
```python
# 在 frame_idx 计算之后
frame_ms = ANIMS[self.state][2]
sub_t = self.anim_elapsed % frame_ms  # 当前帧内已过时间
self._blur_ratio = sub_t / frame_ms   # 下一帧权重 0→1

# 运动自适应：低运动状态禁用混合
if self.state in ('idle', 'sleep', 'sit'):
    self._blur_ratio = 1.0  # 不混合
```

#### 2. 可选：快门角度参数
```python
SHUTTER_ANGLE = 180  # 默认180°（电影标准），360=全曝光，90=更锐利
# 实际使用的ratio衰减：
effective_ratio = self._blur_ratio * (SHUTTER_ANGLE / 360.0)
```
180°快门 = ratio×0.5，更锐利自然；360°= ratio×1.0，更模糊流畅

#### 3. paintEvent渲染逻辑（~15行）
```python
# 在 drawPixmap(draw_rect, pm, src_rect) 之前插入：
blur_r = getattr(self, '_blur_ratio', 1.0)
if blur_r < 0.99:  # 需要混合
    _owner = self.bank.alias.get(self.state, self.state)
    _loaded = len(self.bank.frames.get(_owner, []))
    next_idx = (self.frame_idx + 1) % _loaded
    # 增量加载中next_idx可能未就绪 → 降级单帧
    pm_next = self.bank.get(self.state, next_idx, self.flipped)
    if not pm_next.isNull():
        painter.save()
        painter.setOpacity(blur_r * (SHUTTER_ANGLE / 360.0))
        painter.drawPixmap(draw_rect, pm_next, QRectF(0, 0, _iw, _ih))
        painter.restore()

# 然后正常画当前帧（opacity=1.0）
painter.drawPixmap(draw_rect, pm, QRectF(0, 0, _iw, _ih))
```

#### 4. 边界安全
| 场景 | 处理 |
|------|------|
| loop=True（walk/run/idle等）| frame_idx+1回绕到0 |
| loop=False（happy/stretch等）| 到末帧时ratio→1.0，不混合 |
| 增量加载中frame_idx+1未加载 | `pm_next.isNull()`降级单帧 |
| 状态切换瞬间 | ratio重置为0，纯新帧 |

### 性能量化

| 指标 | 当前 | 加入混合后 | 变化 |
|------|------|-----------|------|
| drawPixmap调用 | 1次/帧 | 2次/帧 | +0.1ms |
| bank.get()调用 | 1次/帧 | 2次/帧 | +0.01ms |
| 内存增量 | — | 0 | 无（用已有缓存） |
| 磁盘增量 | — | 0 | 无 |
| 帧时间预算 | 16ms | 16ms | 仍在预算内 |

### 可选增强：三帧混合
对run/dance等高速运动，同时混合frame[i-1]和frame[i+1]：
```
painter.setOpacity(0.15) → drawPixmap(frame[i-1])
painter.setOpacity(0.25) → drawPixmap(frame[i+1])
painter.setOpacity(1.0)  → drawPixmap(frame[i])
```
模拟180°快门：50%当前帧 + 25%前尾 + 25%后尾
开销：3次drawPixmap → 仍<0.5ms/帧

---

## 四、方案对比总结

| | 方案1:双帧混合(推荐) | 方案2:离线预生成 | 方案3:全帧模糊 | 方案4:残影叠加 |
|---|---|---|---|---|
| 需重新生成视频 | ❌不需要 | ✅需要 | ❌不需要 | ❌不需要 |
| 代码改动量 | ~30行 | ~100行+脚本 | ~50行 | ~40行 |
| 磁盘增量 | 0 | +123MB | 0 | 0 |
| 内存增量 | 0 | +60MB | 0 | +3帧缓存 |
| 渲染性能 | +0.1ms | 0 | +10ms+ | +0.3ms |
| 画质提升 | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐ |
| 自适应运动幅度 | ✅ | ❌ | ❌ | ❌ |
| 24fps下效果 | ✅正确 | ✅正确 | ❌错误 | ❌差 |

**唯一最优解：方案1 — 运动自适应双帧Alpha混合**

---

## 五、待决策选项

1. **快门角度**：180°（电影标准，自然锐利）vs 270°（更模糊流畅）vs 360°（最模糊）
2. **混合模式**：仅双帧（简单高效）vs 可选三帧（run/dance时更高质量）
3. **运动阈值**：哪些状态启用混合？建议idle/sleep/sit禁用，其余全部启用
4. **是否加菜单开关**：右键菜单加"运动模糊 开/关"选项，让用户自选
