# 运行时架构

本项目是一个“案件无关”的后端叙事运行时。它负责加载案件包、创建内存会话、处理玩家行为、生成可审计事件日志，并返回公开状态摘要。默认不调用真实 LLM，不使用数据库持久化，不使用向量记忆，也不包含前端。

## 启动流程

```text
FastAPI app
  -> 扫描 cases/*
  -> CaseLoader.load(包含 case.yaml 的目录)
  -> create_runtime(case packages)
  -> InMemoryCaseStore / InMemorySessionStore
  -> API routes
```

如果 YAML schema 校验或跨文件引用校验失败，启动会抛出 `CaseLoadError`。

角色配置采用“公开/私有角色卡”结构。公开字段描述 NPC 身份和可见行为；私有目标、秘密和内部知识表示 NPC 自己的非公开视角。私有信息不是对该 NPC 隐藏，而是不能自动对玩家、其他 NPC 或公开 API 暴露。当前 v0 不会把原始 private 配置复制到公开状态，只会在 `AgentContext` 内构造目标 NPC 专属的 `CharacterInnerContext`。

`character_impression.updated` 是运行时派生的 NPC 对玩家的私有主观画像。它不是角色卡真相，也不是公开 `StateSummary` 数据。

`AgentGateway.from_env()` 默认使用 `mock` 后端。只有显式设置环境变量时才会启用真实 OpenAI 适配器：

```text
LLM_BACKEND=real
OPENAI_API_KEY=...
```

缺少任一变量时仍回退到 `MockAgent`。`LLM_BACKEND=llm_stub` 会选择本地合同桩，不发起网络请求。

## 行为处理流程

```text
POST /sessions/{id}/actions
  -> PlayerAction
  -> SessionState
  -> build AgentContext
  -> AgentGateway.generate(context)
  -> AgentIntent
  -> NarrativeDirector.validate
  -> RuleEngine.apply_*
  -> DerivedEventSystem.derive
  -> MemorySnapshotSystem.apply
  -> RuleTriggerSystem.evaluate
  -> EventRecorder.append
  -> StateSummary
```

`inspect` 不调用 Agent。它只校验热点，并由 Rule Engine 解锁合法线索。

`talk` 会构造 `AgentContext` 并调用 `AgentGateway`。默认实现是 `MockAgent`；`LLMAgentStub` 只是本地占位，不调用外部模型；`OpenAILLMAgent` 是可选适配器，不参与默认测试和场景快照。

`ask_about` 是结构化询问动作。Rule Engine 校验被询问对象，写入 `player.asked_about`，之后走与 `talk` 相同的 AgentGateway -> Director -> Rule Engine 链路。

`present_clue` 是玩家向 NPC 施压或展示证据的动作。Rule Engine 会先校验：`target_id` 是已知角色、`clue_id` 存在、线索已被发现、且玩家已知账本里存在对应 `player_knowledge`。合法时写入 `player.presented_clue`，再进入 Agent 链路。非法时写入 `rule.rejected`，不会产生 NPC 回复或关系变化。

`present_clue` 不等于证明真相，只表示玩家用某条已知线索进行施压或试探。叙事真相仍只能通过事件和 `RuleTriggerSystem` 推进。

`accuse` 是正式指控动作，不调用 `AgentGateway`。Rule Engine 根据 `solution_claims.yaml` 校验 `claim_id`、当前剧情阶段和玩家已掌握证据，写入 `player.accused`，再写入 `accusation.evaluated`。它不直接修改剧情阶段；阶段变化仍由 `RuleTriggerSystem` 根据事件触发。

## 核心模块

- `app/domain/models.py`：Pydantic v2 领域模型和 API DTO。
- `app/cases/loader.py`：YAML 加载和案件包引用校验。
- `app/agents/context.py`：构造安全的 `AgentContext`。
- `app/agents/protocol.py`：定义 `AgentProtocol`。
- `app/agents/gateway.py`：Agent 生成的统一入口。
- `app/agents/mock_agent.py`：确定性 mock 实现。
- `app/agents/llm_contract.py`：未来 LLM 输入/输出安全合同。
- `app/agents/llm_stub.py`：schema 安全的 LLM 占位实现。
- `app/agents/real_llm_agent.py`：默认禁用的 OpenAI 适配器，只返回校验后的 `AgentIntent` 或安全拒答。
- `app/director/narrative_director.py`：阻止 NPC 输出禁说事实。
- `app/rules/engine.py`：真实状态变化的唯一权威。
- `app/rules/triggers.py`：根据事件完成 beat 并推进 phase。
- `app/runtime/derivations.py`：派生玩家已知、记忆候选和私有角色画像。
- `app/runtime/memory_snapshots.py`：把记忆候选归并成稳定 Agent 记忆快照。
- `app/runtime/replay.py`：从 `WorldEvent` 重建 `SessionState`。
- `app/storage/memory.py`：内存案件/会话存储与 `StateSummary` 构造。

