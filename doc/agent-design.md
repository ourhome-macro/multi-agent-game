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

`AgentGateway.from_env()` 会读取本地 `.env`，但可用 `LLM_LOAD_DOTENV=0` 显式关闭，方便测试隔离。真实 LLM 适配器支持 OpenAI-compatible base URL：

```text
OPENAI_BASE_URL=https://api.xiaomimimo.com/v1
```

适配器会优先把 base URL 拼接到 `/responses`。如果 OpenAI-compatible 服务明确不支持 Responses API，会降级到 `/chat/completions`。例如小米 API 使用 `https://api.xiaomimimo.com/v1`，本轮真实 Shadow Eval 使用 `OPENAI_MODEL=mimo-v2.5` 验证通过。可用 `LLM_API_STYLE=chat_completions` 显式跳过 `/responses` 探测，直接请求 `/chat/completions`。Chat Completions 默认仍要求 `json_schema`；如果兼容服务不支持 schema，默认安全 fallback。只有显式设置 `LLM_ALLOW_JSON_OBJECT_FALLBACK=1` 时才允许降级到 `json_object`，且输出仍要经过 Python 合同校验和 Director。即使配置了 API key 和 base URL，常规运行仍只有在 `LLM_BACKEND=real` 时才使用真实后端。

## LLM Shadow Eval

LLM Shadow Eval v0 复用 Agent 合同，但不是正式运行链路。它只在标准路径的 Agent 行动点构造候选 `AgentIntent`，随后交给 `NarrativeDirector` 审计并写评测报告。

影子评测的硬边界：

- 默认使用 `LLMAgentStub`。
- 真实 LLM 只在 `LLM_SHADOW_EVAL=1` 且 `LLM_BACKEND=real` 且存在 `OPENAI_API_KEY` 时启用。
- 候选 intent 不会进入 `RuleEngine.apply_agent_intent`。
- 不写 `npc.replied`、`director.blocked` 或任何 `WorldEvent`。
- 不修改 `PlayerKnowledge`、`CharacterFactAwareness`、`WorldState`、`NarrativePhase`、`EventLog`。
- 即使评测进程设置了 `LLM_BACKEND=real`，标准路径推进也固定使用 `MockAgent`；真实 LLM 只生成 shadow candidate。

影子报告位于 `doc/case/<case_id>/llm_shadow_report.json` 和 `doc/case/<case_id>/llm_shadow_report.md`。`--all` 会额外写 `doc/evaluations/llm_shadow/summary.json` 和 `summary.md`。报告只记录 intent 摘要、Director 审计结果、`disclosure_claims` 摘要和 `failure_categories`，不公开原始 speech 或玩家自由文本，避免把 private 原文、forbidden facts、blocked terms 或 solution claims 写入公开文档产物。

真实对话调试可显式设置 `LLM_SHADOW_WRITE_RAW=1`，私有 transcript 只写入 ignored 的 `.shadow_eval/private_transcripts/` 或 `LLM_SHADOW_RAW_DIR` 指定目录，不进入 `doc`。安全基准可通过 `scripts/run_llm_shadow_eval.py --case mist_clock_manor --benchmark safety` 运行；它不调用真实 LLM，只用确定性候选 intent 检查 Director 和 schema guardrail。Red-team 探针可通过 `--redteam` 运行；它构造 adversarial 玩家行动来评估真实 LLM 是否会越权、剧透、伪造事实或试图改状态，但仍只产生 shadow candidate。

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
- `portrait_summary`
- `blocked_fact_ids`
- `revealable_fact_ids`
- `asked_subject_type`
- `asked_subject_id`
- `interaction_pressure`
- `subject_is_sensitive`
- `presented_clue_id`
- `presented_knowledge_id`
- `inner_context`
- `director_safe_fragments`

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

`director_safe_fragments` 是 `AgentLoop` 在构造上下文后由 `NarrativeDirector.safe_fragment_constraints(...)` 注入的生成前事实网关投影。它只包含当前目标 NPC 已有 `FactDisclosureStrategy` 的 `WorldInfo`，并且只包含当前 phase / beat / clue / player knowledge 条件已满足的 `WorldInfo.claim_graph.safe_fragments`。投影字段包括 fragment ref、safe summary、allowed modes 和授权 source refs；locked fragment、forbidden inference、solution claim 和 world truth 原文不得进入该字段。

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

