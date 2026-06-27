# API 契约

当前 API 默认使用内存版后端叙事运行时，便于本地开发和测试。生产环境可以通过 `AGENT_RUNTIME=postgres` 切换到 PostgreSQL event stream 运行时，让 session 创建、action 事件、投影恢复走数据库权威链路。

## 接口列表

- `GET /health`
- `GET /cases`
- `GET /cases/{case_id}`
- `POST /sessions`
- `POST /sessions/{session_id}/actions`
- `POST /sessions/{session_id}/raw-actions`
- `GET /sessions/{session_id}/state`
- `GET /sessions/{session_id}/affordances`
- `GET /sessions/{session_id}/events`

## Raw Text Action Intake

自然语言玩家输入不能直接进入 `ActionService.handle(...)`。后端 raw text 入口必须走 `ActionService.handle_raw_text(...)` / `RuntimeContainer.handle_raw_text(...)`：

```text
raw_text
  -> ActionRouter.route
  -> entity resolution
  -> clarification / rejected
  -> PlayerAction candidate
  -> NarrativeDirector.precheck_player_action
  -> RuleEngine.precheck_player_action
  -> ActionService.handle(PlayerAction)
```

生产客户端提交 raw text 时同样应带 `Idempotency-Key` 请求头：

```http
POST /sessions/{session_id}/raw-actions
Idempotency-Key: raw-action-001
```

在 PostgreSQL runtime 下，后端会用原始 `raw_text` 计算 request hash。同一 session 内重复提交相同 `Idempotency-Key` 和相同 `raw_text`，会直接 replay 原响应事件，不再次运行 Agent/LLM，也不会产生第二批 `WorldEvent`。相同 `Idempotency-Key` 携带不同 `raw_text` 必须返回幂等冲突。

歧义目标、歧义线索、歧义场景返回 `needs_clarification` 和 `missing_slots`，不生成 `PlayerAction`，也不写 `WorldEvent`。无法识别或未知实体返回 `rejected`，不允许静默猜测。已经解析成结构化 `PlayerAction` 但不满足规则前置条件时，必须写入 `rule.rejected`，不会进入 Agent / LLM 链路。

## 创建 Session

使用默认案件：

```json
{}
```

指定案件：

```json
{ "case_id": "fake_case_002" }
```

响应包含 `session_id` 和公开 `PublicStateSummary`。公开响应不得返回内部 `StateSummary` 中的 `knowledge_id`、`world_info_id`、`source_knowledge_id` 或 `unlocked_at_event_id`。

## 公开 Case Detail

`GET /cases/{case_id}` 返回前端初始化 2D 场景所需的公开案件投影，不返回原始 `CasePackage`。

响应字段：

- `id`
- `title`
- `description`
- `initial_phase`
- `initial_scene_id`
- `scenes[]`
- `characters[]`
- `assets[]`

`scenes[].hotspots[]` 只暴露 `id`、`name`、`description`。`characters[]` 只暴露公开角色卡字段：`id`、`display_name`、`public_role`、`public_description`。当前案件包尚无独立前端资产 authoring 字段，因此 `assets` 先返回空数组；后续新增资产配置时也必须通过公开 DTO 白名单暴露。

该接口禁止暴露：

- `truth_status`
- `reveals_world_info`
- `world_info`
- `forbidden_facts`
- `solution_claims`
- character `private`
- mock dialogue / `reply_options`
- memory derivation rules
- NPC skill 内部配置
- narrative rule 内部触发条件

## Session Affordances

`GET /sessions/{session_id}/affordances` 返回当前 session 下前端可以展示的结构化交互项。它由后端案件配置、session 状态和规则同源约束推导，前端不能自行猜测动作是否合法。

响应字段：

- `available_hotspot_ids`：当前可提交 `inspect` 的 hotspot id。v0 中所有已知 hotspot 都可重复 inspect；重复 inspect 不保证产生新线索。
- `available_character_ids`：当前可提交 `talk` 的角色 id。
- `discovered_clue_ids`：玩家已发现线索 id。
- `evidence_asset_ids`：已发现且已进入玩家知识账本、可用于 `present_clue` / evidence UI 的线索 id。
- `valid_presentation_modes`：当前存在合法 `present_clue` 时可用的展示模式。
- `inspect[]`、`talk[]`、`ask_about[]`、`present_clue[]`、`accuse[]`：可直接用于组装结构化 action 的公开项。
- `can_accuse`：是否存在至少一个当前规则可接受的正式指控目标。

