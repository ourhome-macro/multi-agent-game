# API 契约

当前 API 覆盖内存版后端叙事运行时。它默认不调用真实 LLM，也不把 session 持久化到数据库。

## 接口列表

- `GET /health`
- `GET /cases`
- `POST /sessions`
- `POST /sessions/{session_id}/actions`
- `GET /sessions/{session_id}/state`
- `GET /sessions/{session_id}/events`

## 创建 Session

使用默认案件：

```json
{}
```

指定案件：

```json
{ "case_id": "fake_case_002" }
```

响应包含 `session_id` 和公开 `StateSummary`。

## PlayerAction

所有玩家动作目标统一使用 `target_id`。如果请求使用旧字段 `target`，会被 422 拒绝。

### inspect

```json
{
  "type": "inspect",
  "target_id": "desk"
}
```

`target_id` 必须是已知场景热点。未知调查目标返回 404，且不会写入 `player.inspected`。

### talk

```json
{
  "type": "talk",
  "target_id": "butler",
  "text": "Where were you?"
}
```

`target_id` 必须是已知角色。未知对话目标返回 404，且不会写入 `player.talked`。

### ask_about

```json
{
  "type": "ask_about",
  "target_id": "butler",
  "subject_type": "clue",
  "subject_id": "scratched_drawer",
  "text": "What about the drawer?"
}
```

`subject_type` 必须是 `clue`、`character` 或 `scene`。

Rule Engine 会校验：

- `target_id` 是已知角色
- clue subject 存在，且已被玩家发现或已在玩家已知账本中
- character subject 是已知角色
- scene subject 是已知场景

校验成功时写入 `player.asked_about`，payload 示例：

```json
{
  "target_id": "butler",
  "subject_type": "clue",
  "subject_id": "scratched_drawer",
  "text": "What about the drawer?",
  "interaction_pressure": 0.6,
  "knowledge_id": "player_knowledge.desk_forced_open"
}
```

校验失败时返回 `accepted=false`，写入 `rule.rejected`，不会产生 `npc.replied` 或关系变化。

### present_clue

```json
{
  "type": "present_clue",
  "target_id": "butler",
  "clue_id": "scratched_drawer",
  "text": "What about these scratch marks?"
}
```

`present_clue` 表示玩家用已知线索向 NPC 施压或试探。它不表示该线索已经证明 NPC 有罪，也不直接推进真相或阶段。

Rule Engine 会校验：

- `target_id` 是已知角色
- `clue_id` 存在于案件包
- `clue_id` 已经被发现
- 对应 `player_knowledge.<world_info_id>` 存在

校验失败时返回 `accepted=false`，写入 `rule.rejected`，不会产生 `npc.replied` 或关系变化。

校验成功时写入 `player.presented_clue`，payload 示例：

```json
{
  "target_id": "butler",
  "clue_id": "scratched_drawer",
  "knowledge_id": "player_knowledge.desk_forced_open",
  "text": "What about these scratch marks?",
  "interaction_pressure": 0.9
}
```

之后进入 `AgentGateway -> NarrativeDirector -> RuleEngine` 链路。

### accuse

```json
{
  "type": "accuse",
  "target_id": "butler",
  "claim_id": "butler_moved_key",
  "evidence_clue_ids": [
    "scratched_drawer",
    "dustless_frame",
    "torn_note"
  ],
  "text": "You moved the key and staged the study entry."
}
```

`accuse` 是结构化正式指控。它不调用 `AgentGateway`，不使用 LLM，也不让 NPC 判断指控是否正确。Rule Engine 根据 `solution_claims.yaml` 评估。

Rule Engine 会校验：

- `target_id` 是已知角色
- `claim_id` 存在
- claim 的 `target_id` 与动作 `target_id` 一致
- 当前剧情阶段允许该 claim
- `evidence_clue_ids` 非空
- 所有 evidence id 都存在于案件包
- 所有 evidence clue 都已被发现
- 所有 evidence clue 都已进入玩家已知账本
- 玩家提交的 evidence 覆盖 claim 的 `required_evidence`
- 玩家已知 WorldInfo 覆盖 claim 的 `required_world_info`

校验失败时返回 `accepted=false`，写入 `rule.rejected`，不会产生 `player.accused`、`accusation.evaluated`、`npc.replied`、关系变化或记忆污染。

校验成功时写入 `player.accused` 和 `accusation.evaluated`。结果来自案件配置，不来自自然语言推理。`accuse` 不直接改变剧情阶段；如果 `narrative_rules.yaml` 定义了匹配事件触发的 beat，后续 `RuleTriggerSystem` 可写入 `narrative.beat.completed` 和 `narrative.phase.changed`。

## 交互压力

后端计算 `interaction_pressure`：

- `talk`：基础 `0.1`
- `ask_about`：基础 `0.3`
- `present_clue`：基础 `0.6`
- 关联 subject 或 clue 命中 NPC：`+0.2`
- 关键线索：`+0.1`
- 最终值限制在 `0.0 .. 1.0`

## 事件

重要事件类型包括：

- `session.created`
- `player.inspected`
- `player.talked`
- `player.asked_about`
- `player.presented_clue`
- `player.accused`
- `accusation.evaluated`
- `npc.replied`
- `director.blocked`
- `rule.rejected`
- `clue.discovered`
- `relationship.changed`
- `relationship.threshold.crossed`
- `player_knowledge.updated`
- `memory_candidate.created`
- `agent_memory_snapshot.updated`
- `character_impression.updated`
- `narrative.beat.completed`
- `narrative.phase.changed`

`relationship.changed.payload.current` 总是包含限制在 `-1.0 .. 1.0` 的关系指标。

`player_knowledge.updated` 记录玩家通过什么来源掌握了哪个 WorldInfo，包含：

- `clue_id`
- `world_info_id`
- `knowledge_id`
- `confidence`
- `acquisition`
- `source_type`
- `source_event_id`
- `title`
- `summary`

`memory_candidate.created` 是重要事件派生出的候选记忆。`agent_memory_snapshot.updated` 是运行时派生的稳定记忆快照更新，actor 是 `memory_snapshot_system`。

`character_impression.updated` 记录运行时派生的 NPC -> player 私有画像，不由 Agent 或 LLM 直接生成。

## StateSummary

`StateSummary` 是公开状态视图。它可以包含已发现线索、完成的 beats、公开关系指标和玩家已知摘要。v0 不暴露记忆快照或私有角色画像，也不暴露 `solution_claims` 或指控真相配置。

角色 `private` 数据是 NPC 自己的非公开视角，不是对 NPC 自己隐藏。API 边界是：原始 private 数据不能返回给玩家、其他 NPC、公开 summary 或 journey artifacts。`AgentContext.inner_context` 不属于公开 API 响应。

角色摘要只暴露公开角色卡字段：

- `id`
- `display_name`
- `public_role`
- `public_description`

不得暴露：

- character `secrets`
- character `goals`
- internal character `knowledge`
- private character impressions
- character-card `private`
- `inner_context`
- clue `truth_status`
- forbidden fact text 或 blocked terms
- `forbidden_facts`
- `solution_claims`

## 错误

- 未知 `case_id`：404
- 未知 `session_id`：404
- 未知 inspect target：404
- 未知 talk target：404
- 请求 schema 非法：422
- `ask_about`、`present_clue` 或 `accuse` 证据状态非法：200 + `accepted=false` + `rule.rejected`
