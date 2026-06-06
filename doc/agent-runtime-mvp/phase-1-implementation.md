# 第一阶段实现记录：AgentLoop + 最小 PromptBuilder + Terminal REPL

## 本次完成范围

已完成第一阶段验收目标：

- 显式新增 `AgentLoop`，玩家触发式 NPC 回合不再只是直接调用 `AgentGateway.generate`。
- 新增最小 `PromptBuilder`，真实 LLM prompt 后续不应继续散落在适配器里。
- 新增 `PromptInjectionGuard`，对玩家文本做输入侧风险标记。
- 新增 `RuntimeTracer`，同时输出机器可读 JSONL 和人工可读 `.log`。
- 新增 Terminal REPL 入口与命令解析。
- `talk / ask_about / present_clue / accuse` 进入 AgentLoop。
- `inspect` 明确保持环境交互，只走 Rule Engine，不走 NPC AgentLoop。

## 关键实现

新增模块：

- `app/agents/loop.py`
  - `AgentLoop.run_turn(...)`
  - `AgentTurnResult`
  - 负责构造 `AgentContext`、调用 `PromptBuilder`、运行安全检查、调用 `AgentGateway`、校验 `AgentIntent`、创建 trace draft。

- `app/agents/prompt_builder.py`
  - `PromptBuilder.build(...)`
  - `build_agent_prompt(...)`
  - `build_contract_instruction(...)`
  - `build_safety_instruction(...)`
  - 只使用 `AgentContext` 的安全投影，不读取完整案件 YAML 原文。

- `app/runtime/security.py`
  - `PromptInjectionGuard`
  - 输出 `prompt_injection.*` 安全旗标。

- `app/runtime/tracing.py`
  - `RuntimeTracer`
  - `RuntimeTraceDraft`
  - 输出 `runtime_trace.jsonl` 与 `runtime_trace.log`。

- `scripts/run_terminal_mvp.py`
  - 支持 `inspect / talk / ask / present / accuse / state / events / memory / quit`。
  - 终端 `ask <npc> clue|character|scene <id>` 会映射为内部 `PlayerAction.type=ask_about`。

修改模块：

- `app/runtime/service.py`
  - `ActionService` 改为依赖 `AgentLoop`。
  - `RuntimeContainer` 暴露 `agent_loop`。
  - `create_runtime(...)` 新增可选 `runtime_tracer` 参数。
  - `talk / ask_about / present_clue` 继续保持原事件顺序。
  - `accuse` 进入 AgentLoop 做感知、prompt、安全检查和 trace，但不新增 NPC 回复事件，不让 LLM 判断指控结果。

- `app/domain/models.py`
  - 新增 `PromptBundle`。

## Trace 约束

普通 JSONL trace 包含：

- `schema_version`
- `trace_id`
- `timestamp`
- `turn_id`
- `action_type`
- `target_agent_id`
- `agent_backend`
- `duration_ms`
- `context_tokens_estimated`
- `memory_ids_used`
- `tool_calls`
- `security_flags`
- `intent_type`
- `director_allowed`
- `director_reason_category`
- `rule_rejections`
- `new_event_types`
- `phase_before`
- `phase_after`
- `status`
- `error_category`
- `player_text_hash`
- `player_text_length`
- `claim_hash`
- `evidence_ids`

禁止进入普通 trace：

- 玩家自由文本全文
- raw system prompt
- raw LLM prompt
- raw provider response
- private 原文
- forbidden fact 原文
- solution claims
- 工具完整参数
- 工具完整返回值

`.log` 只从 JSONL 安全字段渲染，不额外读取敏感数据。

## 行为边界

`inspect`：

- 不走 NPC AgentLoop。
- 不写 Agent trace。
- 仍由 Rule Engine 解锁线索并派生记忆。

`talk / ask_about / present_clue`：

- 走 AgentLoop。
- 经过 PromptBuilder、安全检查、AgentGateway、AgentIntentValidator、Director、RuleEngine。
- 保持原有事件链兼容。

`accuse`：

- 走 AgentLoop 进行 NPC 回合观测和 trace。
- 不调用 LLM 判断指控是否正确。
- 不新增 `npc.replied`。
- 正式裁决仍由 `RuleEngine.apply_accuse` 和 `solution_claims.yaml` 决定。

## 测试

新增 `tests/test_agent_runtime_mvp.py`，覆盖：

- NPC 动作进入 AgentLoop，`inspect` 不进入。
- JSONL 和 `.log` 双轨 trace 输出。
- trace 不泄露玩家原文、private 原文、forbidden fact 原文。
- `inspect` 不创建 Agent trace。
- `PromptBuilder` 使用安全上下文投影。
- REPL `ask` 命令映射为 `ask_about`。

验证结果：

```powershell
py -3.12 -m pytest
py -3.12 -m ruff check .
```

当前结果：

- `172 passed`
- `ruff check` 通过

## 运行方式

终端 MVP：

```powershell
py -3.12 scripts\run_terminal_mvp.py --case-id fake_case_001
```

默认 trace：

```text
logs/runtime_trace.jsonl
logs/runtime_trace.log
```

关闭 trace：

```powershell
py -3.12 scripts\run_terminal_mvp.py --no-trace
```

## 未进入第一阶段的内容

以下内容仍属于后续阶段，不在本次实现范围内：

- 完整 prompt 文件化。
- Skill / Superpowers 文件落地。
- MemoryRetriever 独立模块。
- ContextBudgetManager 和 80% 压缩。
- ToolRuntime 与真实 function calling。
- 多 Agent Orchestrator。
- 数据库持久化。