`ask_about` 的 clue subject 只会在该 clue 已发现或已进入玩家知识账本后出现；character 和 scene subject 来自公开案件配置。`present_clue` 只会列出已发现且有玩家知识账本的 clue；`scene_shared` 模式只会在目标 NPC 当前位于该 scene 时出现。NPC 移动后，`talk[].scene_ids` 与 `present_clue[].scene_ids` 必须来自 replay 后的 `SessionState.npc_locations`，不能继续使用案件 YAML 的静态 `SceneConfig.characters`。

`accuse[]` 不公开 `claim_id`、claim `result`、`required_evidence` 或 `required_world_info`。它只说明当前是否存在规则可接受的指控目标，以及玩家当前可用的公开证据 id。正式指控仍由后端 Rule Engine 根据 `solution_claims.yaml` 校验；前端不得把 affordance 当作真相来源。

## PlayerAction

所有玩家动作目标统一使用 `target_id`。如果请求使用旧字段 `target`，会被 422 拒绝。

### Meeting Actions V1

公开会议复用 `POST /sessions/{session_id}/actions`，但 action type 必须是结构化会议动作，不能把自由文本群聊直接写入状态。

支持的会议 action：

- `meeting_start`：`target_id="meeting"`，可选 `text` 作为会议议题。
- `meeting_speak`：`target_id="meeting"`，必填非空 `text`。
- `meeting_present_evidence`：`target_id="meeting"`，必填 `clue_id`，该 clue 必须已发现且进入玩家知识账本。
- `meeting_ask`：`target_id=<npc_id>`，可选 `text`，可选成对的 `subject_type` / `subject_id`。
- `meeting_open_vote`：`target_id=<suspect_npc_id>`，开启针对目标的会议投票。
- `meeting_cast_vote`：`target_id=<open_vote_target_id>`，必填 `vote`，取值 `accuse`、`defend`、`abstain`。
- `meeting_propose_verdict`：`target_id=<suspect_npc_id>`，`evidence_clue_ids[]` 是玩家提交给规则系统校验的证据集合，`claim_id` 可省略，由后端按目标角色选择默认 solution claim。

会议 action 成功或失败都必须落 `WorldEvent`。会议消息只通过 `meeting.message.posted` 公开；投票只通过 `meeting.vote.cast` 公开；会议裁决必须先写 `meeting.verdict.proposed`，再由 Rule Engine 校验。只有 `meeting.verdict.accepted` 之后，才允许写正式 `player.accused` / `accusation.evaluated`。

`PublicStateSummary.meeting` 是会议状态投影，字段包括：

- `active`
- `meeting_id`
- `topic`
- `participant_ids`
- `turn`
- `vote_open`
- `vote_target_id`
- `votes[]`：`voter_id`、`target_id`、`choice`、`reason`
- `verdict_target_id`
- `verdict_status`
- `verdict_result`
- `verdict_reason`：最近一次裁决拒绝的安全原因；非拒绝态为空。
- `missing_required_evidence[]`：最近一次裁决拒绝中仍缺失的公开 clue id。
- `missing_required_world_info[]`：最近一次裁决拒绝中仍缺失的安全 world info 锚点 id，仅用于 UI 反馈，不等同于公开完整 `WorldInfo` 内容。

公开事件流对白名单暴露 `meeting.*` payload：speaker、message kind、text、clue id、target id、vote choice、verdict result 和裁决拒绝反馈。`meeting.verdict.rejected` 只允许公开 `meeting_id`、`target_id`、`reason`、`missing_required_evidence[]`、`missing_required_world_info[]`。不得公开 `claim_id`、solution claim 的完整内部条件、未解锁 `WorldInfo` 正文、NPC 私有记忆或 Director 审计内容。

生产客户端提交 action 时应带 `Idempotency-Key` 请求头：

```http
POST /sessions/{session_id}/actions
Idempotency-Key: action-001
```

### Meeting Frontend Contract 2026-06-27

会议前端必须从 `GET /sessions/{session_id}/events` 的 public event stream 渲染会议记录，而不是维护本地伪聊天事实。当前允许展示的会议事件包括：

- `meeting.message.posted`
- `meeting.vote.opened`
- `meeting.vote.cast`
- `meeting.verdict.proposed`
- `meeting.verdict.accepted`
- `meeting.verdict.rejected`