`memory_candidates` 是运行时候选记忆；`memory_snapshots` 是从候选记忆归并出的稳定快照。AgentContext 只传递当前目标 NPC 可见的 player-scoped 记忆，不把其他 NPC 的私有记忆塞进上下文，不做向量检索、RAG 或 LLM 摘要。

Memory v1 支持四类 `memory_type`：`episodic`、`belief`、`relationship`、`strategy`。`build_agent_context(...)` 和 `MemoryRetriever` 会按目标 NPC 可见性过滤；Director 审计可以通过专门入口读取所有 player-scoped memory，但这不等于注入某个 NPC 的 AgentContext。

Memory v1.1 要求每条 memory 带 `rule_id` 和 `source_event_ids`。规则来源由 `MemoryDerivationRule` 表示。

Memory v1.1 hardening 进一步要求每条 candidate / snapshot 都带：

- `memory_scope`：`case`、`session`、`npc_private`、`scene_shared`、`director_audit`
- `memory_layer`：`core`、`working`、`archival`

现有 typed memory 默认是 `npc_private` + `working`。`player.presented_clue` 的展示范围由结构化 `presentation_mode` 决定：`private` 只生成目标 NPC 可见的私有互动记忆；`scene_shared` 必须带合法 `scene_id` 和 `present_character_ids`，运行时会额外生成 `scene_shared` memory，且 `visible_to_character_ids` 必须等于当前场景在场 NPC。自然语言 Router 不负责从玩家文本里推断公共场景。

`build_agent_context(...)` 的常规投影只允许注入 `case/core`、`session/working`、当前目标 NPC 可见的 `npc_private`、当前目标 NPC 可见的 `scene_shared` 和当前目标 NPC 自己的 `portrait_summary`。它必须禁止注入 `director_audit`、其他 NPC 的 `npc_private` 和其他 NPC 的 portrait。`archival` memory 只有在 `MemoryRetriever` 冷召回选中后才能进入 `memory_snapshots`，不能由 skill 或 prompt 直接强塞。

`MemoryRetriever` 的默认 NPC 检索顺序是 `memory_scope` -> `visible_to_character_ids` / `owner_character_id` -> `memory_layer`。Director 审计入口 `retrieve_for_director(...)` 可以读取 `director_audit` 和其他非 archival player-scoped memory，但不能把这些记忆塞回普通 NPC `AgentContext`。

Memory v1.2 增加 Skill-driven Retrieval Planner。`MemoryProjectionSkill` 使用 Markdown + YAML frontmatter，默认位于 `app/agents/skills/memory_projection/*.md`，案件可在 `cases/<case_id>/skills/memory_projection/*.md` 用同 id 文件覆盖默认 skill。frontmatter 必须包含 `id`、`description`、`trigger`、`include`、`forbid`、`projection`、`disclosure`。`SkillSelector` 只按结构化 `PlayerAction` 的 trigger 选择 skill，不允许 LLM 自由选择。

当前默认 projection skills：

- `talk`：普通 talk、present_clue、非 clue ask_about 的通用投影。
- `ask_about_clue`：线索询问的渐进式披露投影。
- `accuse`：正式指控时的更宽但仍受边界限制的投影。

`RetrievalPlanner` 从 skill 生成 `MemoryRetrievalPlan`，控制允许的 `memory_type`、`memory_scope`、常规 `memory_layer`、禁止的 scope/layer、`max_memory_items`、是否注入 `portrait_summary`、是否允许 `recent_events`。`recent_events=false` 同时约束 `AgentContext.recent_events` 和 `ToolRuntime.get_recent_events` 的结果计数。硬边界仍在代码里：`director_audit`、其他 NPC private、其他 NPC portrait 和 forbidden fact 文本不能被 skill 放进普通 NPC `AgentContext`。`archival` 即使出现在 skill 的 forbidden layer 中，也可在代码级冷召回路径被选中；该路径只在常规 working/core 没有相关命中时触发，并且不放宽其他边界。

