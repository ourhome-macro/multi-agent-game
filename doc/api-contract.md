# API 契约

当前 API 默认使用内存版后端叙事运行时，便于本地开发和测试。生产环境可以通过 `AGENT_RUNTIME=postgres` 切换到 PostgreSQL event stream 运行时，让 session 创建、action 事件、投影恢复走数据库权威链路。

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

生产客户端提交 action 时应带 `Idempotency-Key` 请求头：

```http
POST /sessions/{session_id}/actions
Idempotency-Key: action-001
```

在 PostgreSQL runtime 下，后端会用结构化 `PlayerAction` 计算 request hash。同一 session 内重复提交相同 `Idempotency-Key` 和相同 action，会直接 replay 原响应事件，不再次运行 Agent/LLM，也不会产生第二批 `WorldEvent`。

冲突语义：

- 相同 `Idempotency-Key` 携带不同 action：返回 `409 Conflict`。
- 相同 session 的事件流在本轮 action 生成后被其他请求推进：返回 `409 Conflict`。
- 幂等键已占用但尚未提交响应事件：返回 `409 Conflict`。

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
  "presentation_mode": "private",
  "text": "What about these scratch marks?"
}
```

当众展示必须走显式结构化字段：

```json
{
  "type": "present_clue",
  "target_id": "jiang_yanhui",
  "clue_id": "empty_capsules",
  "presentation_mode": "scene_shared",
  "scene_id": "study",
  "text": "Show everyone the empty capsules."
}
```

`present_clue` 表示玩家用已知线索向 NPC 施压或试探。它不表示该线索已经证明 NPC 有罪，也不直接推进真相或阶段。

UI 推荐路径是“背包 / 已发现线索列表 -> 选择线索 -> 选择展示对象 -> 选择私下展示或当众展示”，然后由前端提交结构化 `PlayerAction`。自然语言 `ActionRouter` 只适合轻量兜底，不负责推断公共场景或在场 NPC。

Rule Engine 会校验：

- `target_id` 是已知角色
- `clue_id` 存在于案件包
- `clue_id` 已经被发现
- 对应 `player_knowledge.<world_info_id>` 存在
- `presentation_mode=private` 时禁止传入 `scene_id`
- `presentation_mode=scene_shared` 时必须传入 `scene_id`
- `presentation_mode=scene_shared` 时目标 NPC 必须位于该场景

校验失败时返回 `accepted=false`，写入 `rule.rejected`，不会产生 `npc.replied` 或关系变化。

校验成功时写入 `player.presented_clue`，payload 示例：

```json
{
  "target_id": "butler",
  "clue_id": "scratched_drawer",
  "scene_id": "study",
  "present_character_ids": ["butler", "niece"],
  "knowledge_id": "player_knowledge.desk_forced_open",
  "presentation_mode": "scene_shared",
  "text": "What about these scratch marks?",
  "interaction_pressure": 0.9
}
```

`player.presented_clue` payload 必须写出 `presentation_mode`。`scene_id` 和 `present_character_ids` 只在玩家明确当众展示线索时出现。没有 `scene_id` 且没有显式 `presentation_mode` 的旧请求仍按私下展示兼容处理；新客户端必须提交 `presentation_mode`，不能让后端从自然语言或静态场景自动扩散记忆。

之后进入 `AgentGateway -> NarrativeDirector -> RuleEngine` 链路。

### LLM fallback 观测字段

当启用真实 LLM backend 时，`ActionResponse` 会额外返回：

- `llm_fallback_used`：本轮是否使用真实 LLM 安全降级。
- `llm_error`：脱敏错误摘要，包含 `backend`、`error_type`、`error_message_sanitized`、`fallback_used` 和 `schema_validation_errors`。

这些字段不表示 action 被规则层拒绝。它们只说明 Agent 生成阶段发生了可观测错误，后端已使用无 `proposed_actions` 的安全回复继续走 Director / Rule Engine 边界。

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

`memory_candidate.created` 是重要事件派生出的候选记忆。payload 包含：

- `memory_id`
- `rule_id`
- `memory_type`：`episodic`、`belief`、`relationship`、`strategy`
- `memory_scope`：`case`、`session`、`npc_private`、`scene_shared`、`director_audit`
- `memory_layer`：`core`、`working`、`archival`
- `subject_id`
- `owner_character_id`
- `visible_to_character_ids`
- `content`
- `source_event_id`
- `source_event_ids`
- `source_memory_ids`
- `visibility`
- `salience`
- `confidence`
- `metadata`

Memory v1.4 后，payload 结构不变，但 `rule_id` 可能来自 app 默认 `MemoryDerivationRule`、案件包 `memory_derivation_rules.yaml`，或未迁移规则的 Python fallback。外部消费者只能依赖 payload 字段本身，不应假设某个 `rule_id` 必然来自代码或 YAML。

`agent_memory_snapshot.updated` 是运行时派生的稳定记忆快照更新。payload 包含上述结构化记忆字段，并额外包含 `operation` / `last_operation`。

- `operation=create`：创建新记忆。
- `operation=reinforce`：已有记忆被同类来源强化，不重写 canonical content。
- `operation=revise` / `supersede`：已有记忆被明确修订或替代。
- `operation=archive`：actor 是 `memory_archival_system`，表示 P2 归档策略把已有 working snapshot 降级为 `memory_layer=archival`。payload 还会包含 `archived_from_layer` 和 `archival_policy` 审计字段。

旧事件中的 `created` / `updated` / `archived` 会在模型层兼容解析，但新事件必须写 canonical v2 operation。

兼容旧事件时，缺失的 `memory_scope` 默认按 `npc_private` 处理，缺失的 `memory_layer` 默认按 `working` 处理。新事件必须显式写入这两个字段。普通 NPC 上下文不会注入 `director_audit` memory；`archival` memory 只能在常规 `core/working` 检索没有相关命中时通过冷召回进入 selected `memory_snapshots`。Director 审计入口可以检索 `director_audit` memory，但仍不产生状态写入权限。

`metadata` 不是开放命名空间。当前只允许：

- `relationship_delta`
- `strategy_id`
- `belief_subject`
- `belief_polarity`
- `emotion_delta`
- `clue_id`
- `world_info_id`
- `claim_id`
- `scene_id`
- `topic_tags`
- `privacy_reason`
- `decay_policy`

`character_impression.updated` 记录运行时派生的 NPC -> player 私有画像，不由 Agent 或 LLM 直接生成。当前画像兼容 `NPCPortraitState`，包含 `owner_character_id`、`subject_id`、`trust`、`suspicion`、`fear`、`traits`、`current_strategy` 和 `source_memory_ids`，同时保留解释性 `CharacterImpression` 字段。

`director.blocked` 记录 Director 拦截了某次 NPC 输出。payload 包含：

- `target_id`
- `blocked_fact_id`
- `reason`
- `world_info_id`
- `claimed_mode`
- `detected_directness`
- `matched_by`
- `matched_text`
- `pattern_id`
- `safe_fallback_used`
- `disclosure_claims`

其中 `matched_text` 是公开 API payload 中的脱敏值，不能回显 forbidden term、private 原文或被拦截的敏感事实原文。前端只能用这些字段做“回复被导演系统阻止”的 UI 和调试提示，不能把它们当作玩家已知事实。

## StateSummary

`StateSummary` 是公开状态视图。它可以包含已发现线索、完成的 beats、公开关系指标和玩家已知摘要。v0 不暴露记忆快照或私有角色画像，也不暴露 `solution_claims` 或指控真相配置。

`StateSummary.evidence_assets` 是面向前端证据栏的公开投影。每条记录来自已发现线索和对应玩家已知账本：

- `id`
- `title`
- `summary`
- `source`
- `clue_id`
- `world_info_id`
- `source_knowledge_id`
- `unlocked_at_event_id`

它不暴露未发现线索、未解锁 `WorldInfo`、forbidden facts、角色 private 原文或 solution claim。客户端不能把该字段回传当作权威证据状态；`present_clue` 和 `accuse` 仍必须由后端按 `session.discovered_clues` 与 `session.player_knowledge` 校验。

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

## Runtime Trace

运行时 trace schema v4 的 `memory_projection` 是对象，不是 memory content 列表。它包含本轮 AgentContext 使用的检索 skill 摘要：

- `skill_id`
- `included_memory_types`
- `included_scopes`
- `included_layers`
- `forbidden_scopes`
- `forbidden_layers`
- `selected_count`
- `items`

`items` 只允许包含 `memory_id`、`memory_type`、`memory_scope`、`memory_layer`、`owner_character_id` 和 `visible_to_character_ids`。禁止写入 memory `content`、forbidden fact 文本、private 原文或玩家原始文本。`selected_count` 必须等于 `items.length`，用于审计 skill-driven retrieval 是否按计划收窄投影。

真实 LLM fallback 会写入 trace：

- `llm_fallback_used`
- `llm_error_type`
- `llm_error_message_sanitized`
- `schema_validation_errors`

PostgreSQL runtime 下，action 产生的 trace 会随同本轮 `world_events` 在同一事务写入 `runtime_traces`。trace payload 会包含 `action_event_id`，用于关联触发它的玩家 action 事件。若事件追加因 stale sequence 或幂等冲突失败，本轮 trace 不会提前落库。

## 错误

- 未知 `case_id`：404
- 未知 `session_id`：404
- 未知 inspect target：404
- 未知 talk target：404
- 请求 schema 非法：422
- `ask_about`、`present_clue` 或 `accuse` 证据状态非法：200 + `accepted=false` + `rule.rejected`
