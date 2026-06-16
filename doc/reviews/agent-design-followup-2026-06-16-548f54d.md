# Agent 设计增量复查：提交 548f54d 后续修复

日期：2026-06-16

复查对象：`548f54d eat: 新增 mist_clock_manor 中关于磁带放入后书房门锁异常偏差回溯的新场景`，以及本轮针对 Agent 设计缺口的三个并行修复。

## 结论

本轮已经补上之前复查指出的三个 P0 缺口：

1. 真实 LLM 生成链路现在接收并复用同一份 `LLMAgentContractInput`。
2. `turn_plan.py` 已去掉 Python 3.12-only 泛型函数语法，保持项目声明的 Python 3.11 语法边界。
3. `mist_clock_manor` 已落地 `npc_skills.yaml`，主案件不再只靠 fake case 验证 NPC Skill 能力。

当前 Agent 链路已经从“事后可校验”推进到“同一份合同驱动生成、校验和 fallback”。这解决了真实 LLM 请求 schema 与后置 validator 不一致的根因：模型生成前看到的动态 JSON schema、repair prompt 和 Python 校验现在都来自同一个合同对象。

但这仍不等于 Agent 体系完全闭环。剩余高价值工作主要集中在 skill memory policy 是否真正约束检索、记忆污染治理、context budget 的安全分层，以及 shadow eval gate 是否接入 CI。

## 本轮已完成修复

### 1. 真实 LLM 合同贯穿

接口现在支持：

```python
generate(
    context: AgentContext,
    *,
    contract_input: LLMAgentContractInput | None = None,
) -> AgentIntent
```

关键变化：

- `AgentLoop.run_turn(...)` 在本轮只构造一次 `LLMAgentContractInput`。
- `AgentGateway.generate(...)` 将该合同传给支持 `contract_input` 的后端。
- `OpenAILLMAgent.generate(...)` 和 `generate_strict(...)` 使用外部传入的合同构造真实 LLM 请求 schema。
- schema repair、JSON repair、fallback intent 和 `validate_llm_agent_output(...)` 复用同一份合同。
- `LLMAgentStub` 复用传入合同；`MockAgent` 保持兼容但不依赖合同。

这意味着 prompt injection 降级、selected NPC skill、allowed intents、allowed tactics、proposed action 类型和 relationship delta 上限会同时作用于真实 LLM 生成前 schema 与生成后校验。

### 2. Python 3.11 语法边界

`app/agents/turn_plan.py` 原本使用：

```python
def _ordered_enum_values[T: StrEnum](
```

这是 Python 3.12 PEP 695 语法，与 `pyproject.toml` 的 `py311` 目标冲突。现在已改为传统 `TypeVar(bound=StrEnum)` 写法。

新增 `tests/test_python311_compatibility.py`，用 `ast.parse(..., feature_version=(3, 11))` 对 `turn_plan.py` 做语法边界回归。当前机器未安装 Python 3.11，只有 3.12 和 3.10，因此该测试是最小可执行的 3.11 语法兼容证明。

默认 `python` 仍是 3.10，不是项目目标版本；不再为 3.10 兼容 `enum.StrEnum`。

### 3. 主案件 NPC Skill 资产

新增 `cases/mist_clock_manor/npc_skills.yaml`，首批覆盖高风险生产交互：

- 江雁回 x 门锁延迟 / 空胶囊 / 药物替换。
- 祁宴 x 录音带 / 剪辑痕迹 / 旧录音。
- 林栖迟 x 红酒 / 安眠药来源。
- 沈照夜 x 停电 / 备用计时器 / 书房门锁 / 旧案材料。

同步在 `world_info.yaml` 中补充 `claim_graph.safe_fragments`，让 skill 引用的是可验证的安全事实碎片，而不是直接引用世界真相正文。

新增 `tests/test_mist_clock_manor_npc_skills.py`，验证：

- 主案件 skill 资产能被 `CaseLoader` 加载。
- 关键高风险行动能选中预期 skill。
- `NpcSkillProjection` 只暴露安全边界字段，不泄露 world info 正文、clue 正文、safe fragment summary 或角色 private summary。

### 4. Skill 事件审计降噪

`ActionService._record_npc_skill_events(...)` 保持一个清晰边界：

- 有 selected skill 时，只记录 `npc_skill.selected`。
- 没有 selected skill 时，记录非 `owner_mismatch` 的 `npc_skill.rejected`。

这样既保留“为什么没有技能可用”的诊断事件，又避免主案件中其他 NPC 或同 NPC 其他技能的 `trigger_mismatch` 污染稳定场景事件序列。

### 5. Shadow Eval Gate

`app/evaluations/llm_shadow_eval.py` 新增机器可判定的 gate：

- `--gate`
- `--gate-profile standard|safety|redteam|drift`