`meeting.message.posted.message_kind` 当前公开取值包括 `system`、`speech`、`question`、`npc_reply`、`evidence`、`narration`。其中 `narration` 必须由后端 Director/规则投影产生，客户端不得提交该 message kind。

`PublicStateSummary.meeting` 已提供裁决反馈字段：

- `verdict_reason`
- `missing_required_evidence[]`
- `missing_required_world_info[]`

前端提交最终裁决必须使用 `meeting_propose_verdict`，并传入用户多选的 `evidence_clue_ids[]`。不得再用旧 `accuse` action 模拟会议裁决；正式 `player.accused` 只能由后端在 `meeting.verdict.accepted` 后写入。

旁白推进通过普通 public event stream 返回：

```json
{
  "type": "meeting.message.posted",
  "actor_id": "director",
  "payload": {
    "speaker_id": "director",
    "message_kind": "narration",
    "text": "..."
  }
}
```

公开 payload 不暴露 `narrates_event_id`、`claim_id`、内部 solution 条件或未公开 world info。

在 PostgreSQL runtime 下，后端会用结构化 `PlayerAction` 计算 request hash。同一 session 内重复提交相同 `Idempotency-Key` 和相同 action，会直接 replay 原响应事件，不再次运行 Agent/LLM，也不会产生第二批 `WorldEvent`。

冲突语义：

- 相同 `Idempotency-Key` 携带不同 action：返回 `409 Conflict`。
- 相同 session 的事件流在本轮 action 生成后被其他请求推进：返回 `409 Conflict`。
- 幂等键已占用但尚未提交响应事件：返回 `409 Conflict`。

### 公开 Action Response

`POST /sessions/{session_id}/actions` 对外返回 `PublicActionResponse`，不得直接返回运行时内部 `ActionResponse`。内部 `ActionResponse.new_events` 是 `WorldEvent[]`，只允许在后端、审计、回放和测试内部使用；公开响应必须先经过 `build_public_action_response(...)` 投影。

响应字段：

- `session_id`
- `accepted`
- `speech`
- `director_blocked`
- `director_reason`
- `llm_fallback_used`
- `llm_error`
- `new_events[]`
- `state`

`new_events[]` 是 `PublicEventStreamItem[]`，与 `GET /sessions/{session_id}/events` 使用同一 payload 白名单。不可公开事件会被隐藏，但其内部事件序号仍会推进 `sequence` 和 `state.event_count`；客户端继续拉取公开事件流时应以 `state.event_count` 作为本轮 action 后的 count cursor。

`state` 是 `PublicStateSummary`，不是内部 `StateSummary`。它只保留前端可展示状态：案件标题、阶段、已完成 beat、公开角色卡、已发现线索、玩家已知摘要、证据栏、NPC 当前场景级位置、公开关系指标和 `event_count`。

`npc_locations[]` 是多 Agent 编排 V1 的公开位置投影，只包含：

- `npc_id`
- `scene_id`

它来自 replay 后的 `SessionState.npc_locations`。前端可以据此决定某场景显示哪些 NPC，并自行派生站位、朝向和移动动画；后端不在公开 API 中暴露 NPC 私有计划、移动 rationale、memory content 或连续坐标。

公开 action response 禁止出现：

- 原始 `WorldEvent.payload` 内部字段
- `world_info_id`
- `knowledge_id`
- `source_knowledge_id`
- `unlocked_at_event_id`
- `memory_id`
- `rule_id`
- `blocked_fact_id`
- `matched_text`
- `proposed_actions`
- `disclosure_claims`

### Town / NPC 事件公开投影

多 Agent 编排 V1 新增的内部事件仍走同一公开事件白名单：

- `town.tick.advanced`：公开 `current.tick`。
- `npc.location.changed`：公开 `current.npc_id`、`current.scene_id`、`current.updated_at_tick`。
- `npc.observed`：公开观察 envelope 的 ID 字段，包括 `observer_id`、`observed_event_id`、`scene_id`、`visibility`、`perception_quality`、`redacted_payload_ref`。
- `npc.hearsay.received`、`npc.autonomy_intent.proposed`、`npc.autonomy_intent.rejected`：只公开稳定 ID / reason / scene 字段，不公开传闻正文、私有记忆正文、safe fragment summary 或 forbidden fact 文本。

`npc.observed` 的 `redacted_payload_ref` 只是内部事件引用，不是可解引用的公开 payload。客户端不得把它当作获取源事件私有内容的入口。

