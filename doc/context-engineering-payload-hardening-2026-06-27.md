# Context Engineering Payload Hardening - 2026-06-27

## 背景

真实 LLM 请求不能发送完整 `LLMAgentContractInput` 或完整 `AgentContext`。完整合同属于本地审计、回放、动态 schema 和输出校验；provider payload 只能是生成需要的紧凑 DTO。

本轮重点解决三个上下文问题：

- soft compression 不能只写 `compressed_history` 标记，还必须实际裁剪 soft context。
- provider payload 不能继续携带目标 NPC 的 `self_knowledge`、`fact_awareness`、`disclosure_strategies`、portrait 文本或完整 memory content。
- token budget 必须按 provider/model profile 计算，并允许接入 provider/model tokenizer；没有真实 tokenizer 时 trace 必须暴露 fallback estimator method。

## 已落地边界

- 真实 provider payload 不再包含 `recent_events`、`context_layers`、`portrait_summary`、`private_context`。
- 目标 NPC 的 self-knowledge summary、fact awareness、disclosure strategy 不再发送给真实模型；这些只保留在本地合同、Director 和输出校验中。
- `memories[]` 不再发送完整 `AgentMemorySnapshot.content`，改为 compact `summary`、salience、confidence 和少量 anchors。
- `reply_options`、`WorldEvent.payload`、source ids、timestamps、rule id、blocked/revealable fact ids、`must_not_claim`、safe fact source refs、aliases、claim patterns 等审计/回放字段不进真实请求。
- soft compression 触发后，`AgentLoop` 会清空 `recent_events` 和 `memory_candidates`，把 `memory_snapshots[].content` 裁成 96 字符短摘要，并移除 source ids / timestamps 后重建 provider contract。
- `create_runtime(...)` 在未显式传入 `token_budget_profile` 时，会从 `AgentGateway.provider_name` 和 `AgentGateway.model_name` 自动解析 provider/model profile。
- `ProviderModelTokenEstimator` 可按 provider/model 路由外部 tokenizer；默认仍是保守字符/字节估算器，trace 会记录 `token_estimator_method`。

## 当前量化

沈照夜 reconstruction turn：玩家检查 `wine_table`、`study_lock`、`tape_recorder`、`burned_letter`、`medicine_box`、`breaker_box` 后，对 `shen_zhaoye` 询问 `cut_power_trace`。

- full contract: 40,843 bytes
- agent_context: 29,916 bytes
- provider payload: 11,129 bytes
- provider/full ratio: 27.25%

provider payload 当前计数：

- player_knowledge: 6
- memories: 8
- safe_facts: 5
- disclosure_limits: 6
- npc_skills: 1
- private_context: absent
- self_knowledge / fact_awareness / disclosure_strategies: 0
- memory content key: absent
- recent_events / context_layers / portrait_summary: absent

## 剩余风险

当前已经切断完整 memory content 进入 provider，但 compact summary 仍来自 memory content 的确定性截断，不是语义级摘要器。下一步如果要继续压 token，应做 `AgentMemorySnapshot -> ProviderMemoryProjection` 的显式 authoring schema，例如 `safe_summary`、`allowed_use`、`uncertainty`、`evidence_refs`，并给 case memory 内容加 lint，禁止把过宽真相写进单条 memory。

生产成本预测仍取决于运行环境是否提供真实 provider tokenizer。代码已支持注入 provider/model tokenizer；如果未注入，预算仍是保守估算，不应把它当成账单级精确值。

## 验证

- `py -3.12 -m pytest tests\test_llm_provider_payload.py tests\test_llm_budgeting.py tests\test_context_budget_safety.py tests\test_provider_token_budget.py -q`
- `py -3.12 -m pytest tests\test_llm_budgeting.py tests\test_context_budget_safety.py tests\test_provider_token_budget.py tests\test_llm_provider_payload.py tests\test_memory_db_retrieval.py tests\test_memory_retrieval_quality.py tests\test_memory_retrieval_matrix.py tests\test_agent_context_recent_events.py tests\test_agent_runtime_mvp.py tests\test_agent_runtime_remaining_phases.py tests\test_mist_clock_manor_memory_boundaries.py tests\test_npc_skill_memory_policy.py -q`
- `py -3.12 -m ruff check app\agents\provider_payload.py app\agents\loop.py app\agents\gateway.py app\agents\real_llm_agent.py app\runtime\service.py tests\test_llm_provider_payload.py tests\test_llm_budgeting.py tests\test_provider_token_budget.py tests\test_context_budget_safety.py`