## 状态权威

Agent 只能输出 `AgentIntent`。它不能直接修改 `SessionState`、世界事实、线索、关系、剧情阶段或事件日志。

`AgentIntent.proposed_actions` 必须先通过模型白名单，再经过 Rule Engine。非法动作会生成 `rule.rejected`，不得污染状态。

剧情阶段变化由 `narrative_rules.yaml` 和 `RuleTriggerSystem` 驱动，不由 Agent 输出决定。

正式指控的正确性由 `solution_claims.yaml` 编写，并由 Rule Engine 评估。Agent 和 LLM 不决定指控是否成立。Rule Engine 也不直接把案件设为 resolved；它只写入 `accusation.evaluated`，后续由 `RuleTriggerSystem` 消费该事件。

## Agent 输入安全

Agent 接收的是 `AgentContext`，不是原始 `CasePackage` 或 `SessionState`。

`AgentContext` 不包含角色原始 `private`、秘密、目标、内部知识、线索 `truth_status` 或禁说事实原文。禁说范围只通过 `blocked_fact_ids` 和 `revealable_fact_ids` 表示。被询问对象用 `asked_subject_type` / `asked_subject_id` 表示。展示证据用 `presented_clue_id` / `presented_knowledge_id` 表示。`interaction_pressure` 是后端计算出的 `0.0 .. 1.0` 数值。

`AgentContext.target_profile` 来自公开的 `AgentCharacterView`，可以包含公开身份、公开描述、说话风格、可见性格、压力/信任/恐惧反应风格。不得包含 private、目标、秘密、内部知识、真相状态、禁说事实原文或结案声明。

`AgentContext.inner_context` 是目标 NPC 专属的 `CharacterInnerContext`。它包含该 NPC 自己的受控自我知识项和披露策略元数据。它不能包含其他 NPC 的私有数据，不能通过公开 API 返回，也不能复制进 `WorldEvent`。

`CharacterInnerContext.inner_portraits` 只包含当前目标 NPC 自己的 `CharacterImpression`。v0 只支持 NPC -> player 画像。`AgentContext.recent_events` 会过滤 `character_impression.updated`，避免一个 NPC 从事件流里看到另一个 NPC 的私有画像。

`memory_candidate.created` 只是候选记忆事件。运行时的 `MemorySnapshotSystem` 消费它并生成 `agent_memory_snapshot.updated`，更新 `session.memory_snapshots`。Agent 可以读取安全的 player-scoped 记忆快照，但不能直接创建或修改快照。

`character_impression.updated` 是运行时派生的私有认知事件，来源包括 `player.asked_about`、`player.presented_clue`、`player.accused`、`relationship.threshold.crossed`、`director.blocked` 和 `accusation.evaluated`。LLM 可以读取目标 NPC 自己的画像视图，但不能直接写画像状态。

画像感知披露 v0 会用私有画像计算目标 NPC 自我知识项的有效 `DisclosurePolicy.allowed_modes`。高威胁或危险话题会收窄披露；高结盟潜力可允许谨慎 hint；玩家有相关证据时可允许 partial；但永远不能授予 full reveal 或直接引用 private 原文。

`LLMAgentContractInput` 用显式披露约束包裹 `AgentContext`，供未来真实 LLM 使用。`validate_llm_agent_output` 要求严格 `AgentIntent` JSON，并在 Rule Engine 前拒绝 LLM 提出的剧情阶段变化。

真实适配器启用时，会发送 `LLMAgentContractInput`，请求严格 JSON，使用 `validate_llm_agent_output` 校验返回值。API 错误、JSON 错误、schema 错误、阶段变更提议或 private 原文回显都会降级为安全拒答。适配器不写事件，也不能绕过 Narrative Director 或 Rule Engine。

## 事件回放

所有真实状态变化和运行时派生事实都必须表示为 `WorldEvent`。`replay_events(case, events)` 必须能重建等价关键状态：

- case id
- narrative phase
- completed beats
- discovered clues
- relationships
- player knowledge
- memory candidates
- agent memory snapshots
- private character impressions
- event count

Replay 会直接应用已持久化的 `agent_memory_snapshot.updated` 和 `character_impression.updated`，不会重新跑派生或聚合逻辑，因此不会递归创建新事件，也不会改变事件数量。
