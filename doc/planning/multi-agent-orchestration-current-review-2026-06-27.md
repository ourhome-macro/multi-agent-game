# 多 Agent 编排当前评审

生成时间：2026-06-27

## 结论

可以参考 Stanford Generative Agents / Smallville，但不能直接采用“小镇里每个 NPC 自由 tick、自由对话、自由反思”的形态。本项目是悬疑叙事运行时，核心资产是案件真相、线索释放节奏、NPC 视角隔离和事件可回放。合理路线是把 Smallville 改造成事件驱动的受控世界模拟层：

```text
WorldEvent
  -> NPC 可见性感知
  -> 规则派生记忆
  -> 低频日程/意图候选
  -> Director 叙事审计
  -> RuleEngine 状态裁决
  -> 新 WorldEvent
```

不应采用：

```text
NPC A LLM -> NPC B LLM -> NPC C LLM -> 共享上下文
```

那会直接破坏本项目已经建立的记忆隔离、事实网关和 replay 权威。

## 当前后端现状

当前后端 agent 链路已经具备生产级边界的雏形：

- `ActionService` 把玩家动作分为 `inspect`、`talk`、`ask_about`、`present_clue`、`accuse`。其中 `talk`、`ask_about`、`present_clue` 才进入 agent-backed 链路。
- `AgentLoop.run_turn(...)` 是单目标 NPC turn：先做记忆检索，再构造 `AgentContext`，再注入 Director safe fragments，随后生成 `AgentTurnPlan`、`LLMAgentContractInput`、provider payload、预算审计，最后调用 `AgentGateway` 并做本地合同校验。
- `NarrativeDirector.validate(...)` 在 `npc.replied` 事件写入前审计最终 speech。
- `RuleEngine.apply_agent_intent(...)` 只执行白名单 `proposed_actions`，并明确拒绝 Agent 直接推动 narrative phase。
- `DerivedEventSystem` 已经把 `player.asked_about`、`player.presented_clue`、`director.blocked`、`accusation.evaluated` 等事件派生为玩家已知、角色事实认知、记忆候选和画像事件。
- 记忆权威层已经预留 `npc_hearsay`，且权威 rank 很低，适合承接未来 NPC 传闻传播。

当前缺失的是小镇式编排需要的世界模拟基础：

- 没有 `npc.location.changed`、`npc.schedule.updated`、`npc.observed`、`npc.hearsay.received`、`npc.autonomy_intent.proposed` 等事件。
- `SessionState` 和 replay 还没有 NPC 位置、场景占用、日程状态和感知收件箱投影。
- 现有 `AgentOrchestrator.run_secondary_reactions(...)` 只是把同一个玩家 `PlayerAction` 复制给其他 NPC，并按角色顺序截断。它可以作为“上下文不泄漏”的测试夹具，但不能作为生产级多 Agent 编排。原因是它没有场景可见性、没有 NPC-NPC 语义、没有独立触发事件，也无法解释“为什么这个 NPC 参与反应”。

根因不是缺一个更会聊天的多 Agent 框架，而是缺一层可回放、可审计、受规则约束的 NPC 感知与自主行为模型。

## 对 Stanford AI 小镇的判断

Smallville 可借鉴的部分：

- memory stream：NPC 经历都进入长期记忆流。
- retrieval：按相关性、近因、重要性召回。
- reflection：从低层经历生成高层主观认知。
- planning：日程计划和短期行为意图。
- observation：NPC 观察环境和其他角色行为。
- conversation：NPC 之间通过对话传播信息。
- emergence：局部信息经社交网络扩散，形成看似自然的群体行为。

本项目必须改写这些机制：

- memory stream 只能由 `WorldEvent` 和派生规则写入，不能由 LLM 直接写。
- reflection 只能生成 `belief`、`strategy`、`impression`，不能生成 world truth、solution claim 或 clue unlock。
- planning 只能提出 `NpcAutonomyIntent`，不能执行真实状态变化。
- conversation 必须先落 `npc.social_interaction.*` 或 `npc.hearsay.received` 事件，再由可见性和权威规则派生记忆。
- emergence 只能发生在 Director 允许的叙事带宽内，不能提前合成真相、推进阶段或解锁关键线索。