Memory v1.3 hardening 改进的是检索质量，不改变记忆权威链路。`MemoryRetriever` 仍先执行 scope、可见性、layer、skill plan 和 forbidden fact 过滤，再对可注入 snapshot 做运行时排序。排序分数只在检索时派生，不能写回 `AgentMemorySnapshot`、`WorldEvent` 或 trace content。当前分数来源包括结构化锚点匹配、中文/英文文本 token、`updated_at` recency、由 `source_event_ids` 派生的 reinforcement、salience 和 confidence。recency / reinforcement 只能在已有结构化或文本相关性命中后加分，不能单独召回无关记忆。

`build_agent_context(...)` 的 `memory_snapshots` 投影必须复用 `MemoryRetriever` 的质量排序并在排序后应用 `max_memory_items`，不能重新按 `memory_id` 截断。AgentLoop 路径中，注入到 loop 的 `MemoryRetriever` 是唯一事实源：loop 先检索出 `memory_snapshots`，再传给 `build_agent_context(...)`、trace `memory_projection` 和 tool `search_memory` 摘要。只有直接调用 `build_agent_context(...)` 且未传入 `memory_snapshots` 时，函数才会使用内部 fallback retriever。

Memory Retrieval Matrix 是 Agent 记忆投影的回归评测入口。它可以直接验证 `MemoryRetriever.retrieve(...)`，也可以验证已构造的 `AgentContext.memory_snapshots`。前者用于锁定底层召回和隔离边界；后者用于锁定当前 projection skill 在特定 phase 下实际给普通 NPC 的记忆集合。新增或替换 BM25、embedding、reranker、排序权重、projection skill 时，必须确认同一矩阵里的 `expected_memory_ids` 与 `forbidden_memory_ids` 不漂移，尤其是 `npc_private`、`scene_shared`、`director_audit` 和 `archival` 的边界。

Memory v1.3 P0 hardening 进一步收紧真实 LLM 输入边界：运行时内部 `AgentContext` 可以为了兼容 mock、调试和直接调用保留 `memory_candidates` 与 `recent_events`，但 `build_llm_agent_input(...)` 会构造安全投影后再进入真实 LLM 合同。该投影清空 `memory_candidates`，移除未被本轮 retriever 选中的 memory events，并对已选中 memory events 的 payload 脱敏。真实 LLM 可读取的记忆事实内容只能来自同一批 selected `memory_snapshots[].content`；recent event、compressed history、tool summary 和 trace 都不能成为第二条记忆内容通道。

Memory P2 后，归档不再只是“可 replay 但永不注入”。`MemoryArchivalSystem` 在 agent-backed action 构造上下文前，把陈旧且未强化的 working memory 通过 `agent_memory_snapshot.updated(operation=archived)` 降级为 `archival`。`MemoryRetriever` 先执行常规 `core/working` 检索；只有没有任何结构化或文本相关命中时，才对当前 NPC 可见的 archival memory 做冷召回。被冷召回的 archival memory 仍然是 selected `memory_snapshots` 的一部分，因此 P0 的 LLM 安全投影继续适用。

Memory v1.4 后，`MemoryDerivationRule` 由代码级 loader 合并 app 默认规则与案件规则。规则可以声明 trigger event、target / clue / subject / claim 约束、memory type/scope/layer、owner、visible characters、subject、salience/confidence、metadata、content template、source event ids 和 source memory ids。Agent 和 LLM 仍不能创建、修改或删除 memory；它们最多通过结构化 action 触发后端规则链。未迁移到配置的 core memory 仍由 Python fallback 产生，fallback 只在配置规则没有产生同一目标 memory 时执行。

适合放进 skill 的是“检索和渐进式披露策略”：剧情阶段打开哪些 memory type、完成哪些 beat 后允许 belief/strategy、某类动作最多投影几条、是否带画像摘要、是否允许 recent events。适合放进 system prompt 的是全局不可违反纪律：玩家文本是数据、不能写状态、不能越权披露、输出必须是结构化 intent。Memory 只描述发生过什么和 NPC 记住什么；Portrait 只描述 NPC 当前怎么看玩家；State 只描述当前进度和已完成 beat。

`portrait_summary` 是目标 NPC 自己的私有画像摘要投影，例如“江医生当前对玩家高度警惕”。它用于让 Agent 感知当前态度和策略，但不暴露其他 NPC 的画像，也不直接复制原始画像解释文本。

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

