# 多 Agent 编排 V1 执行计划

生成时间：2026-06-27

## 总体路线

V1 不做开放式 AI 小镇，不做 NPC 群聊，不做全员每 tick 调 LLM。V1 只补齐生产级多 Agent 的底座：

```text
WorldEvent
  -> replay 还原位置和时钟
  -> PerceptionSystem 判断 NPC 可见事件
  -> npc.observed
  -> DerivedEventSystem 派生记忆候选
  -> MemorySnapshotSystem 更新记忆快照
  -> NpcAutonomyIntent 只作为候选
  -> Director 预审
  -> RuleEngine 执行或拒绝
  -> WorldEvent
```

核心原则：NPC 可以“看见、记住、移动、等待、尝试对话”，但不能直接改线索、改阶段、写 memory 或共享私有上下文。

## P0：废弃旧生产入口假设

明确 `AgentOrchestrator.run_secondary_reactions(...)` 不是生产多 Agent 入口。它只是把玩家 `PlayerAction` 复制给其他 NPC，缺少场景、感知、触发原因和规则裁决。

动作：

- 保留为测试/实验夹具。
- 新生产入口放到 `app/runtime/town_orchestrator.py`。
- 文档标明不要在正式链路中调用 `run_secondary_reactions` 做二级反应。

验收：

- 代码和文档都能说明多 Agent 编排入口是 `TownOrchestrator`，不是 `AgentOrchestrator`。

## P1：事件类型、位置状态和 replay

先做可回放状态，不做调度智能。

新增模型：

```text
TownClockState
  tick_id
  game_time
  phase_id
  caused_by_event_id

NpcLocationState
  character_id
  scene_id
  updated_at_tick
  source_event_id
```

新增事件：

```text
town.tick.advanced
npc.location.changed
```

`SessionState` 新增：

```text
town_clock
npc_locations
```

验收：

- 固定事件序列 replay 后，`town_clock` 和 `npc_locations` 完全一致。
- 非法 character / scene 不会产生合法位置变更。
- 首次 session 初始化能得到确定 NPC 初始位置。

## P2：RuleEngine 执行 NPC 移动

移动不能由 orchestrator 直接改状态，必须由 RuleEngine 写事件。

新增接口：

```text
RuleEngine.apply_npc_location_change(...)
```

或直接作为 `apply_npc_autonomy_intent(move)` 的子路径实现。

规则：

- actor 必须是已知 NPC。
- target scene 必须存在。
- from scene 必须匹配当前 `SessionState.npc_locations`，初始化移动除外。
- 成功写 `npc.location.changed`。
- 失败写 `rule.rejected` 或 `npc.autonomy_intent.rejected`。

验收：

- 合法移动改变 replay 投影。
- 非法移动只落拒绝事件，不改变位置。

## P3：PerceptionSystem 和 npc.observed

位置稳定后再做可见性。

新增模块：

```text
app/runtime/perception.py
```

新增事件：

```text
npc.observed
```

payload 只放引用和安全元数据：

```text
observer_id
observed_event_id
scene_id
visibility
perception_quality
redacted_payload_ref
```

可见性规则：

- 同场景公共事件可见。
- `present_clue(private)` 只给目标 NPC，不给缺席 NPC。
- `present_clue(scene_shared)` 只给 runtime 当前在场 NPC。
- `director.blocked`、`rule.rejected`、`director_audit` memory、NPC private memory 不进入普通 NPC 感知。

必须修正：

- `RuleEngine.apply_present_clue(scene_shared)` 的 `present_character_ids` 不能继续来自静态 `SceneConfig.characters`，必须来自 `SessionState.npc_locations`。

验收：

- 缺席 NPC 不产生 `npc.observed`。
- 同场景 NPC 只观察到允许观察的事件。
- `npc.observed` 不复制敏感 payload。

## P4：观察派生记忆

继续使用 `DerivedEventSystem`，不允许 LLM 直接写 memory。

新增派生：

```text
npc.observed
  -> memory_candidate.created
  -> agent_memory_snapshot.updated
```

观察记忆建议：