因此建议：不引入 Smallville 原型代码，不把它当运行时框架；只吸收 memory / reflection / planning / observation / conversation 的概念，并落在当前事件溯源架构上。

## 推荐编排方式

### 1. 保留玩家动作链路为主轴

玩家动作仍然是悬疑推进主轴：

```text
raw input / UI action
  -> ActionRouter / PlayerAction
  -> RuleEngine precheck
  -> ActionService
  -> AgentLoop
  -> NarrativeDirector
  -> RuleEngine
  -> DerivedEventSystem
  -> WorldEvent
```

多 Agent 编排不应接管这条链路，只能在玩家动作之后或低频 clock tick 中追加受控事件。

### 2. 新增 TownOrchestrator，但只调度候选

建议新增 `app/runtime/town_orchestrator.py`，不要扩展现有 `app/agents/orchestrator.py`。后者语义太偏“复制玩家回合”，继续往里堆会污染模型边界。

目标链路：

```text
TownOrchestrator.tick_once(session)
  -> collect_recent_world_events
  -> PerceptionSystem.visible_events_for(npc)
  -> append npc.observed
  -> MemoryDerivationSystem.derive
  -> SchedulePlanner.propose
  -> SocialEncounterSelector.select
  -> Director.precheck_npc_autonomy
  -> RuleEngine.apply_npc_autonomy_intent
  -> append derived events
```

`TownOrchestrator` 不直接调用数据库写状态，不直接改 `SessionState`，不直接写 memory snapshot。它只组织候选、调用已有权威系统并追加事件。

### 3. 先做确定性小镇 tick，不急着接 LLM

第一版 tick 只做三件事：

- NPC 位置和场景占用。
- NPC 对同场景公开事件的观察。
- 由观察事件派生 `npc_private` 或 `scene_shared` 记忆。

这些都应该由规则完成，不调用真实 LLM。只有这层稳定后，才允许在高价值社交遭遇中接入 LLM。

### 4. NPC-NPC 对话要有新语义，不能复用 PlayerAction 伪装

当前 `AgentContext`、`relationship_to_player`、`player_knowledge`、`interaction_pressure` 都是围绕“玩家询问某 NPC”设计的。把 NPC-NPC 对话伪装成 `PlayerAction(type=TALK)` 会让上下文语义失真。

建议新增结构：

```text
NpcAutonomyIntent
  actor_id
  intent_type: move | observe | talk_to | ask | share_hearsay | avoid | wait | investigate
  target_character_id
  target_scene_id
  topic_refs
  memory_refs
  proposed_actions
  speech
  risk_flags
```

并逐步新增 `NpcInteractionContext`，它与 `AgentContext` 共享安全投影原则，但字段必须以 `actor_npc`、`target_npc`、`shared_scene`、`visible_event_refs`、`shared_memory_refs` 为中心，而不是玩家视角。

### 5. 社交遭遇只做高价值选择

不要让所有 NPC 每个 tick 都调用 LLM。建议分层：

- P0：玩家动作后的相关 NPC 事件传播。目标 NPC、同场景 NPC、被展示线索影响的 NPC、关系网络强相关 NPC。
- P1：低频 deterministic tick。移动、等待、场景占用、观察，不调用 LLM。
- P2：高价值 NPC-NPC social encounter。只有同场景、同阶段允许、有共享事件或冲突记忆、Director 判断不会剧透时才调用 LLM。
- P3：章节/关键 beat 后 reflection。生成主观 belief / strategy，不生成事实。

候选选择必须记录 trace：

```text
orchestration_trace:
  tick_id
  source_event_ids
  candidate_npc_ids
  selected_npc_ids
  selection_reason_codes
  director_precheck_result
  rule_result_event_ids
```