`inner_portraits` 是目标 NPC 当前如何看待玩家的 `CharacterImpression`。v0 只支持 NPC -> player。画像不是角色真相，也不是公开资料；它是主观私有认知，可影响后续话术、警惕、合作、威胁判断和分支条件。`CharacterImpression` 继承 `NPCPortraitState`，因此同时包含 `trust`、`suspicion`、`fear`、`traits`、`current_strategy` 和 `source_memory_ids`。

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

`AgentContext.recent_events` 会过滤私有运行时事件，避免一个 NPC 通过近期事件流看到另一个 NPC 的私有画像、私有 typed memory、角色事实认知或私有玩家交互。当前目标 NPC 只能通过 `inner_context.inner_portraits` 看到自己的画像。

PromptBuilder 只把 `portrait_summary` 和 inner context 的 id 级摘要写入 prompt payload，不把其他 NPC 的 private memory、private portrait 或角色卡 private 原文写入 Agent 输入。

## 安全边界

`AgentContext` 不得包含：

- 原始 `CharacterPrivateConfig`
- 其他 NPC 的 `secrets`、`goals` 或内部 `knowledge`
- 其他 NPC 的 `character_fact_awareness`
- 其他 NPC 的 private impressions
- 其他 NPC 的 private typed memory
- `director_audit` memory
- 未被 `MemoryRetriever` 冷召回选中的 `archival` memory
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
  "memory_refs": [],
  "disclosure_claims": []
}
```

`AgentIntent.proposed_actions` 不是真实状态变化，只是请求。它必须经过白名单和 Rule Engine 校验后才能改变状态。Agent intent 不能创建 `memory_candidate.created`、`agent_memory_snapshot.updated` 或 `character_impression.updated`；这些事件都由运行时派生。

同理，Agent intent 不能创建或修改 `character_fact_awareness.updated`。角色事实认知只由运行时根据案件初始配置和玩家交互事件派生。

Agent 也不能写 `FactDisclosureStrategy`。策略是上下文投影，不是状态；每次构造 `AgentContext` 时由后端重新计算。

`AgentIntent.disclosure_claims` 是 Agent 对最终台词触碰事实的自我声明。它不是状态变化，也不是授权来源。每个 claim 都必须被 Narrative Director 对照目标 NPC 当前的 `FactDisclosureStrategy` 审计：

- `world_info_id` 必须存在于当前约束中。
- `mode` 必须在 `allowed_modes` 内。
- `mode` 不能在 `forbidden_modes` 内。
- `full` 永远拒绝。
- `claim_refs` 不能命中 `must_not_claim`。
- 如果 `speech` 实际触碰某个 `safe_fragment`，同一个 claim 必须通过 `claim_refs` 或 `source_refs` 引用该 Director 授权的 safe fragment 或其解锁来源。

如果台词直接命名某个 `WorldInfo`，但没有对应 `disclosure_claim`，Director 会拒绝该回复并降级为安全台词。

更重要的是，`disclosure_claims` 只是 Agent 自报，不是通行证。Narrative Director 会独立扫描最终 `speech`，用 `WorldInfo.title`、`WorldInfo.aliases`、`WorldInfo.claim_patterns` 和禁说词映射判断实际触碰了哪些事实。只要 speech 的实际触碰超过 claim.mode，或触碰了没有声明的另一个 `WorldInfo`，回复都会被拒绝。

对配置了 `claim_graph` 的 `WorldInfo`，Director 还会扫描 safe fragment alias / pattern 与 forbidden inference alias / pattern。`partial` claim 必须引用授权 safe fragment；即使 claim mode 合法，只要台词复述了某个 safe fragment 但没有匹配的 `claim_refs` 或 `source_refs`，Director 也会拒绝并降级为安全回复。多个 safe fragment 组合触发 locked forbidden inference 时，同样拒绝。

这意味着 LLM 负责语言表现，但不能通过“claim 写得保守、台词说得直接”的方式绕过事实披露边界。安全降级和 `director.blocked` 事件由后端生成，不由 Agent 决定。

允许的 proposed action 类型：

- `clue.discover`
- `relationship.change`
- `narrative.phase.change`

`narrative.phase.change` 保留在 schema 中用于审计，但 Rule Engine 会拒绝它。剧情阶段只能由 `narrative_rules.yaml` 通过 `RuleTriggerSystem` 推进。

## 实现说明

`MockAgent` 使用 `AgentContext`，根据案件包中的确定性规则选择回复。它可以根据阶段、已发现线索、询问对象、展示线索、交互压力、敏感主题、记忆快照、关系指标和目标 NPC 自己的 `inner_portraits` 改变回复。

当 `PlayerAction.force_forbidden=true` 时，`MockAgent` 会输出一段专门用于测试的越界探针台词。探针只服务于自动化测试，用来确认 Narrative Director 能拦截当前阶段禁说的事实，不代表真实 LLM 可以绕过 `FactDisclosureStrategy`。新增真实案件时，如果希望剧情级回归覆盖某个禁说事实，应让该禁说事实拥有稳定 `blocked_fact_id`，并在 mock 探针中有对应的可检测台词。

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

`present_clue` 不表示线索证明 NPC 有罪，只表示玩家用已知线索施压、试探或质询 NPC。其 `presentation_mode` 来自 UI / API / REPL 的结构化动作契约，Agent 只能在 `AgentContext.player_action` 摘要中读取该字段，不能据此自行扩大可见 NPC 或写入记忆。真相推进仍属于 Rule Trigger System 和 narrative rules。

`LLMAgentStub` 返回合法 `AgentIntent`，不调用外部模型，也不修改 `SessionState`。它用于在接入真实模型前锁定 LLM 合同。

`OpenAILLMAgent` 是最小真实后端适配器。它构造 `LLMAgentContractInput`，请求符合 `AgentIntent` 的严格 JSON，运行 `validate_llm_agent_output`，返回校验后的 intent。任何失败都会返回无 `proposed_actions` 的安全拒答。失败包括缺少 API key、HTTP 错误、JSON 错误、schema 错误、private 原文回显、直接提议剧情阶段变化。

真实 LLM fallback 不是静默兜底。`OpenAILLMAgent.generate(...)` 会在安全拒答的 `AgentIntent.llm_error` 中记录机器可读错误摘要：

- `network_error`
- `timeout`
- `invalid_json`
- `schema_error`
- `policy_violation`
- `private_leak_detected`
- `configuration_error`
- `unknown_error`

`RuntimeTracer` 会把 `llm_fallback_used`、`llm_error_type`、`llm_error_message_sanitized` 和 `schema_validation_errors` 写入 trace；`ActionResponse` 同步返回 `llm_fallback_used` 和脱敏 `llm_error`。这些字段只用于观测和排障，不授予 Agent 任何状态写入权限。

`LLMAgentContractInput.disclosure_constraints` 会同时包含 private self-knowledge 约束和 `world_info` 级事实披露策略约束。`world_info` 约束会带 `allowed_modes`、`forbidden_modes`、`rhetoric_tactics`、`must_not_claim`、`safe_fact_refs` 和 `safe_fragments`，用于告诉 LLM：你可以怎么说，但不能说到哪里。`safe_fragments` 只来自 Director 放行的 safe fragment summary；blocked fragment、forbidden inference、solution claim 和 world truth 原文不进入真实 LLM payload。`LLMAgentContractInput.output_contract` 额外提供机器可读枚举边界：合法 intent、合法 proposed action、合法 disclosure mode 和“speech 触碰 WorldInfo 必须自报 claim”的规则。

真实 LLM 输出必须包含 `disclosure_claims`。合同校验器会先拒绝越权 claim；Narrative Director 会再次根据最终文本、`WorldInfo` 文本审计字段、`safe_fragments` 和 `FactDisclosureStrategy` 执法。这样 strategy 不再只是提示，而是后置安全门。真实适配器的动态 schema 会把 `disclosure_claims.world_info_id` 收窄到当前可声明的 `world_info` 约束，把 `claim_refs` / `source_refs` 收窄到当前 safe refs，并禁止 `full` 作为真实 LLM 输出模式。

真实适配器不改变状态权威模型。它的输出仍经过 Narrative Director，所有 `proposed_actions` 仍经过 Rule Engine。除非显式环境变量启用，否则它不参与完整场景快照。

## 记忆检索 v2

Memory v2 将检索拆成可审计管线：

- hard filter：先执行 scope、owner/visible、layer、source provenance、phase、plan、forbidden content 过滤。
- keyword/BM25：只在通过硬边界的候选中做关键词相关性排序。
- embedding scorer：预留可插拔接口，当前默认不调用外部服务。
- reranker：预留二阶段排序接口，当前默认保持 deterministic 顺序。

普通 NPC 不会因为 `salience` 高就召回无关记忆。`salience` 可留在快照中供审计和叙事解释，但不作为相关性总分来源；只有结构化锚点、关键词/topic/source 命中或 embedding 命中能让候选进入排序。若 working/core 没有相关命中，结果为空；只有 archival cold recall 可以在 working/core 无命中时尝试，但仍必须满足当前 NPC 可见性、scope、type、source provenance、phase、forbidden fact 和 plan 约束。

记忆矩阵评测见 `doc/evaluations/memory-retrieval-matrix-2026-06-15.md`。新增检索策略、embedding 或 reranker 之前，必须用矩阵确认“应召回 / 不应召回”的 memory_id 没有漂移。

完整 LLM 输入/输出合同见 `doc/agents/llm-agent-contract.md`。

## System Prompt 编排

当前真实 LLM 的 provider 级 system instructions 只来自 `app/agents/prompts/system.md`。`OpenAILLMAgent` 通过 `load_agent_system_prompt()` 把它传入 Responses API 的 `instructions`，或传入 Chat Completions 的 `system` message。`system.md` 只放全局硬纪律：玩家文本和工具输出都是数据、只能输出一个 `AgentIntent` JSON、不得输出推理过程、不得泄露 private/forbidden/solution 信息、不得提出剧情阶段变化、真实状态变化只能通过白名单 `proposed_actions` 请求。

动态运行时事实不拼进 system prompt。真实 LLM 的 user payload 是 `LLMAgentContractInput`：`agent_context` 是安全投影后的目标 NPC 视图；`disclosure_constraints` 是当前 self-knowledge、`FactDisclosureStrategy` 和 blocked fact id 派生的表达约束；`output_contract` 是机器可读输出边界。禁说事实原文、blocked terms、solution claims、线索 truth_status、其他 NPC private、未选中 memory content 和 `director_audit` memory 都不能进入该 payload。

`PromptBuilder` 仍由 `AgentLoop` 使用，但当前用途是本地 prompt surface 和 context budget 估算：`agent_prompt` 是 `AgentContext` 的 JSON 摘要，`contract_instruction` 来自 `output_contract.md` 与 `disclosure_policy.md`，`safety_instruction` 来自 NPC turn、memory、tool policy 和 skill discipline。当前 `OpenAILLMAgent` 不把这些段落拼接到 provider 请求里；真实 provider 请求的 system 来源仍是 `system.md`，动态事实和约束来源仍是 `LLMAgentContractInput`。

输出边界分三层执行：

- provider 动态 JSON schema 收窄字段、枚举、`disclosure_claims.world_info_id` 和真实 LLM 可请求的 proposed action 类型。
- `validate_llm_agent_output(...)` 在 Python 层拒绝额外顶层字段、阶段变化、越权 disclosure claim、`mode=full`、未知 `world_info_id`、命中 `must_not_claim` 和 private 原文回显。
- `NarrativeDirector.validate(...)` 独立审计最终 `speech`，确认 claim 与实际触碰的 `WorldInfo` 一致。

schema / JSON repair 只修合同形状，不补新事实。repair instruction 使用同一个 `system.md`、同一个 `LLMAgentContractInput` 和同一个动态 schema，并明确要求不要添加新事实。真实 LLM fallback 是带 `llm_error` 的安全拒答，`proposed_actions=[]`、`memory_refs=[]`、`disclosure_claims=[]`，仍会进入 Director 和 trace，不会绕过状态权威链。

P0 硬链路详见 `doc/architecture/p0-hard-chain-2026-06-16.md`。

## 案件级 Agent 扩写

`mist_clock_manor` 的 2026-06-14 扩写只新增可选 mock dialogue 和 memory derivation rule，不改变 Agent 权限边界。新增规则仅在玩家询问或展示新增线索时产生 NPC 私有工作记忆，不能写世界事实、线索状态、剧情阶段或最终指控结果。

案件级 mock 回复必须按 Director 的文本审计规则编写：如果回复没有 `disclosure_claims` 支持，就不要直接复用 `WorldInfo.title`、`aliases` 或 `claim_patterns` 中的完整表达。可选线索的 NPC 反应应维持“承认观察痕迹、回避完整因果”的粒度。
