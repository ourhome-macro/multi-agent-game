# NPC 位置与移动 V1 设计

生成时间：2026-06-27

## 结论

多 Agent 必须加位置，而且位置不能只是前端动画状态。NPC 位置是感知、私聊、公共展示、NPC-NPC 遭遇、传闻传播和移动叙事的基础权威状态。

但 V1 不能做“随机游荡”。随机移动会让悬疑案件失控：NPC 为什么知道某事、为什么错过某事、为什么正好撞见某事，都无法解释。正确路线是确定性、可回放、规则约束的适度移动。

```text
town.tick
  -> movement candidate
  -> Director precheck
  -> RuleEngine validate
  -> npc.location.changed
  -> PerceptionSystem
  -> npc.observed
  -> memory_candidate.created
```

## 位置分层

V1 只做两层位置，不急着做连续寻路。

### 1. 场景级位置

权威状态：

```text
NpcLocationState
  character_id
  scene_id
  updated_at_tick
  source_event_id
```

这是后端规则和 replay 的主状态。所有可见性判断都先看 `scene_id`。

### 2. 前端展示坐标

展示坐标不作为权威状态：

```text
scene_id
display_x
display_y
facing
animation_state
```

前端可以根据 `scene_id`、角色默认站位、最近移动事件和插值动画生成展示效果。除非后续要做格子寻路、追逐、遮挡视线，否则 V1 不把 `x/y` 写入权威事件。

## 移动事件

新增事件：

```text
npc.location.changed
```

payload：

```text
character_id
from_scene_id
to_scene_id
movement_reason
tick_id
route_ref
```

`movement_reason` 使用稳定枚举，不写自然语言：

```text
schedule
investigate_noise
avoid_player
join_scene
return_to_anchor
director_forced
```

V1 推荐只启用：

```text
schedule
return_to_anchor
join_scene
```

`investigate_noise`、`avoid_player` 容易制造过强叙事效果，等感知和意图拒绝链稳定后再开。

## 移动规则

移动必须由 RuleEngine 执行。

规则：

- NPC 必须存在。
- `to_scene_id` 必须存在。
- `from_scene_id` 必须匹配当前 `SessionState.npc_locations`，初始化除外。
- 目标场景必须在允许路线内。
- 当前剧情阶段必须允许该 NPC 进入目标场景。
- 正在进行关键对话、审讯、公开展示时，不允许无故离场。
- 移动不能直接解锁线索、推进 phase 或改 memory。

拒绝必须落事件：

```text
rule.rejected
```

或：

```text
npc.autonomy_intent.rejected
```

## 场景连接

V1 需要在案件包里补一个轻量 scene graph。

推荐配置：

```yaml
scene_connections:
  - from_scene_id: hall
    to_scene_id: study
    bidirectional: true
  - from_scene_id: hall
    to_scene_id: gallery
    bidirectional: true
```

如果暂时不想改 schema，可以先在运行时代码中从 `SceneConfig` 的已知场景生成保守连接，但这只能用于 demo，不该长期作为生产规则。

## 移动调度策略

V1 用 deterministic scheduler，不调 LLM。

输入：

```text
session.town_clock.tick_id
session.npc_locations
case.characters
case.scenes
recent_world_events
```

输出：

```text
list[NpcAutonomyIntent(move|wait|observe)]
```

策略：

- 每 tick 最多移动少量 NPC，例如 1 到 2 个。
- NPC 有 anchor scene，空闲时会回到自己的常驻场景。
- 关键阶段 NPC 固定在叙事需要的位置。
- 最近参与玩家交互的 NPC 短时间内不自动离场。
- 同一 NPC 有移动 cooldown，避免来回抽搐。
- 移动原因必须可解释，写入 trace reason code。

示例：

```text
tick 1: jiang_yanhui hall -> study, reason=schedule
tick 2: no movement
tick 3: qi_yan gallery -> hall, reason=join_scene
tick 4: lin_qichi hall -> gallery, reason=return_to_anchor
```

## 感知联动

NPC 移动后，PerceptionSystem 才判断同场景事件可见性。

关键边界：

- NPC 不在场，就不能观察 `scene_shared` 事件。
- NPC 刚移动进场，只能观察移动后发生的事件，不能倒看之前的私聊。
- `npc.location.changed` 本身可以被同场景角色观察，但 payload 只说明“某角色进入/离开”，不带私有动机。
- Director 审计事件、规则拒绝事件、private memory 永远不可因移动被普通 NPC 看见。

## 前端表现

前端需要展示“活着的小镇”，但不应伪造权威。

V1 表现策略：

- 后端返回每个 NPC 当前 `scene_id`。
- 前端根据 scene layout 给 NPC 分配站位。
- 收到 `npc.location.changed` 后做过场动画：离开旧场景、进入新场景。
- 如果玩家切到某场景，只显示当前 `npc_locations` 中在该场景的 NPC。
- NPC 的具体坐标、朝向、走路动画可以是前端派生，不写回后端。

## 验收标准

- replay 固定事件序列后，NPC 所在场景完全一致。
- 同一 tick 运行结果确定，不依赖随机数或 LLM。
- 缺席 NPC 不会观察私聊或公共展示。
- NPC 移动不会直接产生 clue unlock、phase change 或 memory 写入。
- 所有移动都有 `npc.location.changed` 或拒绝事件可追溯。
- 前端看起来有移动，但后端仍以 scene-level location 作为权威。

## 不做事项

V1 不做：

- 逐像素寻路。
- 碰撞体和视锥遮挡。
- 随机漫游。
- NPC 自主搜证解锁关键线索。
- 全员每 tick 调 LLM 决定去哪。
- NPC 因移动直接共享 private memory。

这些能力必须等 scene-level replay、可见性、传闻权威和 NPC 自主意图拒绝链稳定后再加。