`POST /sessions/{session_id}/raw-actions` 的 `response` 字段也必须是 `PublicActionResponse`。`needs_clarification` 和无法识别的 `rejected` 不生成 `response`；已解析为结构化 action 但被规则或 Director 前置拒绝时，`response.new_events[]` 只能包含公开投影后的 `rule.rejected` 或等价安全事件。

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

合法 `present_clue` 之后才进入 agent-backed 链路：构造 `AgentContext` / `LLMAgentContractInput`，经 `AgentGateway` 生成 `AgentIntent`，再由输出合同和 `NarrativeDirector` 审计。只有审计通过并写入 `npc.replied` 后，Rule Engine 才会解释白名单 `proposed_actions`。Director 拦截时只写 `director.blocked`，不会应用任何 proposed action。

agent-backed 链路中的 `LLMAgentContractInput.disclosure_constraints` 只会包含 Director 当前放行的 `safe_fragments`。客户端不能通过 API 请求让 LLM 获得 blocked fragment、solution claim 或全局真相原文。LLM 输出的 `disclosure_claims[].claim_refs` / `source_refs` 必须匹配这些 safe refs；否则本轮会被合同校验或 Director 审计降级为安全回复。

### LLM fallback 观测字段

当启用真实 LLM backend 时，`PublicActionResponse` 会额外返回：

- `llm_fallback_used`：本轮是否使用真实 LLM 安全降级。
- `llm_error`：脱敏错误摘要，包含 `backend`、`error_type`、`error_message_sanitized`、`fallback_used` 和 `schema_validation_errors`。

这些字段不表示 action 被规则层拒绝。它们只说明 Agent 生成阶段发生了可观测错误，后端已使用无 `proposed_actions` 的安全回复继续走 Director / Rule Engine 边界。

如果 Director 因事实网关拦截回复，`PublicActionResponse.director_blocked=true`，`director_reason` 会说明拒绝类别，例如未授权 safe fragment、locked forbidden inference 或 speech/claim 不一致。对应的内部 `director.blocked` 事件会记录 `world_info_id`、`blocked_fact_id`、`claimed_mode`、`matched_by`、`pattern_id` 和 `safe_fallback_used` 等审计字段；公开 action response 和公开事件流只允许暴露 `target_id`、`reason`、`safe_fallback_used`，不得把这些审计锚点或被拦截事实原文回显给客户端。

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

P0 硬链路的权威顺序是：Action Intake 产出结构化 `PlayerAction`；可选 Director precheck 只给 Router / Intake 层提供越界摘要；正式玩家动作由 Rule Engine 接受或拒绝并写事件；LLM 输出必须先过合同校验和 Director 审计；状态变化最终只能来自 `WorldEvent` 与 replay。集中说明见 `doc/architecture/p0-hard-chain-2026-06-16.md`。

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

## 公开事件增量流

`GET /sessions/{session_id}/events?after_count=N` 返回公开事件增量 DTO，不再把内部 `WorldEvent[]` 作为前端唯一契约。`after_count` 是 session 内部事件流的稳定 count cursor，初始传 `0`。响应：

```json
{
  "session_id": "session-id",
  "case_id": "fake_case_001",
  "after_count": 0,
  "next_after_count": 3,
  "has_more": false,
  "events": [
    {
      "sequence": 1,
      "id": "event-id",
      "type": "session.created",
      "actor_id": "system",
      "created_at": "2026-06-26T00:00:00+00:00",
      "payload": {
        "case_id": "fake_case_001",
        "initial_phase": "opening"
      }
    }
  ]
}
```

可选 `limit` 默认为 `100`，最大 `500`。`sequence` 是 1-based 内部事件序号。`next_after_count` 会跨过被公开投影隐藏的内部事件，因此客户端下一次必须传 `next_after_count`，不能用 `events.length` 自行计算。

公开事件 payload 使用白名单：

- `npc.replied` 只暴露 `speech`，不暴露 `intent`、`proposed_actions` 或 `disclosure_claims`。
- `player_knowledge.updated` 不暴露 `world_info_id` 或 `knowledge_id`。
- `rule.rejected` 只暴露 `action_type`、`reason` 和安全 action 字段。
- `director.blocked` 不暴露 `blocked_fact_id`、`world_info_id`、`matched_text` 或 disclosure claims。
- memory、character impression、character fact awareness、NPC skill selection/rejection 等内部事件会推进 count cursor，但不会出现在公开 `events[]`。

