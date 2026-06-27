# 多 Agent 编排实施蓝图

生成时间：2026-06-27

## 核心做法

多 Agent 编排不从“多个 LLM 互相聊天”开始，而从“世界事件如何被不同 NPC 看见、记住、误传、反应”开始。当前后端已有玩家动作链、`AgentLoop`、`NarrativeDirector`、`RuleEngine`、`DerivedEventSystem` 和 memory authority，应该沿这条权威链扩展。

第一版目标：

```text
玩家动作 / tick 事件
  -> WorldEvent
  -> NPC 可见性感知
  -> 规则派生私有/共享记忆
  -> 少量 NPC 自主意图候选
  -> Director 预审
  -> RuleEngine 执行或拒绝
  -> 新 WorldEvent
```

不做：

```text
NPC 群聊
全员每 tick 调 LLM
LLM 直接改世界状态
NPC 通过共享上下文互相污染记忆
```

## 代码落点

新增模块优先放在 `app/runtime`，因为这是世界运行时编排，不是单个 Agent 生成能力。

建议新增：

```text
app/runtime/town_orchestrator.py
app/runtime/perception.py
app/runtime/npc_autonomy.py
app/runtime/social_encounters.py
```

不要继续扩展 `app/agents/orchestrator.py` 作为生产入口。它目前的 `run_secondary_reactions` 是测试夹具性质，核心问题是复制玩家 action 给其他 NPC，缺少场景、感知、触发原因和规则裁决。

## 第一阶段：NPC 位置和小镇时钟

先新增确定性世界投影，不接 LLM。

领域模型建议：

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

事件建议：

```text
town.tick.advanced
npc.location.changed
```

`SessionState` 增加：

```text
town_clock
npc_locations
```

`replay_events(...)` 必须能从事件还原这两个投影。

第一阶段验收：

- 固定 tick 序列 replay 后 NPC 位置完全一致。
- 非法 scene / character 会被 RuleEngine 拒绝。
- 前端只读取公开位置投影，不看到 NPC 私有计划。

## 第二阶段：NPC 感知

新增 `PerceptionSystem`，输入最近事件和 NPC 当前场景，输出可见观察事件。

事件建议：

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

不要复制原事件敏感 payload。尤其不要把玩家原文、private memory、safe fragment summary、forbidden fact 文本带进去。

规则：

- 同场景公开事件可观察。
- 私聊 `present_clue(private)` 不给缺席 NPC。
- `scene_shared` 事件只给 `present_character_ids`。
- `director.blocked`、`rule.rejected`、其他 NPC private memory 默认不可观察。

第二阶段验收：

- 缺席 NPC 不产生 `npc.observed`。
- 同场景 NPC 可观察公开展示或公开移动。
- replay 后感知事件数量和 observer 完全一致。

## 第三阶段：由感知派生记忆

扩展 `DerivedEventSystem`，让 `npc.observed` 派生低风险记忆。

建议 memory：

```text
memory_scope = npc_private | scene_shared
memory_layer = working
memory_type = episodic
metadata.authority_source = world_event
metadata.authority = event_observed
source_event_ids = [npc.observed, observed_event_id]
```

如果是听别人转述，不走 `npc.observed` 的直接观察权威，必须走 `npc.hearsay.received`。

第三阶段验收：

- 观察记忆只进入 observer 的上下文。
- scene_shared 只进入合法在场角色集合。
- Director audit memory 不会借感知链进入普通 NPC。

## 第四阶段：传闻传播

新增传闻事件：

```text
npc.hearsay.received
```

传闻记忆必须低权威：

```text
memory_type = belief
memory_scope = npc_private
metadata.authority_source = npc_hearsay
metadata.authority = non_authoritative
confidence <= 0.5
```

规则：

- 传闻不能解锁线索。
- 传闻不能推进 phase。
- 传闻不能覆盖 `player_evidence`、`rule_derived`、`world_event`、`npc_direct`。
- 传闻只能作为 NPC 主观态度、怀疑、试探的输入。

第四阶段验收：

- memory authority 冲突时传闻输给更高权威来源。
- 传闻能影响 NPC 语气或策略，但不能成为案件事实。

## 第五阶段：NPC 自主意图

新增 `NpcAutonomyIntent`，不要复用 `PlayerAction`。

建议结构：

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

新增事件：

```text
npc.autonomy_intent.proposed
npc.autonomy_intent.rejected
```

Director 增加：

```text
precheck_npc_autonomy(...)
validate_npc_social_output(...)
```

RuleEngine 增加：

```text
precheck_npc_autonomy_action(...)
apply_npc_autonomy_intent(...)
```

第五阶段验收：

- NPC 不能移动到非法 scene。
- NPC 不能向不在同场景的目标直接说话，除非案件规则显式允许远程通信。
- NPC 自主意图默认不能 discover clue 或 change phase。
- 所有拒绝都落 `rule.rejected` 或 `npc.autonomy_intent.rejected`。

## 第六阶段：社交遭遇选择

新增 `SocialEncounterSelector`，只挑高价值 NPC-NPC 互动候选。

候选条件：

- 两个 NPC 同场景。
- 当前 phase 允许社交互动。
- 双方有共享观察、冲突记忆、关系张力或同一案件线程。
- Director 预判不会提前泄露 forbidden inference。
- 本 tick 未超过 LLM 调用预算。

输出 trace：

```text
orchestration_trace
  tick_id
  source_event_ids
  candidate_npc_ids
  selected_npc_ids
  reason_codes
  director_precheck_result
  rule_result_event_ids
```

第六阶段验收：

- 没有候选时不调用 LLM。
- 候选选择可解释。
- trace 不含私有正文和 memory content。

## 第七阶段：高价值 LLM NPC-NPC 对话

最后再接 LLM。新增 `NpcInteractionContext`，不要把 NPC-NPC 对话伪装成玩家 `talk`。

上下文字段围绕：

```text
actor_npc
target_npc
shared_scene
visible_event_refs
shared_memory_refs
relationship_between_npcs
director_safe_fragments
output_contract
```

输出仍然是结构化 intent，仍然先过 schema、本地合同、Director，再给 RuleEngine。

第七阶段验收：

- mock LLM 测试覆盖正常对话、越权泄露、传闻传播、错误目标、预算超限。
- 真实 LLM 只在 shadow eval 或明确配置后启用。
- 100 tick 长跑无未授权真相泄露、无非法 phase change、无 NPC private memory 污染。

## 推荐排期

优先级按风险和收益排序：

1. 事件类型、`SessionState` 投影、replay 测试。
2. `PerceptionSystem` 和 `npc.observed`。
3. 感知派生 memory。
4. `npc.hearsay.received` 和低权威传闻。
5. deterministic `TownOrchestrator.tick_once(...)`。
6. `NpcAutonomyIntent` + Director / RuleEngine 审计。
7. `SocialEncounterSelector`。
8. NPC-NPC LLM 对话。

## 判断标准

这套编排是否正确，看三点：

- 能否 replay：同一事件序列必须还原同一世界状态。
- 能否解释：每个 NPC 为什么知道、为什么移动、为什么说话，都能追溯到事件。
- 能否拒绝：任何 LLM 输出、传闻、反思、社交行为都能被 Director 或 RuleEngine 拒绝。

只要这三点没闭环，就不该上开放式 AI 小镇。

