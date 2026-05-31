# Agent 设计

当前运行时默认仍使用 `MockAgent`。Agent 行为通过稳定接口路由，让确定性 mock、本地 stub 和可选真实 LLM 共享同一套输入/输出合同。

## 统一入口

所有 Agent 实现都使用同一协议：

```python
generate(context: AgentContext) -> AgentIntent
```

`AgentGateway` 是运行时唯一的 Agent 生成入口。默认后端是 `MockAgent`。`LLMAgentStub` 只是 schema 安全的本地占位，不调用外部服务。`OpenAILLMAgent` 是默认禁用的真实 LLM 适配器。

当前 Agent 支持的玩家动作链路：

```text
PlayerAction(talk | ask_about | present_clue)
  -> build_agent_context(case, session, action)
  -> AgentGateway.generate(context)
  -> AgentIntent
  -> NarrativeDirector.validate
  -> RuleEngine.apply_agent_intent
```

`ActionService` 不应直接调用 `MockAgent`。

`accuse` 在 v0 中故意不走 Agent。它是结构化 Rule Engine 动作；Agent 和 LLM 不判断指控是否正确。

后端选择由环境变量控制：

```text
默认 -> mock
LLM_BACKEND=llm_stub -> LLMAgentStub
LLM_BACKEND=real + OPENAI_API_KEY=... -> OpenAILLMAgent
```

如果 `LLM_BACKEND=real` 但没有 API key，网关创建时会回退到 `mock`，避免 CI 和默认本地场景意外进入真实 LLM 或安全拒答快照。

## AgentContext

`AgentContext` 是暴露给 Agent 的受控视图，包含：

- `case_id`
- `session_id`
- `target_agent_id`
- `current_phase`
- `completed_beats`
- `discovered_clues`
- `player_knowledge`
- `relationship_to_player`
- `relationship_thresholds_crossed`
- `recent_events`
- `memory_candidates`
- `memory_snapshots`
- `blocked_fact_ids`
- `revealable_fact_ids`
- `asked_subject_type`
- `asked_subject_id`
- `interaction_pressure`
- `subject_is_sensitive`
- `presented_clue_id`
- `presented_knowledge_id`
- `inner_context`

为了支持当前 mock，还包含案件编写的回复配置：

- `player_action`
- `target_profile`
- `default_speech`
- `default_intent`
- `reply_options`
- `fallback_relationship_delta`

`target_profile` 是公开的 `AgentCharacterView`，不包含原始 `private`、`secrets`、`goals` 或内部 `knowledge`。

`inner_context` 是当前目标 NPC 专属的 `CharacterInnerContext`。它来自该 NPC 自己的 private goals/secrets/knowledge 和 private portraits，不通过公开 API 返回，也不能包含其他 NPC 的私有数据。

`inner_context.fact_awareness` 是目标 NPC 自己的运行时事实认知账本投影。它只包含该 NPC 对 `WorldInfo` 的 stance、confidence、来源引用和证据引用，不包含其他 NPC 的事实认知。Agent 可以用它决定回答、回避、暗示或紧张程度，但不能通过输出直接修改它。

`inner_context.fact_disclosure_strategies` 是从 `fact_awareness` 派生出的可说边界。它把 `knows / suspects / conceals / misbelieves` 翻译成：

- 当前允许的 `allowed_modes`
- 当前禁止的 `forbidden_modes`
- 可用话术战术 `rhetoric_tactics`
- 禁止直接宣称的 `must_not_claim`
- 可围绕表达的 `safe_fact_refs`

这层的重点是支持“半真半假但不越权”的蒙太奇话术：LLM 可以负责语言表现，但不能自己决定是否 full reveal、是否直接承认或是否新增事实。

`AgentCharacterView` 只包含安全的公开角色卡字段：

- `id`
- `display_name`
- `public_role`
- `public_description`
- `speech_style`
- `default_tone`
- `catchphrases`
- `visible_traits`
- `defensive_style`
- `pressure_response`
- `trust_response`
- `fear_response`