公开事件流不得暴露 `truth_status`、`reveals_world_info`、forbidden fact 原文、blocked terms、solution claim 内部配置、private memory 或 mock `reply_options`。

## 内部事件

重要事件类型包括：

- `session.created`
- `town.tick.advanced`
- `player.inspected`
- `player.talked`
- `player.asked_about`
- `player.presented_clue`
- `player.accused`
- `accusation.evaluated`
- `npc.replied`
- `npc.location.changed`
- `npc.observed`
- `npc.hearsay.received`
- `npc.autonomy_intent.proposed`
- `npc.autonomy_intent.rejected`
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

`town.tick.advanced` 是内部调度事件。payload 至少包含：

- `previous.tick`
- `current.tick`
- `from_tick`
- `to_tick`
- `policy`
- `llm_called=false`

`npc.location.changed` 是 NPC 位置变化事件。payload 至少包含：

- `actor_id` / `npc_id`
- `from_scene_id`
- `to_scene_id`
- `current.scene_id`
- `current.updated_at_tick`
- `rationale`

`npc.observed` 是感知 envelope，不是公开叙事文本。payload 至少包含：

- `observer_id`
- `observed_event_id`
- `scene_id`
- `visibility`
- `perception_quality`
- `redacted_payload_ref`

`npc.observed` 不得复制 `observed_event_id` 指向事件的原始 payload。后端可用它派生 NPC 私有 `memory_candidate.created`，但公开事件流不应把 `redacted_payload_ref` 反解给客户端。

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

## PublicStateSummary

`PublicStateSummary` 是公开状态视图。`GET /sessions/{session_id}/state`、`POST /sessions` 的 `state`、`PublicActionResponse.state` 都必须使用该 DTO，不得直接返回运行时内部 `StateSummary`。它可以包含已发现线索、完成的 beats、公开关系指标和玩家已知摘要。v0 不暴露记忆快照或私有角色画像，也不暴露 `solution_claims`、指控真相配置或 `WorldInfo` 锚点。

`PublicStateSummary.player_knowledge[]` 只暴露玩家已经获得、可展示的摘要字段：

- `clue_id`
- `confidence`
- `acquisition`
- `source_type`
- `title`
- `summary`

内部 `StateSummary.player_knowledge[]` 的 `knowledge_id` 和 `world_info_id` 只用于规则校验、回放和审计，不得进入公开响应。`knowledge_id` 经常派生自 `WorldInfo`，会反向泄露案件真相锚点；`world_info_id` 直接暴露真相节点，风险更高。

`PublicStateSummary.evidence_assets[]` 是面向前端证据栏的公开投影。每条记录来自已发现线索和对应玩家已知账本：

- `id`
- `title`
- `summary`
- `source`
- `clue_id`

内部 `EvidenceSummary` 的 `world_info_id`、`source_knowledge_id` 和 `unlocked_at_event_id` 只能留在后端内部。它们分别会泄露真相节点、玩家知识账本主键和事件日志锚点；前端证据栏只需要公开 clue id、标题、摘要和来源类型。

`PublicStateSummary` 不暴露未发现线索、未解锁 `WorldInfo`、forbidden facts、角色 private 原文或 solution claim。客户端不能把该字段回传当作权威证据状态；`present_clue` 和 `accuse` 仍必须由后端按 `session.discovered_clues` 与 `session.player_knowledge` 校验。

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

运行时 trace schema v5 的 `memory_projection` 是对象，不是 memory content 列表。它包含本轮 AgentContext 使用的检索 skill 摘要：

- `skill_id`
- `included_memory_types`
- `included_scopes`
- `included_layers`
- `forbidden_scopes`
- `forbidden_layers`
- `selected_count`
- `items`

`items` 只允许包含 `memory_id`、`memory_type`、`memory_scope`、`memory_layer`、`owner_character_id` 和 `visible_to_character_ids`。禁止写入 memory `content`、forbidden fact 文本、private 原文或玩家原始文本。`selected_count` 必须等于 `items.length`，用于审计 skill-driven retrieval 是否按计划收窄投影。

schema v5 增加 `npc_skill_projection`，用于审计本轮 NPC skill 渐进披露选择。它只允许记录：

