# 多 Agent 七步第一版评审

生成时间：2026-06-27

## 结论

这 7 步是合理的，而且是当前项目进入 NPC 自主行为前应采用的最小生产闭环。它没有从“多 NPC 调 LLM 聊天”入手，而是先补齐世界模拟最缺的三件事：

- NPC 在哪里。
- NPC 能看见什么。
- NPC 看见后如何以事件和低权威记忆进入可回放状态。

这正好匹配当前项目的核心边界：LLM 只能生成表达、推理和候选意图；真实状态变化必须由 RuleEngine、DerivedEventSystem、MemorySnapshotSystem 和 WorldEvent 链路裁决。

但第一版要收紧三个点：

1. `town.tick` 不能先成为自由调度器，必须先成为确定性事件边界。
2. `present_character_ids` 不能继续只依赖静态 `SceneConfig.characters`，引入 `npc_locations` 后，在场权威必须来自 replay 后的 `SessionState`。
3. `NpcAutonomyIntent` 第一版应只支持 `move`、`observe`、`wait`、`talk_to`，不要提前放入 `ask/share_hearsay/investigate`，否则会绕开“候选意图不能改状态”的验收边界。

## 当前代码判断

现有代码已经适合承接这套方案的部分：

- `app/runtime/replay.py` 已经是从 `WorldEvent` 重建 `SessionState` 的权威入口。
- `app/runtime/derivations.py` 已经按事件类型分发派生逻辑，可以扩展 `npc.observed` 和 `npc.hearsay.received`。
- `app/runtime/memory_snapshots.py` 已经把 `memory_candidate.created` 聚合为 `agent_memory_snapshot.updated`。
- `app/agents/memory_authority.py` 已经有 `npc_hearsay` 权威等级，且低于 `world_event`、`player_evidence`、`rule_derived`。
- `app/director/narrative_director.py` 和 `app/rules/engine.py` 已经形成“生成前后审计 + 规则裁决”的硬边界。

当前不适合直接复用的部分：

- `app/agents/orchestrator.py::AgentOrchestrator.run_secondary_reactions(...)` 只是复制同一个 `PlayerAction` 给其他 NPC。它没有场景可见性、没有观察事件、没有 NPC 自主语义，也不能解释为什么某个 NPC 参与反应。它只能保留为测试或实验夹具，不能作为生产入口。
- `RuleEngine.apply_present_clue(...)` 当前 `scene_shared` 的在场角色来自 `SceneConfig.characters`。NPC location 落地后，这里必须改为以 `SessionState.npc_locations` 计算，否则缺席 NPC 仍可能被静态场景配置错误加入可见集合。
- `EventType` 还没有 `town.tick.advanced`、`npc.location.changed`、`npc.observed`、`npc.hearsay.received` 等事件；`SessionState` 也还没有 `town_clock` 和 `npc_locations` 投影。

## 七步方案评审

### 1. NPC 位置状态

合理，且必须最先做。没有位置状态，后面的可见性、私聊隔离、公共展示、NPC-NPC 对话都没有可靠依据。

第一版只需要：

```text
EventType.NPC_LOCATION_CHANGED = "npc.location.changed"
SessionState.npc_locations: dict[character_id, NpcLocationState]
replay_events(...) applies npc.location.changed
```

位置事件 payload 必须至少包含：

```text
character_id
from_scene_id
to_scene_id
reason
tick_id
```

`from_scene_id` 可以为空，用于 session 初始化或首次投影。

### 2. 小镇 tick

合理，但 tick 第一版必须极简。`TownOrchestrator.tick_once(session)` 的职责不是“让 NPC 活起来”，而是推进一个确定性时间片，并产生可审计事件。

第一版 tick 只允许：

```text
town.tick.advanced
npc.location.changed
npc.observed
```

不要调 LLM，不要做群聊，不要反思，不要自动推理案件真相。

### 3. NPC 可见性感知

合理，是这套编排的核心。`PerceptionSystem` 必须按事件引用工作，不复制敏感 payload。

可见性默认策略：

- 同场景公共事件可观察。
- 私聊、私有记忆、Director 审计事件不可观察。
- `scene_shared` 事件只给事件 payload 中授权的在场角色。
- `rule.rejected` 和 `director.blocked` 默认不可进入普通 NPC 感知。

`npc.observed` payload 应只记录：

```text
observer_id
observed_event_id
scene_id
visibility
perception_quality
redacted_payload_ref
```