`memory_candidates` 是运行时候选记忆；`memory_snapshots` 是从候选记忆归并出的稳定快照。当前版本只传递 `subject_id="player"` 的快照，不做向量检索、RAG 或 LLM 摘要。

案件包仍可定义 `forbidden_test_speech` 用于 mock-only Director 测试，但该字段不会复制进 `AgentContext`。

## Character Inner Context

角色 `private` 数据代表 NPC 自己的非公开视角。它不是对 NPC 自己隐藏。目标 NPC 应该知道自己的 goals、secrets、knowledge；运行时派生的 private impressions 也属于角色认知。系统限制的是“向外披露”和“权威状态写入”，不是 NPC 是否能访问自身视角。

`CharacterInnerContext` 会把原始 `CharacterPrivateConfig` 留在案件包内，只在 `AgentContext` 中暴露目标 NPC 专属的受控自我视图：

```text
CharacterInnerContext
  -> SelfKnowledgeItem
  -> DisclosurePolicy
```

`SelfKnowledgeItem` 包含目标 NPC 自己的 selected goals/secrets/knowledge 以及 `inner_portraits`。它不能包含其他 NPC 的 private 数据或其他 NPC 的 impressions。

`inner_portraits` 是目标 NPC 当前如何看待玩家的 `CharacterImpression`。v0 只支持 NPC -> player。画像不是角色真相，也不是公开资料；它是主观私有认知，可影响后续话术、警惕、合作、威胁判断和分支条件。

`DisclosurePolicy` 控制每个自我知识项是否能用于对外表达，以及表达粒度：

- 不披露
- 回避
- 暗示
- 部分披露
- 完整披露

有效披露策略会考虑剧情阶段、玩家已知证据、关系阈值、交互压力、禁说事实引用、是否允许逐字引用，以及目标 NPC 对玩家的私有画像。默认不应把 private 原文变成公开台词。

画像感知披露 v0 只在 `CharacterInnerContext` 内生效：

- 高威胁会把可用模式收窄到 `deny` / `deflect`
- 高结盟潜力可允许 `hint`
- `has_relevant_evidence` 可对匹配线索或 WorldInfo 允许 `partial`
- `dangerous_topic_triggered` 会收窄到 `deny` / `deflect`
- 画像永远不能授予 `full` 或直接引用 private 原文

即使有 `CharacterInnerContext`，对外发言仍受 Narrative Director 控制，`proposed_actions` 仍受 Rule Engine 控制。private knowledge 可以塑造意图，但不能直接写 `WorldEvent`。

`AgentContext.recent_events` 会过滤 `character_impression.updated`，避免一个 NPC 通过近期事件流看到另一个 NPC 的私有画像。当前目标 NPC 只能通过 `inner_context.inner_portraits` 看到自己的画像。

## 安全边界

`AgentContext` 不得包含：

- 原始 `CharacterPrivateConfig`
- 其他 NPC 的 `secrets`、`goals` 或内部 `knowledge`
- 其他 NPC 的 `character_fact_awareness`
- 其他 NPC 的 private impressions
- 线索 `truth_status`
- 带原文或 blocked terms 的 `forbidden_facts`
- 通过 memory snapshots 泄露的角色秘密、目标或内部知识
- `WorldEvent` payload 中的原始 private 角色卡数据

禁说事实可见性只能用 ID 表示：

- `blocked_fact_ids`
- `revealable_fact_ids`

禁说事实原文仍保留在案件包中，只供 `NarrativeDirector` 做输出校验。

## AgentIntent

Agent 输出必须始终是结构化结果：

```json
{
  "speech": "自然语言回复",
  "intent": "answer | conceal | lie | refuse | probe | panic",
  "emotional_shift": {},
  "proposed_actions": [],
  "memory_refs": []
}
```

