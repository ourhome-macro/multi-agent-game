# 多 Agent 小镇式编排方案

生成时间：2026-06-17

## 结论

项目可以吸收 Stanford Generative Agents / Smallville 的多 Agent 小镇机制，但不能照搬。原论文的核心是每个 agent 通过 memory stream、reflection、planning 形成可信日常行为，并在环境中观察、交谈、传播信息、协调活动。这个方向适合本项目的 2D 悬疑世界，但必须改造成“事件溯源 + 规则裁决 + Director 审计”的版本。

正确方向不是：

```text
NPC A LLM -> NPC B LLM -> NPC C LLM
```

而是：

```text
WorldEvent
  -> NPC perception inbox
  -> private / shared memory derivation
  -> schedule / intention proposal
  -> Director + Rule Engine
  -> new WorldEvent
```

也就是说，小镇是 world simulation，不是群聊。

## Stanford 小镇可借鉴的组件

Stanford Generative Agents 论文中的关键组件：

- Memory stream：记录 agent 经历。
- Retrieval：按相关性、近因和重要性召回。
- Reflection：把低层经历总结成高层认知。
- Planning：生成日计划，并拆成短期行为。
- Observation：agent 感知环境和其他 agent 行为。
- Conversation：agent 间对话形成社会传播。
- Emergence：一个初始种子可以通过社交网络传播成群体活动。

这些组件对本项目有价值，但要改写权威边界：

- memory stream 不能由 LLM 直接写，必须由事件派生。
- reflection 不能生成世界真相，只能生成角色主观 belief / strategy / impression。
- planning 不能直接行动，只能提出 `NpcAutonomyIntent`。
- conversation 不能直接污染其他 NPC 记忆，必须通过 `WorldEvent` 和可见性规则传播。
- emergent behavior 必须被 Narrative Director 节奏约束，不能提前合成真相。

## 建议目标形态

增加一个 `Town Orchestrator`，作为运行时的 NPC 自主调度层。

```text
TownClock.tick
  -> PerceptionSystem.collect_visible_events(npc)
  -> MemoryDerivationSystem.update_npc_memory
  -> ReflectionSystem.maybe_reflect(npc)
  -> SchedulePlanner.propose_next_activity(npc)
  -> SocialOrchestrator.match_interactions
  -> NarrativeDirector.precheck_autonomy
  -> RuleEngine.apply_npc_action
  -> EventRecorder.append
```

它和玩家行动链路并列，但共享同一套状态权威：

```text
PlayerAction path:
  player input -> ActionService -> AgentLoop -> Director -> RuleEngine -> WorldEvent

Autonomous NPC path:
  clock tick -> TownOrchestrator -> NPC intent -> Director -> RuleEngine -> WorldEvent
```

任何 NPC 自主行为都不得绕过 Rule Engine。

## 新领域模型建议

### TownClock

表示游戏内时间，不等于真实系统时间。

字段建议：

- `session_id`
- `tick_id`
- `game_time`
- `phase_id`
- `active_scene_ids`
- `caused_by_event_id`

时间推进也应事件化：

```text
town.tick.advanced
```

### NpcScheduleState

NPC 当前计划，不是硬状态真相，只是可解释行为依据。

字段建议：

- `character_id`
- `current_goal_id`
- `current_activity_id`
- `scene_id`
- `planned_until`
- `priority`
- `source_event_ids`

变更事件：

```text
npc.schedule.updated
```

### NpcPerceptionEvent

NPC 观察到什么。观察不是全知，必须按场景、距离、可见性和剧情权限过滤。

事件：

```text
npc.observed
```

payload：

- `observer_id`
- `observed_event_id`
- `scene_id`
- `visibility`
- `perception_quality`
- `redacted_payload_ref`

注意：不要把被观察事件的完整敏感正文复制进 payload。记录引用和安全摘要即可。

### NpcAutonomyIntent

自主 NPC 的结构化意图，类似 `AgentIntent`，但更偏行动。

字段建议：

- `actor_id`
- `intent_type`: `move | talk | observe | ask | share | avoid | investigate | wait`
- `target_character_id`
- `target_scene_id`
- `topic_refs`
- `memory_refs`
- `proposed_actions`
- `speech`
- `risk_flags`

LLM 可以生成这个意图，但不能执行。

### SocialTransmission

NPC 间信息传播必须显式事件化。

事件：

```text
npc.social_interaction.started
npc.social_interaction.uttered
npc.social_interaction.ended
npc.hearsay.received
```

`hearsay` 必须低权威：

```text
metadata.authority_source = npc_hearsay
memory_type = belief
confidence <= 0.5 by default
```

这样 hearsay 不能压过玩家证据、系统规则或直接观察。

## Memory 改造方式

当前 memory 已有：

- `episodic`
- `belief`
- `relationship`
- `strategy`
- `case/session/npc_private/scene_shared/director_audit`
- `core/working/archival`
- `authority_source`

这些足够承接小镇机制。需要新增的不是向量库，而是 NPC 自主观察和反思的事件来源。

建议新增 memory 来源：