trace 只能写 ID、计数和 reason code，不写私有正文、玩家原文、memory content 或 safe fragment summary。

## 事件和状态建议

建议先新增这些事件类型：

```text
town.tick.advanced
npc.location.changed
npc.schedule.updated
npc.observed
npc.autonomy_intent.proposed
npc.autonomy_intent.rejected
npc.social_interaction.started
npc.social_interaction.uttered
npc.social_interaction.ended
npc.hearsay.received
```

`npc.observed` payload 应只记录引用和安全摘要：

```text
observer_id
observed_event_id
scene_id
visibility
perception_quality
redacted_payload_ref
```

不要复制被观察事件的敏感 payload。

`npc.hearsay.received` 派生记忆时必须低权威：

```text
memory_type = belief
metadata.authority_source = npc_hearsay
metadata.authority = non_authoritative
confidence <= 0.5
```

这样传闻不会压过玩家证据、rule_derived 记忆或直接观察。

`SessionState` 最小新增投影：

```text
npc_locations: dict[character_id, scene_id]
npc_schedules: dict[character_id, NpcScheduleState]
town_clock: TownClockState
```

这些投影必须能从 `WorldEvent` replay 重建。

## Director 和 RuleEngine 接口建议

`NarrativeDirector` 增加两个入口：

```text
precheck_npc_autonomy(case, session, intent) -> DirectorDecision
validate_npc_social_output(case, session, intent, context) -> DirectorDecision
```

职责：

- 拒绝跨阶段主动揭示。
- 拒绝多个 safe fragment 被 LLM 合成为 solution claim。
- 拒绝 NPC 说出自己视角外的信息。
- 限制某阶段可发生的 NPC-NPC 社交主题。

`RuleEngine` 增加：

```text
precheck_npc_autonomy_action(...)
apply_npc_autonomy_intent(...)
```

职责：

- 校验 actor 是否存在、是否在可行动场景、目标是否同场景或可达。
- 校验 proposed action 是否允许。
- 执行 location、relationship、hearsay、social interaction 等事件。
- 对 clue discovery 和 phase change 保持强限制，默认拒绝。

## 实施顺序

1. 把 `AgentOrchestrator` 明确标注为测试/实验用途，生产路径不要使用它做二级反应。
2. 增加 NPC location / town clock 的领域模型、事件类型、replay 投影和单元测试。
3. 增加 `npc.observed`，只允许同场景或规则可见事件进入 NPC 感知。
4. 从 `npc.observed` 派生低风险 `npc_private` / `scene_shared` memory，不调用 LLM。
5. 增加 `npc.hearsay.received` 与低权威记忆派生。
6. 增加 deterministic `TownOrchestrator.tick_once(...)`，先覆盖移动、等待、观察。
7. 增加 SocialEncounterSelector，只产出候选和 trace，不急着调用真实 LLM。
8. 新增 `NpcAutonomyIntent` 和 Director / RuleEngine 审计链。
9. 最后才接入高价值 NPC-NPC LLM 对话，并且只允许 mock LLM 测试先通过。

## 验收标准

上线前必须满足：

- 同一事件序列 replay 后，NPC location、schedule、memory、relationship、phase 完全一致。
- 缺席 NPC 不会获得同场景事件、私聊展示线索或其他 NPC private memory。
- `npc_hearsay` 不会压过 `player_evidence`、`rule_derived`、`world_event`、`npc_direct`。
- 100 tick 长跑不会产生未授权 clue unlock、phase change 或 solution leak。
- Director 能阻断 NPC-NPC 对话里的 forbidden inference 和越权组合推理。
- trace 能回答“哪个事件触发了哪个 NPC 感知、记住、移动、说话或拒绝行动”，但不泄露私有正文。

## 当前取舍

最优路线不是马上做开放式 AI 小镇，而是先把“可见性事件化”和“NPC 自主意图受审计”做扎实。当前项目的优势是状态权威链已经很清楚，如果贸然引入全量多 Agent 自由模拟，反而会把最大的护城河破坏掉。

