# 第三至第六阶段实现记录：Memory、Budget、Tools、Orchestrator、Persistence

## 本次完成范围

本次完成剩余 MVP 阶段：

- 第三阶段：`MemoryRetriever + ContextBudgetManager`
- 第四阶段：`SafetyGuard + ToolRuntime`
- 第五阶段：`AgentOrchestrator`
- 第六阶段：JSONL 事件持久化适配器

本次仍保持 MVP 边界，没有引入向量库、真实 LLM tool calling、多实例数据库事务或生产级调度器。

## 第三阶段：MemoryRetriever + ContextBudgetManager

新增：

- `app/agents/memory.py`
  - `MemoryRetriever`
  - 按目标动作、线索、subject、玩家文本关键词、salience 和 recency 检索可见记忆。
  - 只返回 `subject_id="player"` 且 `visibility="private"` 的运行时记忆快照。

- `app/runtime/budget.py`
  - `ContextBudgetManager`
  - `CompressedHistory`
  - `ContextBudgetResult`
  - `estimate_tokens(...)`

当前压缩是确定性 MVP 摘要：

- 超过 80% 阈值时标记 `compression_used=true`。
- 保留 `important_event_ids` 和 `important_memory_ids`。
- 不把摘要作为世界事实。
- replay 不依赖摘要。

`AgentLoop` 已接入：

- trace 的 `memory_ids_used` 来自 `MemoryRetriever`。
- trace 的 `context_tokens_estimated`、`context_budget_ratio`、`compression_used` 来自 `ContextBudgetManager`。

## 第四阶段：SafetyGuard + ToolRuntime

第一、二阶段已有：

- `PromptInjectionGuard`
- prompt/skill 安全纪律

本阶段新增：

- `app/agents/tools/runtime.py`
  - `ToolRuntime`
  - `ToolResult`

当前只支持受控只读工具摘要：

- `get_public_state`
- `get_known_clues`
- `get_relationship_to_player`
- `search_memory`
- `get_recent_events`
- `get_disclosure_constraints`

工具结果只暴露安全 summary：

- `tool_name`
- `status`
- `duration_ms`
- `error_category`
- `result_count`

不会返回完整参数、完整结果、private 原文、solution claims 或玩家原文。

真实 LLM tool calling 仍未启用。

## 第五阶段：多 Agent 编排

新增：

- `app/agents/orchestrator.py`
  - `AgentOrchestrator`
  - `OrchestratorResult`

当前只实现 secondary reaction MVP：

- 主 Agent 之外最多触发有限 secondary agents。
- secondary agent 使用独立 `AgentLoop` 和独立 `AgentContext`。
- secondary reaction 不写世界状态，不调用 Rule Engine。
- 上下文隔离依赖现有 `build_agent_context`，不会把主 NPC private 注入副 NPC。

## 第六阶段：持久化

新增：

- `app/runtime/persistence.py`
  - `JsonlEventStore`

能力：

- 保存 `WorldEvent` 列表到 JSONL。
- 从 JSONL 加载 `WorldEvent`。
- 可交给 `replay_events(...)` 重建关键状态。

这是 MVP 级事件持久化适配器，不是生产数据库方案。

生产阶段仍应使用 PostgreSQL、事务提交、session cache 和 optimistic lock。

## 测试

新增 `tests/test_agent_runtime_remaining_phases.py`，覆盖：

- `MemoryRetriever` 只返回相关可见记忆。
- `ContextBudgetManager` 超过 80% 阈值会压缩，并保留来源事件/记忆 id。
- `AgentLoop` trace 使用检索记忆和预算结果。
- `ToolRuntime` 只返回安全摘要，不暴露 args/result。
- `AgentOrchestrator` secondary context 不泄露 primary NPC private。
- `JsonlEventStore` 保存/加载事件后可 replay 重建状态。

验证结果：

```powershell
py -3.12 -m pytest tests\test_agent_runtime_remaining_phases.py
py -3.12 -m pytest
py -3.12 -m ruff check .
```

当前结果：

- `tests/test_agent_runtime_remaining_phases.py`：6 passed
- 全量 pytest：183 passed
- ruff：All checks passed

## 明确未做

- 未接向量库。
- 未做 LLM 摘要压缩。
- 未开放真实 LLM tool calling。
- 未做后台自主 tick。
- 未做生产数据库持久化。
- 未改 Rule Engine / Director / EventLog 权威边界。