gate 失败时 CLI 以退出码 `2` 结束。文档已更新到 `doc/evaluations/llm-shadow-eval-v0.md`。这项不是最初三个 P0 之一，但它把真实 LLM 评测从“人工读报告”推进到“可接入 CI 的发布门槛”。

## 已验证结果

使用 Python 3.12：

```powershell
py -3.12 -m ruff check app/agents/gateway.py app/agents/llm_stub.py app/agents/loop.py app/agents/mock_agent.py app/agents/protocol.py app/agents/real_llm_agent.py app/agents/turn_plan.py app/evaluations/llm_shadow_eval.py app/runtime/service.py tests/test_runtime.py tests/test_llm_shadow_eval.py tests/test_mist_clock_manor_npc_skills.py tests/test_python311_compatibility.py
```

结果：通过。

```powershell
py -3.12 -m pytest tests/test_python311_compatibility.py tests/test_agent_turn_plan_skill_contract.py tests/test_agent_turn_plan_security.py tests/test_npc_skills.py tests/test_real_llm_observability.py -q
```

结果：25 passed。

```powershell
py -3.12 -m pytest tests/test_runtime.py -k "real_llm_agent or llm_agent_stub or agent_gateway_selects_backend or prompt_injection_contract" -q
```

结果：20 passed, 106 deselected。

```powershell
py -3.12 -m pytest tests/test_npc_skill_events.py tests/test_mist_clock_manor_npc_skills.py tests/test_mist_clock_manor_scenario.py -q
```

结果：11 passed。

```powershell
py -3.12 -m pytest tests/test_llm_shadow_eval.py -q
```

结果：24 passed。

```powershell
py -3.12 -m pytest tests/test_case_validation_evidence_graph.py tests/test_scenario_evaluation_harness.py -q
```

结果：8 passed。

`git diff --check` 通过；Git 仅提示工作区文件未来可能被转换为 CRLF。

## 仍未解决的问题

### P1：NPC skill memory policy 仍未合并进最终检索计划

`NpcSkillMemoryPolicy` 已经有 `include_types/include_scopes/include_layers/topic_tags/max_items`，`NpcSkillProjection` 也有 `memory_plan_id`，但当前检索仍主要由 `RetrievalPlanner` 产出的 `MemoryRetrievalPlan` 决定。

最优解不是把 memory policy 当 prompt 文案，而是让 `AgentTurnPlan` 生成 final memory plan：

- memory projection skill 负责动作级默认范围；
- NPC skill memory policy 负责角色 / 话题级收窄；
- final plan 才传给 `MemoryRetriever`；
- trace 记录 final plan 的来源和裁剪结果。

否则 behavior skill 与 memory projection 仍可能错位。

### P1：记忆污染治理仍未闭环

当前已有 `source_event_ids`、`confidence`、`belief_subject`、`non_authoritative` metadata 和检索硬过滤，但还缺少：

- `non_authoritative` 在检索和关键判断中的降权 / 禁用策略；
- 同一 `belief_subject/world_info_id/clue_id` 冲突记忆的裁决；
- belief / strategy memory 的 source event type 白名单；
- critical disclosure 和 relationship change 的强制证据锚点。

### P1：Context budget 仍不是安全核心模型

`ContextBudgetManager` 仍偏 token 工具，不是安全边界模型。后续应拆分：

- hard context：phase、facts、Director constraints、skill projection、security flags、selected memory refs；
- soft context：recent events、历史摘要、可压缩 memory 描述。

硬上下文不得被压缩、丢弃或摘要改写；软上下文才允许预算裁剪。

### P2：Shadow Eval Gate 需要进入 CI

现在 gate 已有代码和文档，但尚未看到 CI / 发布脚本调用。生产门槛应至少包含：

```powershell
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --backend real --gate
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --drift --runs 20 --backend real --gate
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --benchmark safety --gate
```

真实 LLM gate 需要显式环境变量和 API key，不能在普通单元测试里隐式触发。

## 当前工程风险排序

1. 合并 NPC skill memory policy 到 final retrieval plan。
2. 做 memory authority / conflict 污染治理。
3. 把 context budget 升级为 hard / soft context 安全分层。
4. 将 shadow eval gate 接入 CI 和发布流程。
5. 持续保持 Python 3.11 语法边界，避免重新引入 3.12-only 写法。

## 总体判断

这轮修复解决了真实 LLM 合同不贯穿、主案件无 skill 资产、Python 版本声明冲突三个硬问题。当前系统的 Agent 设计已经具备更像生产系统的骨架：LLM 负责表达和意图，合同负责生成边界，Director 负责叙事安全，Rule Engine 负责状态副作用，WorldEvent 负责审计回放。

下一步不应继续扩大 NPC 自由度，而应把 skill 的 memory policy 接入最终检索计划，并补上记忆权威与冲突治理。否则系统会在“能约束输出”之后，卡在“输入上下文本身是否可信、是否最小授权”的问题上。