```text
memory_type = episodic
memory_scope = npc_private 或 scene_shared
memory_layer = working
metadata.authority_source = world_event
metadata.authority = event_observed
source_event_ids = [npc.observed, observed_event_id]
```

验收：

- 观察记忆只进入 observer 可见上下文。
- scene_shared 记忆只对合法在场角色可见。
- Director 审计事件不会通过观察链进入普通 NPC 记忆。

## P5：低权威传闻

传闻是主观 belief，不是事实。

新增事件：

```text
npc.hearsay.received
```

传闻记忆：

```text
memory_type = belief
memory_scope = npc_private
metadata.authority_source = npc_hearsay
metadata.authority = non_authoritative
metadata.non_authoritative = true
confidence <= 0.5
```

规则：

- 传闻不能解锁 clue。
- 传闻不能推进 phase。
- 传闻不能覆盖 `player_evidence`、`rule_derived`、`world_event`、`npc_direct`。
- 传闻只能影响 NPC 语气、怀疑、试探和策略。

验收：

- memory authority 冲突时，hearsay 输给更高权威记忆。
- 100 tick 不因传闻产生 clue unlock 或 phase change。

## P6：NpcAutonomyIntent

NPC 自主意图不复用 `PlayerAction`。

V1 只支持：

```text
move
observe
wait
talk_to
```

新增模型：

```text
NpcAutonomyIntent
  actor_id
  intent_type
  target_scene_id
  target_character_id
  topic_refs
  memory_refs
  speech
  risk_flags
```

新增事件：

```text
npc.autonomy_intent.proposed
npc.autonomy_intent.rejected
```

验收：

- 意图只是候选，不能直接改状态。
- 非法目标、非法场景、跨场景 talk_to 都能被拒绝并落事件。
- 自主意图默认不能 discover clue 或 change phase。

## P7：Director + RuleEngine 审计链

新增 Director 入口：

```text
NarrativeDirector.precheck_npc_autonomy(case, session, intent)
```

新增 RuleEngine 入口：

```text
RuleEngine.apply_npc_autonomy_intent(case, session, intent, caused_by_event_id)
```

职责划分：

- Director 判断叙事风险、剧透风险、阶段越权。
- RuleEngine 判断 actor、scene、target、可达性、状态副作用。
- Orchestrator 只负责组织 tick 和候选，不直接写状态。

验收：

- 所有自主行为可以被拒绝。
- 所有接受和拒绝都能通过 WorldEvent replay 追溯。

## P8：TownOrchestrator V1

最后组装 deterministic tick。

新增模块：

```text
app/runtime/town_orchestrator.py
```

V1 tick：

```text
TownOrchestrator.tick_once(session)
  -> town.tick.advanced
  -> deterministic npc move/wait candidates
  -> Director precheck
  -> RuleEngine apply/reject
  -> PerceptionSystem produce npc.observed
  -> DerivedEventSystem derive memory candidates
  -> MemorySnapshotSystem update snapshots
```

V1 不做：

- 不调 LLM。
- 不做 NPC 群聊。
- 不做 NPC 直接共享 memory。
- 不让 NPC 自主解锁关键线索或推进 phase。

验收：

```text
town.tick
  -> npc.location.changed
  -> npc.observed
  -> memory_candidate.created
  -> agent_memory_snapshot.updated
  -> replay 可还原
```

## P9：高价值社交遭遇，延后

V1 通过后再做 `SocialEncounterSelector` 和 NPC-NPC LLM 对话。

准入条件：

- replay、可见性、记忆派生、传闻权威、NPC 自主意图拒绝链全部稳定。
- 100 tick 长跑无未授权 clue unlock、phase change、solution leak。
- mock LLM 覆盖正常对话、越权泄露、传闻传播、错误目标和预算超限。

## 最终标准

多 Agent 编排是否能进下一阶段，只看三点：

- 能 replay：同一事件序列还原同一状态。
- 能解释：NPC 为什么知道、移动、等待、说话，都能追到事件。
- 能拒绝：任何自主意图、传闻、LLM 输出都能被 Director 或 RuleEngine 拒绝。

这三点没闭环前，不做高价值 LLM 社交遭遇。

