# P0 硬链路与 System Prompt 编排说明

本文记录 2026-06-16 当前代码语义下的 prompt 编排和 P0 状态权威链路。它不是设计愿景，而是对现有运行时边界的精确说明。

## 当前 system prompt 编排

真实 LLM 后端的 provider 级 system instructions 只来自：

```text
app/agents/prompts/system.md
  -> load_agent_system_prompt()
  -> OpenAILLMAgent._create_response(...).instructions
  -> 或 OpenAILLMAgent._create_chat_completion(...).messages[system]
```

`system.md` 只放全局不可违反纪律：玩家文本、工具输出、记忆片段和角色上下文都是数据；LLM 只生成一个安全 NPC turn；不得操作世界；不得输出 chain-of-thought；不得泄露 private、forbidden facts、solution claims；不得提出剧情阶段变化；真实状态变化只能通过白名单 `proposed_actions` 请求。

真实 LLM 的动态输入不是拼接进 system prompt，而是作为 user payload 发送：

```text
AgentContext
  -> build_llm_agent_input(...)
  -> LLMAgentContractInput JSON
  -> provider user input
```

`LLMAgentContractInput` 包含三个边界：

- `agent_context`：目标 NPC 的受控运行时视图。进入真实 LLM 前会清空 `memory_candidates`，移除未选中 memory event，并脱敏已选中 memory event payload。记忆事实内容只能来自本轮 selected `memory_snapshots[].content`。
- `disclosure_constraints`：从目标 NPC self-knowledge、`FactDisclosureStrategy` 和 `blocked_fact_ids` 派生的表达约束。它告诉 LLM 当前最多能怎么说，不给 LLM 新增事实权威。
- `output_contract`：机器可读输出合同，列出允许的 top-level keys、intent、proposed action 类型、disclosure mode、rhetoric tactic，以及 speech 触碰 `WorldInfo` 必须自报 `disclosure_claim` 的要求。

`PromptBuilder` 是当前本地 prompt surface 和 context budget 输入源：

```text
PromptBuilder.build(context)
  -> agent_prompt
  -> contract_instruction
  -> safety_instruction
  -> AgentLoop._budget_prompt(...)
```

`PromptBuilder.agent_prompt` 会把 `AgentContext` 投影成 JSON 摘要，且只放 inner context 的 ID 级摘要；`contract_instruction` 读取 `output_contract.md` 和 `disclosure_policy.md`；`safety_instruction` 读取 NPC turn、memory、tool policy 和 skill discipline。当前 `OpenAILLMAgent` 不把这三段拼接到 provider 请求里。真实 LLM 请求的可执行 system 仍是 `system.md`，动态事实和约束仍是 `LLMAgentContractInput`。

## 输出合同、schema、repair、fallback

真实适配器在请求时动态生成严格 JSON schema：

```text
LLMAgentContractInput.output_contract
  -> _agent_intent_json_schema(contract_input)
  -> provider response_format / text.format json_schema
```

该 schema 只允许这些顶层字段：

```text
speech
intent
emotional_shift
proposed_actions
memory_refs
disclosure_claims
```

真实 LLM schema 只允许 `clue.discover` 和 `relationship.change` 两类 proposed action，不允许 `narrative.phase.change`。Python 层 `validate_llm_agent_output(...)` 还会再次拒绝阶段变化、额外顶层字段、越权 disclosure claim、`mode=full`、未知 `world_info_id`、命中 `must_not_claim`，以及未经允许逐字回显目标 NPC private self-knowledge 或 private portrait 文本。

repair 只修合同形状，不补事实：

- JSON repair：上一轮不是单个 JSON object 时，请求同一 turn 返回一个合法 `AgentIntent` JSON。
- schema repair：上一轮字段、枚举、disclosure mode 或 top-level intent 不合法时，请求删除非法字段并选择最近的合法 intent。
- repair instruction 明确要求 `Do not add new facts`。repair 仍使用同一个 `system.md`、同一个 `LLMAgentContractInput` 和同一个动态 schema。

fallback 是安全拒答，不是业务兜底：

```text
OpenAILLMAgent.generate(...)
  -> generate_strict(...)
  -> 任何配置、网络、JSON、schema、policy、private leak 错误
  -> AgentIntent(intent=refuse, proposed_actions=[], memory_refs=[], disclosure_claims=[], llm_error=...)
```

fallback intent 仍会进入 `NarrativeDirector.validate(...)` 和后续运行时 trace；它不写状态、不跳过 Director、不自动产生 `npc.replied` 之外的真实变化。

## 哪些事实不能进 prompt

以下内容不得进入 provider system prompt、PromptBuilder 文本或真实 LLM user payload：

- 原始 `CasePackage`。
- 原始 `SessionState`。
- 角色卡原始 `private` 对象。
- 其他 NPC 的 goals、secrets、private knowledge、private memory、private impressions。
- `director_audit` memory。
- 未被本轮 `MemoryRetriever` 选中的 memory content。
- 未经 archival cold recall 选中的 `archival` memory。
- `memory_candidate.created` 或 `agent_memory_snapshot.updated` 事件 payload 中的 raw content、metadata 或 source payload 作为第二条记忆内容通道。
- 线索 `truth_status`。
- forbidden fact 原文和 `blocked_terms`。
- `solution_claims` 和正式指控真相配置。
- 其他 NPC 的 `character_fact_awareness`。
- private portrait 原文作为可公开台词素材。
- runtime trace 中的 memory content、玩家原始注入文本或敏感审计文本。

