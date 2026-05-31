# 后端运行时骨架

当前运行时仍刻意保持很小：默认不调用真实 LLM、不做前端、不接数据库、不做向量记忆。它的目的，是证明后端叙事状态、规则执行、事件日志和 replay 的合同成立。

## 已实现范围

- 扫描 `cases/*`，加载所有包含 `case.yaml` 的案件包。
- 支持 `cases/fake_case_001` 和 `cases/fake_case_002`。
- 用 Pydantic v2 校验 YAML schema 和跨文件引用。
- 加载公开/私有角色卡，暴露公开角色视图，并为 Agent 支持的 NPC 行为构造目标专属 `CharacterInnerContext`。
- 从运行时事件派生 NPC -> player 私有 `CharacterImpression`。
- 创建内存 session。
- 处理 `inspect`、`talk`、`ask_about`、`present_clue`、`accuse` 玩家动作。
- 通过 Rule Engine 解锁线索。
- 通过 `AgentGateway` 和 `MockAgent` 生成确定性 NPC 意图。
- 提供 `LLMAgentStub` 作为不联网的未来 LLM 合同占位。
- 提供默认禁用、环境变量控制的 `OpenAILLMAgent`。
- 通过 Narrative Director 阻止禁说 NPC 输出。
- 应用合法关系变化，并限制关系指标范围。
- 每个阈值每个 session 只发出一次 `relationship.threshold.crossed`。
- 派生 `player_knowledge.updated` 和 `memory_candidate.created`。
- 把 `memory_candidate.created` 归并为 `agent_memory_snapshot.updated` 和 `session.memory_snapshots`。
- 使用 `solution_claims.yaml` 通过 Rule Engine 评估结构化正式指控。
- 当 `RuleTriggerSystem` 观察到 `accusation.evaluated(result=correct)` 时，`fake_case_001` 可通过 `case_solved` beat 进入 resolved。
- 通过 `RuleTriggerSystem` 完成 beats 并推进 phases。
- 使用 `replay_events(case, events)` 回放事件日志。
- 返回公开 `StateSummary`。

## 运行链路

```text
Case Package
  -> Create Session
  -> PlayerAction
  -> Load SessionState / WorldState
  -> Build AgentContext
  -> AgentGateway.generate(context)
  -> AgentIntent
  -> Narrative Director 校验叙事边界
  -> Rule Engine 应用合法状态变化
  -> Derived Event System 派生玩家已知和记忆候选
  -> Memory Snapshot System 更新稳定运行时记忆快照
  -> Rule Trigger System 评估叙事规则
  -> Write WorldEvent
  -> Return StateSummary
```

`inspect` 跳过 Agent 生成。`talk` 使用 `AgentGateway.generate(context)`。`ask_about` 先校验 clue、character 或 scene subject，写入 `player.asked_about`，再走同一 AgentGateway 路径。`present_clue` 先通过 Rule Engine 证据校验，写入 `player.presented_clue`，再走与 `talk` 相同的 AgentGateway 路径。

`accuse` 不使用 AgentGateway。Rule Engine 校验结构化 claim 和玩家已知证据，写入 `player.accused` 与 `accusation.evaluated`，然后继续运行派生记忆和触发系统。v0 中 accuse 不直接推进 phase 或运行 ending system。

叙事结案 v0 故意保持简单：resolved phase 只能由 `narrative_rules.yaml` 中响应 `accusation.evaluated` 的 beat 达成，而不是 accuse 代码直接设置。

## 公开 API

- `GET /health`
- `GET /cases`
- `POST /sessions`
- `POST /sessions/{session_id}/actions`
- `GET /sessions/{session_id}/state`
- `GET /sessions/{session_id}/events`

`PlayerAction` 目标字段固定为 `target_id`。关系两端固定为 `source_id` 和 `target_id`。

未知 inspect target 和未知 talk NPC 会返回业务错误，并且不写玩家动作事件。非法 `ask_about`、`present_clue`、`accuse` 会写 `rule.rejected` 并返回 `accepted=false`。

## Agent 边界

`ActionService` 依赖 `AgentGateway`，不直接依赖 `MockAgent`。

`AgentGateway` 当前支持：

- `mock`：默认确定性后端。
- `llm_stub`：本地 stub，返回合法 `AgentIntent`，不调用模型。
- `real`：仅在 `LLM_BACKEND=real` 且存在 `OPENAI_API_KEY` 时选择 OpenAI 适配器。

`llm_stub` 会构造 `LLMAgentContractInput` 并校验严格 JSON 形态的 `AgentIntent` 输出，不调用外部模型。

`real` 也会构造 `LLMAgentContractInput`，请求严格 JSON，校验模型输出，任何失败都返回安全拒答。它不改变默认后端、场景快照、replay 路径或 Rule Engine 权威。

`AgentContext` 是当前 Agent 唯一输入形态。它不得包含原始 `CasePackage`、原始 `SessionState`、其他 NPC 的 private 数据、线索真相状态或禁说事实原文。

`AgentContext.target_profile` 是从角色卡公开侧派生的安全 `AgentCharacterView`。MockAgent 只在没有匹配 `mock_dialogues.yaml` reply 时用它做 fallback 行为输入。

角色 `private` 是 NPC 自己的非公开知识。v0 会通过 `AgentContext` 给目标 NPC 暴露目标专属 `CharacterInnerContext`。公开台词仍由 Narrative Director 检查，状态变化仍由 Rule Engine 检查。`inner_context` 不得出现在状态摘要、事件 payload、玩家旅程 Markdown 或其他 NPC 上下文中。

`CharacterInnerContext.inner_portraits` 只包含当前目标 NPC 自己的 private impressions。v0 只支持 NPC -> player。画像状态存储在 `session.character_impressions[npc_id]["player"]`，并通过 `character_impression.updated` 写入，不通过 `AgentIntent` 写入。

`AgentContext.recent_events` 排除 `character_impression.updated`，避免其他 NPC 把画像事件当作近期上下文看到。

画像感知披露 v0 会调整目标 NPC inner context 中的有效 `DisclosurePolicy`。高威胁和危险话题会收窄披露；结盟可能允许 hint；相关证据可能允许 partial。这只是输入塑形，不改变 Rule Engine 权威。

`AgentContext.memory_snapshots` 只包含运行时生成的安全 player-scoped 结构化快照。它不是向量记忆、RAG、数据库或真实 LLM 接入点。

`accuse` 在 v0 中位于 Agent 边界外。Agent 不判断指控正确性，也不能写 `player.accused` 或 `accusation.evaluated`。

## Replay 要求

运行时场景 smoke tests 为 `fake_case_001` 和 `fake_case_002` 记录稳定事件快照，并验证 replay 能重建等价关键状态。这保护规则链、派生状态、Director 阻止、Rule Engine 拒绝、指控评估、叙事结案和阶段推进不会意外漂移。

同一场景还会从实际 `WorldEvent` 列表渲染玩家旅程 Markdown。Markdown 用于人工审阅，并必须遵守与公开摘要相同的防泄漏边界。

Replay 会从持久化事件重建 `memory_candidates` 和 `memory_snapshots`，不会重新运行记忆派生或快照聚合，因此保持事件数量并避免递归记忆事件。

Replay 也会从持久化 `character_impression.updated` 事件重建 `character_impressions`，不会重新运行画像派生。
