# Token 成本优化方案

更新日期：2026-06-26

## 结论

当前 token 成本主要不是“召回 memory 太多”，而是 provider payload 直接携带了过宽的运行时对象。`AgentContext`、`AgentMemorySnapshot`、recent events、inner context、safe fragments 和输出 schema 都混在真实 LLM 输入里，导致 reconstruction turn 成本偏高。

正确方向是新增真实 LLM 专用 compact DTO，同时保留本地完整 `LLMAgentContractInput` 做校验、trace 和审计。

## 实测样本

样本：`mist_clock_manor` reconstruction 阶段，沈照夜 talk。

估算结果：

- full `LLMAgentContractInput`：约 39k chars，约 13.6k tokens。
- `agent_context`：约 30k chars，约 10.5k tokens。
- `memory_snapshots`：约 10.8k chars，约 3.6k tokens。
- `recent_events`：约 5.2k chars，约 1.7k tokens。
- `inner_context`：约 4.3k chars，约 1.5k tokens。
- `director_safe_fragments`：约 2.5k chars，约 0.9k tokens。
- `player_knowledge`：约 2.3k chars，约 1.0k tokens。
- `reply_options`：约 2.1k chars，约 0.8k tokens。

## 根因

`LLMAgentContractInput` 是很好的本地合同对象，但不是最小 provider payload。它承担了多种职责：

- 本地输出校验。
- Director 和 Rule Engine 安全边界。
- trace 解释。
- context budget 估算。
- provider 输入。

其中只有一部分字段真正需要发给模型。审计字段、replay 字段、可见性字段、source event id、完整 metadata 不应原样进入 provider。

## P0：新增 Compact Provider Payload

新增真实 LLM 发送专用结构，例如 `LLMProviderTurnPayload`：

```json
{
  "turn": {
    "case_id": "mist_clock_manor",
    "phase": "reconstruction",
    "target_id": "shen_zhaoye",
    "action": {
      "type": "talk",
      "text": "..."
    }
  },
  "npc": {
    "display_name": "...",
    "public_role": "...",
    "speech_style": "..."
  },
  "memory": [
    {
      "id": "memory.player.clue_discovered.cut_power_trace",
      "type": "episodic",
      "content": "Player discovered cut_power_trace.",
      "clue_id": "cut_power_trace",
      "case_thread_id": "shared_death_chain"
    }
  ],
  "safe_facts": [
    {
      "ref": "...",
      "summary": "...",
      "allowed_modes": ["hint", "partial"]
    }
  ],
  "output_limits": {
    "allowed_intents": ["answer", "deflect"],
    "allowed_disclosure_modes": ["hint", "partial"],
    "allowed_proposed_actions": []
  }
}
```

本地仍保留完整 `LLMAgentContractInput`：

```text
AgentLoop
  -> build full LLMAgentContractInput for validation
  -> build compact provider payload for model request
  -> provider returns AgentIntent JSON
  -> validate_llm_agent_output(payload, full_contract)
  -> NarrativeDirector.validate
```

## P1：Memory Projection

新增 `LLMMemoryProjection`，不要把完整 `AgentMemorySnapshot` 发给 provider。

保留：

- `memory_id`
- `memory_type`
- `memory_scope`
- `content`
- `clue_id`
- `world_info_id` if already safe as id
- `case_thread_id`
- `chain_node_id`
- compact topic tags

移除：

- `rule_id`
- `source_event_ids`
- `source_memory_ids`，除非作为 selected refs
- `visible_to_character_ids`
- `last_updated_event_id`
- `created_at`
- `updated_at`
- full metadata
- salience/confidence，除非用于模型解释且确有必要

## P1：移除真实 LLM 的 `reply_options`

`reply_options` 是 mock dialogue / fixture 行为，不应进入真实 provider payload。

真实模型只需要：

- 角色公开表达风格。
- 当前 action。
- 选中的 memory projection。
- Director safe fragments。
- 输出合同限制。

## P1：Recent Events 压缩为事件桩

真实 LLM 不应看到完整 `WorldEvent` payload。建议只保留：

```json
{
  "id": "...",
  "type": "player.presented_clue",
  "actor_id": "player",
  "safe_summary": "Player presented a discovered clue.",
  "selected_memory_ids": ["..."]
}
```

大部分情况下，selected memories 已经足够表达叙事上下文；recent events 应作为辅助，不应重复携带同样事实。

## P2：模型路由

低成本路径：

- `inspect`：不调用 LLM。
- action validation failed：不调用 LLM。
- affordance/state 查询：不调用 LLM。
- 无敏感事实、无 selected memory 的普通 talk：小模型或模板。

高成本路径：

- reconstruction。
- present_clue 高压力回合。
- safe fragment partial disclosure。
- Director 高风险主题。

## P2：Prompt/Schema 缓存

system prompt、输出 schema、静态公开角色卡、案件公开摘要都是稳定内容。后续如果 provider 支持 prompt caching，应按 hash 缓存；即使不支持 provider 缓存，本地 trace 也应记录 hash，而不是重复展开大段静态内容。

## 验收指标

以 reconstruction turn 为基准：

- provider input tokens 降低 40% 以上。
- 本地合同校验能力不下降。
- Director block 测试不退化。
- memory retrieval matrix 不漂移。
- trace 不记录 memory content、private 原文或 forbidden fact 文本。

## P0 落地：预算输入对齐 compact provider payload

更新日期：2026-06-26

已在 `AgentLoop` 内把预算入口从旧 `PromptBundle` 拼接文本切到真实发送链路使用的 compact provider payload JSON。完整 `LLMAgentContractInput` 仍用于本地审计、动态 schema、输出校验和回放，但不再作为默认预算对象：

```text
build AgentContext
  -> build AgentTurnPlan
  -> build full LLMAgentContractInput
  -> build LLMProviderTurnPayload
  -> budget serialized provider payload JSON
  -> optional soft compression
  -> rebuild full LLMAgentContractInput and provider payload after compression
  -> pass the same contract_input to AgentGateway.generate()
```

预算文本优先级：

1. `serialized_provider_payload`：`run_turn` 默认使用 `LLMProviderTurnPayload` 的序列化结果。
2. `LLMAgentContractInput` JSON：仅作为内部兼容兜底。
3. `PromptBundle`：仅作为旧调用兼容，不再是 `run_turn` 默认预算对象。

`AgentLoop.run_turn()` 预算调用必须保持如下形态：

```python
self._budget_prompt(
    None,
    context,
    memory_ids,
    contract_input=contract_input,
    serialized_provider_payload=serialized_payload,
)
```

验收测试点：

- 预算 estimator 捕获的第一段文本必须等于 `build_llm_provider_payload(contract_input)`。
- soft compression 后必须重建 compact payload 和 full `LLMAgentContractInput`。
- mock agent 流程仍只依赖 `AgentContext`/`contract_input`，不能强制依赖真实 provider payload。
- 本地输出校验仍使用 full `LLMAgentContractInput`，不能用 compact payload 代替安全合同。
