# Agent / Memory / Context / Orchestration Review - 2026-06-26

## 总结

Agent 部分已经不是简单 mock NPC 对话。当前主链路是：

`PlayerAction -> RetrievalPlanner -> MemoryRetriever -> AgentContext -> LLMAgentContractInput -> provider compact payload -> AgentIntent validation -> NarrativeDirector -> RuleEngine -> WorldEvent`

这条链路的状态边界是正确的：LLM 只产出 `AgentIntent`，状态变化仍由 Narrative Director 与 Rule Engine 接管。记忆模块、检索和上下文预算都有可审计骨架；多 Agent 编排还停在实验性 secondary reaction。

## 记忆模块

成熟点：

- `memory_candidate.created -> MemorySnapshotSystem -> agent_memory_snapshot.updated` 的写入链路清楚。
- active memory 必须带 `source_event_ids`，否则被拒绝；非权威 unsourced memory 可保存但不会被高影响召回使用。
- `create / reinforce / revise / supersede / archive` reducer 已有测试覆盖。
- `memory_scope` 和 `memory_layer` 已经成为硬边界：`case/core`、`session/working`、`npc_private/working`、`scene_shared/working`、`director_audit`、`archival` 分层明确。
- `MemoryArchivalSystem` 已有生命周期：过期且未强化的 working memory 归档；冷召回仅在 working/core 无相关命中时触发。
- Postgres 模式有 `memory_snapshots` 投影表和 `PostgresMemoryStore` 第一阶段预筛。

风险点：

- 记忆派生仍有 Python fallback 和 YAML rule 双轨。短期可以接受，但长期会让案件扩写分散在代码和配置两处。
- memory id、metadata、topic tags 的生成仍靠多处字符串约定。它们是幂等键和检索锚点，后续应收敛成稳定 builder，并补回放测试。
- `MemorySnapshotSystem` 的 reducer 已经够用，但还不是事件溯源完整语义模型；例如 revise/supersede 的业务含义还只是字段覆盖策略，没有显式冲突策略。

## 检索召回

成熟点：

- `MemoryRetriever` 有硬过滤：subject、scope、target visibility、layer、source provenance、phase、plan、forbidden text。
- 检索前有 `RetrievalPlanner` 和 memory projection skill，按 `talk / ask_about_clue / accuse` 区分召回类型、scope、layer、max items、recent events 和 portrait summary。
- 搜索打分包含 structured anchor、BM25 keyword、可插拔 embedding scorer、reranker、recency、reinforcement、salience、confidence。
- 高影响记忆走 `memory_authority`，对 belief / relationship / strategy 做权威性门控和冲突 winner 选择。
- trace 记录 store candidate、hard filter、score、authority、selected count，但不记录 memory content。

风险点：

- 默认语义召回很浅。`LocalSemanticEmbeddingScorer` 只是 deterministic alias scorer，当前 concept alias 极少，不足以支撑复杂中文表达、隐喻、跨线索联想。
- Postgres store 只做第一阶段 SQL 预筛，没有 FTS / trigram / pgvector，也没有按 query anchor 下推检索；数据量上来后会变成“先捞一批再 Python 排序”。
- `zero_reason` 和 filter counts 可观测，但还没有召回质量评估：没有 golden query set、MRR/Recall@K、误召回率、漏召回案例库。
- `RetrievalPlanner._apply_rule` 目前没有处理 rule 级 `topic_tags`，topic tag 主要由 NPC skill memory policy 收窄。后续如果希望 memory projection skill 自身按 topic 精细召回，需要补这一层。

## 上下文管理

成熟点：

- `ContextBudgetManager` 明确区分 hard context 和 soft context。
- hard context 超限会阻断生成，返回 `context_over_limit` 安全拒答，不会让 Agent proposed action 进入 Rule Engine。
- provider 预算口径已经基于 compact provider payload，而不是完整 `LLMAgentContractInput`。
- `provider_payload.py` 已剔除 `reply_options`、完整 event payload、source event ids、rule id、created/updated 等审计字段。
- `LLMAgentContractInput.context_layers` 记录 hard/soft 投影，用于证明哪些内容不可被压缩。

风险点：

- soft compression 目前主要是增加 `compressed_history` 引用，并重新预算；它没有真正裁剪 `recent_events`、memory descriptions、portrait summary 或 private context。因此这是“软压缩标记”，不是完整压缩器。
- provider payload 仍包含目标 NPC 的 self knowledge summary、fact awareness、disclosure strategies、portrait 文本。这些不是越权泄漏，但会继续吃 token。
- 预算估算仍是保守估算，未接 provider tokenizer；生产成本预测只能近似。

## 多 Agent 编排

当前状态：

- `NpcSkillSelector` / `AgentTurnPlan` 已经能表达单 NPC 的技能授权、披露上限、可用 tactics、allowed proposed actions、relationship delta cap。
- `AgentOrchestrator.run_secondary_reactions` 只做 secondary reactions：遍历其他角色，把同一个 action 改 target 后新建 `AgentLoop` 跑一遍。

主要问题：

- secondary loop 没复用 primary loop 的 retriever、planner、budget manager、director、tool runtime、trace sink；它只注入 secondary gateway，并关闭 tracer。
- secondary reaction 没有明确触发事件模型，例如“旁听”“同场角色听见”“主动插话”“私下反应”“记忆传播”。
- secondary turn 返回 `AgentTurnResult`，但当前主 runtime 不把它作为一等事件链路提交；因此不是真正的多 Agent 世界编排。
- 没有调度策略：谁能反应、为何反应、是否同场、是否可听见、是否打断主 NPC、是否消耗 action，都还没建模。

结论：多 Agent 目前只能算 isolated secondary experiment，不能算生产级编排。

## 推荐优先级

P0/P1 之后，下一步最该做：

1. 多 Agent 不要继续在 `AgentOrchestrator` 上堆逻辑，先设计事件模型：`scene.audible`, `npc.overheard`, `npc.reaction_requested`, `npc.reacted`, `memory.propagated`。
2. 做真正 soft context compression：在预算超阈值时按 plan 裁剪 recent events / memories / private context，并确保二次 provider payload 真的变小。
3. 给 retrieval 建 golden query set：每个案件维护 query -> expected memory ids，跑 Recall@K / false positive。
4. Postgres retrieval 增加 FTS 或 pgvector 前置候选召回，但硬过滤仍保留在 `MemoryRetriever`。
5. 把剩余 Python memory fallback 逐步迁到 YAML `MemoryDerivationRule`，让案件扩写不再改运行时代码。

## 验证

已跑聚焦测试：

`py -3.12 -m pytest tests\test_memory_v2.py tests\test_memory_archival_p2.py tests\test_memory_db_retrieval.py tests\test_context_budget_safety.py tests\test_agent_runtime_mvp.py tests\test_agent_runtime_remaining_phases.py tests\test_agent_turn_plan_skill_contract.py tests\test_llm_provider_payload.py`

结果：60 passed。