不要把玩家原文、memory content、safe fragment summary 或 forbidden fact 文本塞进观察事件。

### 4. 感知派生记忆

合理，且必须继续走 `DerivedEventSystem`。这是防止 LLM 直接写 memory 的关键。

`npc.observed -> memory_candidate.created -> agent_memory_snapshot.updated` 应成为固定链路。观察记忆建议：

```text
memory_type = episodic
memory_scope = npc_private 或 scene_shared
memory_layer = working
metadata.authority_source = world_event
metadata.authority = event_observed
source_event_ids = [npc.observed, observed_event_id]
```

### 5. 低权威传闻

合理，但第一版要把它限制为“已经有来源事件的转述”，不能做无源谣言生成。

传闻记忆建议：

```text
memory_type = belief
memory_scope = npc_private
metadata.authority_source = npc_hearsay
metadata.authority = non_authoritative
metadata.non_authoritative = true
confidence <= 0.5
```

验收必须明确：

- 传闻不能解锁 clue。
- 传闻不能推进 phase。
- 传闻不能覆盖更高权威记忆。
- 传闻只能影响 NPC 语气、怀疑和试探策略。

### 6. NPC 自主意图

合理，且必须不复用 `PlayerAction`。`PlayerAction` 是玩家输入边界，NPC 自主行为如果伪装成它，会污染 API 语义和审计语义。

第一版 `NpcAutonomyIntent` 建议只支持：

```text
move
observe
wait
talk_to
```

不要第一版加入 `ask`、`share_hearsay`、`investigate`。这些行为更接近线索/知识传播，必须等前五步的 replay、感知、传闻权威测试稳定后再加。

### 7. Director + RuleEngine

合理，而且是上线前硬门槛。

新增接口建议：

```text
NarrativeDirector.precheck_npc_autonomy(case, session, intent)
RuleEngine.apply_npc_autonomy_intent(case, session, intent, caused_by_event_id)
```

规则默认应保守：

- 非法角色、非法场景、不可达场景直接拒绝。
- `talk_to` 目标不在同场景直接拒绝，除非案件配置显式允许远程通信。
- 自主意图默认不能产生 `clue.discovered`。
- 自主意图默认不能产生 `narrative.phase.changed`。
- 所有拒绝必须落 `rule.rejected` 或 `npc.autonomy_intent.rejected`。

## 推荐第一版闭环顺序

用户给出的最小闭环是正确的：

```text
town.tick
  -> npc.location.changed
  -> npc.observed
  -> memory_candidate.created
  -> agent_memory_snapshot.updated
  -> replay 可还原
```

实现顺序建议更精确为：

1. 事件类型 + `TownClockState` / `NpcLocationState` / `SessionState.npc_locations`。
2. replay 还原 `town_clock` 和 `npc_locations`。
3. RuleEngine 写入合法 `npc.location.changed`，非法移动可拒绝。
4. `TownOrchestrator.tick_once(...)` 只推进 tick 和确定性移动。
5. `PerceptionSystem` 根据 `session.npc_locations` 生成 `npc.observed`。
6. `DerivedEventSystem` 从 `npc.observed` 派生记忆。
7. MemorySnapshotSystem 聚合 snapshot，并用 replay 测试锁死结果。
8. 再补 `npc.hearsay.received` 和低权威 belief。
9. 最后接 `NpcAutonomyIntent` 的 Director / RuleEngine 审计链。

## 必须补的测试

- replay 固定事件序列后 NPC 位置完全一致。
- 缺席 NPC 不产生 `npc.observed`。
- 私聊 `present_clue(private)` 不被其他 NPC 观察。
- `scene_shared` 只被当前 runtime 在场 NPC 观察，而不是静态场景全员。
- `director.blocked`、`rule.rejected`、`director_audit` memory 不进入普通 NPC 感知。
- `npc.observed` 派生的 memory 只进入 observer 可见上下文。
- `npc_hearsay` belief `confidence <= 0.5`，且不会触发 clue unlock 或 phase change。
- `NpcAutonomyIntent(move/talk_to)` 非法目标能被拒绝并落事件。

## 最终判断

这套编排合理，且是当前项目多 Agent 化的最优第一步。真正的问题不是“NPC 不够自主”，而是当前还缺可回放的位置、可见性和自主意图裁决层。先把这 7 步做完，再谈 NPC-NPC 对话和高价值 LLM 社交遭遇，技术风险会低一个数量级。