`AgentIntent.proposed_actions` 不是真实状态变化，只是请求。它必须经过白名单和 Rule Engine 校验后才能改变状态。Agent intent 不能创建 `memory_candidate.created`、`agent_memory_snapshot.updated` 或 `character_impression.updated`；这些事件都由运行时派生。

同理，Agent intent 不能创建或修改 `character_fact_awareness.updated`。角色事实认知只由运行时根据案件初始配置和玩家交互事件派生。

Agent 也不能写 `FactDisclosureStrategy`。策略是上下文投影，不是状态；每次构造 `AgentContext` 时由后端重新计算。

允许的 proposed action 类型：

- `clue.discover`
- `relationship.change`
- `narrative.phase.change`

`narrative.phase.change` 保留在 schema 中用于审计，但 Rule Engine 会拒绝它。剧情阶段只能由 `narrative_rules.yaml` 通过 `RuleTriggerSystem` 推进。

## 实现说明

`MockAgent` 使用 `AgentContext`，根据案件包中的确定性规则选择回复。它可以根据阶段、已发现线索、询问对象、展示线索、交互压力、敏感主题、记忆快照、关系指标和目标 NPC 自己的 `inner_portraits` 改变回复。

配置在 `mock_dialogues.yaml` 的 reply 优先级最高。没有匹配 reply 时，MockAgent 使用安全角色卡 fallback：

- `defensive_style=evasive` 产生隐瞒风格回复
- `defensive_style=hostile` 产生拒绝风格回复
- `defensive_style=anxious` 产生慌张风格回复
- `pressure_response` 可强制拒绝或慌张隐瞒
- `speech_style` / `default_tone` 可影响措辞
- 高威胁 `inner_portraits` 会让回复更谨慎，但不引用画像原文
- `has_relevant_evidence` 加有效 `partial` 可产生部分真相式回复
- 高结盟潜力加有效 `hint` 可产生谨慎提示
- `dangerous_topic_triggered` 可强制拒绝或回避
- `FactDisclosureStrategy` 可让 fallback 使用 `answer_adjacent_truth`、`shift_focus` 等战术生成半真半假的安全表达

`mock_dialogues.yaml` 当前支持这些条件：

- `phase`
- `asked_subject_type`
- `asked_subject_id`
- `presented_clue`
- `min_interaction_pressure`
- `max_interaction_pressure`
- `requires_subject_sensitive`
- `requires_discovered`
- `missing_discovered`
- `requires_memory`
- `missing_memory`
- `min_relationship`
- `max_relationship`

`present_clue` 不表示线索证明 NPC 有罪，只表示玩家用已知线索施压、试探或质询 NPC。真相推进仍属于 Rule Trigger System 和 narrative rules。

`LLMAgentStub` 返回合法 `AgentIntent`，不调用外部模型，也不修改 `SessionState`。它用于在接入真实模型前锁定 LLM 合同。

`OpenAILLMAgent` 是最小真实后端适配器。它构造 `LLMAgentContractInput`，请求符合 `AgentIntent` 的严格 JSON，运行 `validate_llm_agent_output`，返回校验后的 intent。任何失败都会返回无 `proposed_actions` 的安全拒答。失败包括缺少 API key、HTTP 错误、JSON 错误、schema 错误、private 原文回显、直接提议剧情阶段变化。

`LLMAgentContractInput.disclosure_constraints` 会同时包含 private self-knowledge 约束和 `world_info` 级事实披露策略约束。`world_info` 约束会带 `allowed_modes`、`forbidden_modes`、`rhetoric_tactics`、`must_not_claim` 和 `safe_fact_refs`，用于告诉 LLM：你可以怎么说，但不能说到哪里。

真实适配器不改变状态权威模型。它的输出仍经过 Narrative Director，所有 `proposed_actions` 仍经过 Rule Engine。除非显式环境变量启用，否则它不参与完整场景快照。

完整 LLM 输入/输出合同见 `doc/llm-agent-contract.md`。
