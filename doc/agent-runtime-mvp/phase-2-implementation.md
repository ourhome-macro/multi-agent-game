# 第二阶段实现记录：Prompt 文件化与 Skill/Superpowers 分层

## 本次完成范围

已完成第二阶段目标：

- 将真实 LLM system prompt 从 `real_llm_agent.py` 拆到 `app/agents/prompts/system.md`。
- `OpenAILLMAgent` 改为通过 `load_agent_system_prompt()` 读取文件化 system prompt。
- `PromptBuilder` 改为读取 prompt 文件和 skill 文件。
- 新增完整 prompt 文件集合。
- 新增 Skill / Superpowers 风格纪律文件集合。
- 保持第一阶段 Terminal REPL 可跑。
- 保持 Director / Rule Engine / EventLog 权威边界不变。

未做且本阶段禁止扩大到：

- MemoryRetriever
- ContextBudgetManager
- 向量库
- 真实 LLM tool calling
- 多 Agent Orchestrator
- 数据库持久化
- Rule Engine / Director / EventLog 重构

## Prompt 文件

新增目录：

```text
app/agents/prompts/
```

文件：

- `system.md`
- `npc_turn_policy.md`
- `output_contract.md`
- `disclosure_policy.md`
- `memory_policy.md`
- `tool_policy.md`

用途：

- `system.md`：真实 LLM system prompt。
- `npc_turn_policy.md`：NPC 单轮行为流程。
- `output_contract.md`：`AgentIntent` 输出合同。
- `disclosure_policy.md`：事实披露模式约束。
- `memory_policy.md`：记忆使用边界。
- `tool_policy.md`：工具输出和工具权限边界。

## Skill 文件

新增目录：

```text
app/agents/skills/
```

文件：

- `npc_dialogue_guard.md`
- `disclosure_discipline.md`
- `prompt_injection_defense.md`
- `memory_use_discipline.md`
- `tool_use_discipline.md`

每个 skill 均包含：

- `when_to_use`
- `iron_law`
- `allowed_behavior`
- `red_flags`
- `rationalization_prevention`
- `output_requirements`

这些 skill 当前作为 PromptBuilder 的安全纪律输入，也作为后续 adversarial 测试清单。

## PromptBuilder 变化

`app/agents/prompt_builder.py` 新增：

- `PROMPT_DIR`
- `SKILL_DIR`
- `load_agent_system_prompt()`

`PromptBuilder.build(...)` 仍返回：

- `agent_prompt`
- `contract_instruction`
- `safety_instruction`

安全投影保持不变：

- 角色卡只通过 `AgentContext.target_profile` 注入公开字段。
- 当前目标 NPC private 只以 `inner_context_summary` 的 ID 摘要形式注入。
- 不注入完整 YAML 原文。
- 不注入 solution claims。
- 不注入 forbidden fact 原文或 blocked terms。
- 不注入其他 NPC private。

## Real LLM 变化

`app/agents/real_llm_agent.py` 不再硬编码大段 system prompt。

Responses API：

```text
instructions = load_agent_system_prompt()
```

Chat Completions：

```text
messages[0].content = load_agent_system_prompt()
```

JSON schema、合同校验、Director 和 Rule Engine 链路不变。

## 测试

新增 `tests/test_agent_prompt_phase2.py`，覆盖：

- prompt 文件存在且内容非空。
- skill 文件存在且包含必需 section。
- PromptBuilder 读取文件化 contract 和 skill。
- PromptBuilder 不泄露 private、forbidden fact 原文、blocked terms、solution claim id。
- Real LLM 使用文件化 system prompt。
- `real_llm_agent.py` 不再硬编码原长 system prompt 关键句。
- Terminal MVP 固定命令序列仍能跑通，并生成 3 条 Agent trace。

验证结果：

```powershell
py -3.12 -m pytest tests\test_agent_prompt_phase2.py
py -3.12 -m pytest tests\test_agent_runtime_mvp.py
py -3.12 -m pytest
py -3.12 -m ruff check .
```

当前结果：

- `tests/test_agent_prompt_phase2.py`：5 passed
- `tests/test_agent_runtime_mvp.py`：5 passed
- 全量 pytest：177 passed
- ruff：All checks passed