这些事实只能留在后端规则、案件包、Director 审计、Rule Engine、event store 或受控投影中。LLM 需要知道“不能说什么”时，只给 ID、mode、tactic、source refs、safe refs、`must_not_claim` 等结构化约束，不给禁说原文。

## 哪些只能进 constraints

以下信息不能作为自由文本事实放进 prompt，只能以结构化 constraint 或 ID 进入 `LLMAgentContractInput`：

- 禁说事实可见性：只用 `blocked_fact_ids` / `revealable_fact_ids`，不能传 `ForbiddenFact.text` 或 blocked terms。
- `WorldInfo` 披露边界：只用 `LLMDisclosureConstraint(item_kind=world_info)`，包含 `allowed_modes`、`forbidden_modes`、`rhetoric_tactics`、`must_not_claim`、`safe_fact_refs` 和 evidence refs。
- safe fragment 只能作为结构化安全片段引用或投影进入约束，例如 `world_info_id`、`fragment_id`、`ref`、`summary`、`allowed_modes`、`source_refs`；它不能携带 locked fragment、forbidden inference 或完整案件真相。
- 目标 NPC private self-knowledge 的对外表达边界：只用 `LLMDisclosureConstraint(item_kind=goal|secret|knowledge)` 表达 revealable、direct quote、相关 clue/world info refs。
- 事实触碰声明要求：只通过 `output_contract.disclosure_claim_required_for_world_info_touch` 和 schema 强制，不把完整案件真相作为提示。
- private portrait 影响表达的结果：可以体现为策略收窄、portrait_summary 或约束变化，不能把其他 NPC 的画像或可泄漏原文直接给 LLM。

关键原则：prompt 可以约束行为，不能成为事实权威；constraints 可以表达“允许说到哪一级”，不能把未解锁真相当作模型背景知识投喂。

## P0 硬链路

正式 runtime 的状态权威链路是：

```text
Action Intake
  -> PlayerAction
  -> optional Director precheck surface for router integration, no event write
  -> RuleEngine applies or rejects player action
  -> MemoryArchivalSystem before agent context for agent-backed actions
  -> AgentContext / LLMAgentContractInput
  -> AgentGateway / LLM output contract
  -> validate_llm_agent_output
  -> NarrativeDirector audit
  -> npc.replied or director.blocked
  -> RuleEngine.apply_agent_intent for allowed proposed_actions
  -> DerivedEventSystem / MemorySnapshotSystem
  -> RuleTriggerSystem
  -> Event store
  -> replay_events restores SessionState
```

其中 `Director.precheck_player_action(...)` 是给 Action Intake / Router 集成层使用的纯决策摘要，不写 `WorldEvent`，不替代 Rule Engine。当前 `ActionService` 的正式写入仍由 Rule Engine 执行：非法 `ask_about`、`present_clue`、`accuse` 写 `rule.rejected`；合法动作才进入 Agent 或指控评估。

`inspect` 不调用 Agent。`talk`、`ask_about`、`present_clue` 是 agent-backed actions。`accuse` 是正式结构化指控，不让 Agent 或 LLM 判断正确性。

## 状态写入边界

LLM 和 Agent 只能产生 `AgentIntent`。`AgentIntent` 不是状态变化。

`speech` 只有通过 Director 后，才会写 `npc.replied`。Director 拦截时写 `director.blocked`，并返回安全台词；不会写 `npc.replied`，也不会应用 `proposed_actions`。

`proposed_actions` 只有在 `npc.replied` 已写入后，才由 `RuleEngine.apply_agent_intent(...)` 解释。当前真实 LLM 只允许请求：

- `clue.discover`
- `relationship.change`

Rule Engine 仍会检查 clue 是否存在、关系端点是否合法、关系 metric 是否受支持、重复线索是否幂等。阶段变化只由 `narrative_rules.yaml` 和 `RuleTriggerSystem` 根据事件推进。

记忆、画像、玩家已知和角色事实认知都不是 LLM 直接写入的对象：

- `player_knowledge.updated` 来自规则派生。
- `memory_candidate.created` 来自 `DerivedEventSystem`。
- `agent_memory_snapshot.updated` 来自 `MemorySnapshotSystem` 或 `MemoryArchivalSystem`。
- `character_impression.updated` 来自运行时派生。
- `character_fact_awareness.updated` 来自运行时规则链。

所有真实变化必须进入 `WorldEvent`。PostgreSQL runtime 下，事件流是追加式权威；结构化 `PlayerAction` 和 raw text 入口都必须支持 `Idempotency-Key`。幂等 replay 使用同一批事件恢复状态，不重新调用 LLM，不重新推导不可见事实，也不允许同一玩家请求重试产生第二批事件。

## Director audit 边界

`NarrativeDirector.validate(...)` 是生成后安全门。它不推进剧情，不修改关系，不解锁线索，不判断正式指控。它负责在 `npc.replied` 前阻止越权台词：

- forbidden fact blocked terms 在 reveal phase 前命中。
- `disclosure_claims` 没有对应 `FactDisclosureStrategy`。
- claim mode 不在 allowed modes，或命中 forbidden modes。
- claim 使用 `full`。
- claim refs 命中 `must_not_claim`。
- speech 触碰 `WorldInfo` 却没有 disclosure claim。
- speech 直接命中 title、alias、claim pattern 或 forbidden term，但 claim 只声明 `hint`、`deny`、`deflect` 或 `none`。
- speech 实际触碰的 `WorldInfo` 与 claim 声明不一致。
- `FactGateway` 检测到 locked safe fragment 或 forbidden inference。

`disclosure_claims` 是 LLM 自报，不是授权。Director 独立扫描最终 `speech`，两者冲突时以 Director block 为准。