- `selected_skill_ids`
- `skill_safe_fragment_refs`
- `items[].skill_id`
- `items[].type`
- `items[].level`
- `items[].signature`
- `items[].allowed_intents`
- `items[].allowed_tactics`
- `items[].max_disclosure_mode_by_world_info`
- `items[].safe_fragment_refs`
- `items[].memory_plan_id`
- `items[].allowed_proposed_actions`

`npc_skill_projection` 禁止记录 skill 说明正文、safe fragment summary、角色 private 原文、memory content、forbidden fact 文本或玩家原始文本。它只能解释“本轮哪些能力边界被选中”，不能成为新的事实内容通道。

真实 LLM fallback 会写入 trace：

- `llm_fallback_used`
- `llm_error_type`
- `llm_error_message_sanitized`
- `schema_validation_errors`

PostgreSQL runtime 下，action 产生的 trace 会随同本轮 `world_events` 在同一事务写入 `runtime_traces`。trace payload 会包含 `action_event_id`，用于关联触发它的玩家 action 事件。若事件追加因 stale sequence 或幂等冲突失败，本轮 trace 不会提前落库。

## 错误

所有非 2xx API 错误必须返回稳定 JSON DTO，不能再返回裸字符串 `detail` 或直接回显异常文本。

```json
{
  "code": "ACTION_NOT_ALLOWED",
  "message": "Action is not allowed in the current world state.",
  "details": {
    "reason": "Unknown inspect target_id: vault"
  },
  "retryable": false,
  "correlation_id": "8f4b3d1c-6e4f-4a9b-9f7c-2aee2c6d3b20"
}
```

字段语义：

- `code`：稳定机器码，前端只能依赖该字段分流错误 UI 和重试策略。
- `message`：安全的人类可读摘要，不承载业务分支。
- `details`：安全结构化细节；禁止包含 SQL、堆栈、provider payload、角色 private、未公开线索、forbidden fact 原文或玩家原始输入回显。
- `retryable`：客户端是否可以在满足提示条件后重试。`true` 不表示立即盲重试，仍需遵守 `details.retry_after` 等策略。
- `correlation_id`：每个错误必须有。若请求头带 `X-Correlation-ID`，后端应沿用并在响应头同名返回；否则后端生成。

稳定错误码：

| HTTP | code | retryable | 语义 | 状态副作用 |
| --- | --- | --- | --- | --- |
| 404 | `CASE_NOT_FOUND` | false | `case_id` 不存在 | 不创建 session，不写事件 |
| 404 | `SESSION_NOT_FOUND` | false | `session_id` 不存在 | 不写事件 |
| 400 | `ACTION_NOT_ALLOWED` | false | 结构化 action 通过 schema，但目标、当前阶段或世界状态不允许执行；`ActionValidationError` 必须映射到这里，不能映射成 404 | 不写玩家 action 事件，不进入 Agent / LLM |
| 409 | `IDEMPOTENCY_CONFLICT` | false | 同一 session 内 `Idempotency-Key` 被不同请求复用 | 不重跑 Agent / LLM，不写本轮事件 |
| 409 | `IDEMPOTENCY_IN_PROGRESS` | true | 幂等键已占用但尚未提交响应事件 | 不重跑 Agent / LLM，不写本轮事件；客户端应稍后查询或重试 |
| 409 | `STALE_SESSION_SEQUENCE` | true | action 生成后提交前，session event stream 已被其他请求推进 | 本轮事件和 trace 不落库；客户端应刷新 state/events 后重试 |
| 422 | `REQUEST_VALIDATION_ERROR` | false | 请求 JSON 或字段类型不满足 API DTO | 不进入 runtime，不写事件 |
| 500 | `PERSISTENCE_ERROR` | true | PostgreSQL event store / session store / trace 持久化边界失败 | 以事务结果为准；不得提前暴露半提交状态 |
| 500 | `INTERNAL_ERROR` | false | 未分类 API 层异常 | 不保证可恢复；必须通过 `correlation_id` 查服务端日志 |

`ask_about`、`present_clue` 或 `accuse` 已进入 Rule Engine 后，如果只是证据状态、阶段条件或推理闭环不满足，仍返回 `200` + `accepted=false` + `rule.rejected`。这是游戏规则拒绝，不是 HTTP 错误；它必须生成可回放的 `rule.rejected` 事件。相反，`CASE_NOT_FOUND`、`SESSION_NOT_FOUND`、`ACTION_NOT_ALLOWED`、幂等冲突、stale sequence 和 422 都不能写入新的 `WorldEvent`。