- `npc_observation`
- `npc_direct_dialogue`
- `npc_hearsay`
- `npc_reflection`
- `schedule_commitment`

反思规则必须受限：

```text
low-level events -> subjective belief / strategy
```

禁止：

```text
low-level events -> world truth
low-level events -> solution claim
hearsay -> authoritative fact
```

## Reflection 设计

Smallville 的 reflection 会把记忆总结成高层结论。本项目可以做，但必须区分三层：

### 安全反思

允许生成：

- “我觉得玩家在试探药物话题”
- “我应该避开锁的时间差”
- “沈照夜可能知道旧案，但这只是传闻”

落地为：

```text
agent_memory_snapshot.updated(memory_type=belief|strategy)
character_impression.updated
```

### 风险反思

需要 Director 审计：

- 涉及 locked world_info
- 涉及多个 safe fragment 合成
- 涉及嫌疑人身份
- 涉及旧案因果链

落地前应进入：

```text
director.reflection_reviewed
```

### 禁止反思

不能让 LLM 从碎片自行推出案件真相，并写入 NPC 认知：

- 凶手是谁
- 完整死亡链
- 未解锁 motive
- solution_claim 是否成立

这些只能由案件 truth anchor、RuleEngine 或正式 accusation 规则处理。

## Planning 设计

小镇日程系统可以增强“活着的 NPC”，但悬疑项目里计划必须服务剧情节奏。

建议分两层：

### Routine Plan

低风险日程：

- 移动到场景
- 等待
- 与某人寒暄
- 检查公共物品
- 回避玩家

可以批量 tick。

### Narrative Plan

高风险计划：

- 试探玩家知道多少
- 转移某 NPC 注意力
- 暗示某条 safe clue
- 传播误导性 hearsay
- 阻止玩家进入某场景

必须经过 Director 和 Rule Engine。

## 多 Agent 编排策略

不要一次性让 25 个 NPC 每 tick 都调用 LLM。生产上必须分级。

### P0：事件驱动 NPC 反应

只在玩家动作后触发相关 NPC：

- 目标 NPC
- 同场景 NPC
- 被线索关联的 NPC
- 被关系网络影响的 NPC

输出是事件派生和可能的 delayed intent。

### P1：低频小镇 tick

每 N 分钟游戏时间推进一次：

- 移动
- routine schedule
- scene occupancy
- low-risk observation

不调用真实 LLM，优先规则和 mock。

### P2：高价值 Social Encounter

只对剧情相关 NPC 对话调用 LLM：

- 两个 NPC 在同场景
- 有共享或冲突 memory
- 当前 phase 允许
- Director 判断不会提前剧透

### P3：长线反思与计划

章节结束、天结束或关键 beat 后触发：

- 生成 private belief
- 生成 strategy memory
- 更新 schedule
- 更新 relationship stance

这些都要写事件，并可 replay。

## 与现有系统的接点

最小改动接点：

- `SessionState` 增加 schedule / location 投影，或先只通过 events replay 派生。
- `RuleEngine` 增加 NPC autonomous action 校验。
- `DerivedEventSystem` 增加 npc observation / hearsay / reflection 派生。
- `MemoryRetriever` 复用现有 scope、authority、phase、forbidden filters。
- `NarrativeDirector` 增加 `precheck_npc_autonomy` 和 `validate_npc_social_output`。
- `RuntimeTrace` 增加 `orchestration_trace`，只记 id 和决策摘要，不记敏感正文。

## 必须避免的错误

- 不要让 NPC 直接互传完整 memory content。
- 不要让 LLM 自己决定“谁听到了什么”。
- 不要把 NPC 反思当世界事实。
- 不要用 group chat 代替事件传播。
- 不要让小镇 emergent behavior 推进主线真相。
- 不要把每个 tick 都变成真实 LLM 调用。

## 推荐实施顺序

1. 定义 NPC location / scene occupancy 的事件和 replay。
2. 定义 `npc.observed`，让 NPC 只观察同场景安全事件。
3. 用规则派生 `npc_private` / `scene_shared` memory，不调用 LLM。
4. 定义 `npc.hearsay.received`，并标记 `authority_source=npc_hearsay`。
5. 增加 `TownOrchestrator.tick_once(...)`，先只做规则移动和观察。
6. 增加 social encounter selector，只选少量高价值 NPC-NPC 互动。
7. 接入 LLM 生成 `NpcAutonomyIntent`，但仍经 Director / RuleEngine。
8. 增加小镇长跑回归：固定 tick 序列、固定事件序列、固定 replay 状态。

## 验收标准

小镇式多 Agent 编排上线前必须满足：

- 同一事件序列 replay 后 NPC location、memory、relationship、phase 完全一致。
- NPC 不知道不同场景、不同权限或未传播给自己的事实。
- hearsay memory 不会压过 player_evidence / rule_derived memory。
- Director 能拦截 NPC-NPC 对话中的 forbidden inference。
- 长跑 100 tick 不产生未授权 clue unlock、phase change 或 solution leak。
- trace 能回答：某 NPC 为什么在某时刻去某地、听到了什么、记住了什么、为什么对玩家改变态度。

