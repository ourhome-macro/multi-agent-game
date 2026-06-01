# LLM Agent 合同

运行时默认使用 `MockAgent`。LLM Agent 合同定义了 `LLMAgentStub` 和默认禁用的真实 LLM 适配器共同使用的安全输入/输出协议。

## 目标

合同允许未来的 LLM Agent 读取与其他 Agent 相同的受控运行时视图，包括目标 NPC 专属的 inner context，同时保持这些边界：

- 不直接修改世界状态
- 不直接推进剧情阶段
- 不把 private 原文输出给玩家
- 不把禁说事实原文或 blocked terms 输出给玩家
- 每个 `AgentIntent` 都必须经过 Narrative Director 检查
- 每个 `proposed_actions` 都必须经过 Rule Engine 检查

## 输入

合同输入是 `LLMAgentContractInput`：

```python
class LLMAgentContractInput(BaseModel):
    agent_context: AgentContext
    disclosure_constraints: list[LLMDisclosureConstraint]
    required_output_schema: Literal["AgentIntent"] = "AgentIntent"
```

`agent_context` 包含：

- 当前 `PlayerAction`
- 目标 NPC 公开画像
- 目标 NPC 专属 `CharacterInnerContext`
- 目标 NPC 专属 `inner_portraits`
- `memory_snapshots`
- `relationship_to_player`
- 玩家已知
- 近期事件
- blocked/revealable forbidden fact ids
- 行为压力和敏感度元数据

它不得包含原始 `CasePackage`、原始 `SessionState`、其他 NPC 的 private 数据、其他 NPC 的 impressions、线索 `truth_status`、禁说事实原文、blocked terms 或 solution claims。

## 披露约束

`LLMDisclosureConstraint` 来自目标 NPC 的 self-knowledge items 和 blocked forbidden fact ids：

```python
class LLMDisclosureConstraint(BaseModel):
    item_id: str
    item_kind: Literal["goal", "secret", "knowledge", "forbidden_fact", "world_info"]
    allowed_modes: list[DisclosureMode]
    forbidden_modes: list[DisclosureMode]
    direct_reveal_allowed: bool
    direct_quote_allowed: bool
    related_clue_ids: list[str]
    related_world_info_ids: list[str]
    rhetoric_tactics: list[RhetoricTactic]
    must_not_claim: list[str]
    safe_fact_refs: list[str]
    blocked: bool
```

这些约束控制表达，不控制认知。目标 NPC 可以知道自己的 private 数据，但 LLM 必须遵守允许的披露模式。

`allowed_modes` 是当前 `AgentContext` 下的有效模式，不只是角色卡默认值。运行时可根据目标 NPC 对玩家的私有画像收窄或放宽：

- 威胁或危险话题：收窄到 `deny` / `deflect`
- 结盟倾向：可允许 `hint`
- 玩家有相关证据：可允许 `partial`

该投影永远不会授予 `full` 披露，也不会允许直接引用 private 原文。

`world_info` 级约束来自 `FactDisclosureStrategy`。它是 LLM 必须遵守的事实披露边界，不是提示建议：

- `allowed_modes`：当前最多可以如何表达。
- `forbidden_modes`：当前明确禁止哪些披露模式。
- `rhetoric_tactics`：允许采用的话术类型。
- `must_not_claim`：不得直接宣称的事实声明。
- `safe_fact_refs`：允许围绕其表达的安全证据引用。

## 输出

要求输出严格匹配 `AgentIntent` 的 JSON：

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

允许的 proposed action 类型仍受运行时模型限制。LLM 合同比通用 `AgentIntent` 更严格：它拒绝直接提出 `narrative.phase.change`。剧情推进属于 `RuleTriggerSystem`。

当 `validate_llm_agent_output` 收到来源 `LLMAgentContractInput` 时，还会拒绝输出中逐字引用目标 private 文本的情况，除非对应 self-knowledge item 的 `DisclosurePolicy.direct_quote_allowed=true`。校验错误不会包含 private 文本。

同一校验器还会拒绝逐字引用目标 `inner_portraits` 文本，例如 `personality_impression`、`perceived_motive` 或 `trust_boundary`。LLM 可以用画像选择更安全的意图，但不能把私有画像原文发布出去。

## 披露声明

`disclosure_claims` 是 LLM 对自己输出内容的结构化事实披露声明：

```python
class DisclosureClaim(BaseModel):
    world_info_id: str
    mode: DisclosureMode
    tactic: RhetoricTactic | None
    source_refs: list[str]
    claim_refs: list[str]
```

语义：

- `world_info_id`：这句话触碰了哪个事实锚点。
- `mode`：本次表达属于 `deny`、`deflect`、`hint`、`partial` 或 `full` 中哪一级。
- `tactic`：使用的话术策略，例如转移重点、反问、邻近真实或降低确定性。
- `source_refs`：本次表达依赖的安全证据引用。
- `claim_refs`：本次声明触碰到的结构化禁说声明引用。

`validate_llm_agent_output` 会在进入 Director 前先做合同校验：

- 没有 `world_info` 约束的声明会被拒绝。
- `mode=full` 会被拒绝。
- `mode` 不在 `allowed_modes` 会被拒绝。
- `mode` 出现在 `forbidden_modes` 会被拒绝。
- `claim_refs` 命中 `must_not_claim` 会被拒绝。

随后 `NarrativeDirector` 会再次审计最终文本。`disclosure_claims` 只是 Agent 自报，不是授权来源。Director 会用 `WorldInfo.title`、`WorldInfo.aliases`、`WorldInfo.claim_patterns` 和禁说词映射独立检测 `speech` 实际触碰了哪些事实。

Director 会阻止这些情况：

- `speech` 触碰某个 `WorldInfo`，但没有对应 `disclosure_claim`。
- claim 声明 `hint`、`deny` 或 `deflect`，但 `speech` 实际是直接事实表达。
- claim 声明事实 A，但 `speech` 实际触碰事实 B。
- claim 合法，但 `speech` 命中 forbidden term、`must_not_claim` 或 `full` 披露边界。

因此 LLM 不能通过把 `disclosure_claims.mode` 写成 `hint`，同时在 `speech` 中直接揭露事实来绕过规则。两者不一致时，以 Director block 为准。

## Stub

`LLMAgentStub` 会构造 `LLMAgentContractInput`，输出确定性 JSON payload，并将其校验回 `AgentIntent`。

Stub 不调用外部模型，不修改 `SessionState`，也不泄露目标 private 文本。

## 真实适配器 v0

`OpenAILLMAgent` 已存在，但默认禁用。只有环境变量选择时才启用：

```text
LLM_BACKEND=real
OPENAI_API_KEY=...
```

可选：

```text
OPENAI_MODEL=...
OPENAI_BASE_URL=https://api.xiaomimimo.com/v1
```

如果设置了 `LLM_BACKEND=real` 但没有 `OPENAI_API_KEY`，`AgentGateway` 仍保持 `MockAgent`。因此 CI、本地测试和完整场景快照默认继续使用 mock。

`OPENAI_BASE_URL` 用于 OpenAI-compatible 服务。运行时会优先拼接 `/responses`，例如 `https://api.xiaomimimo.com/v1` 会先请求 `https://api.xiaomimimo.com/v1/responses`。如果兼容服务明确不支持 Responses API，适配器会降级到 `/chat/completions`。`LLM_BASE_URL` 是同义兜底配置；优先级低于 `OPENAI_BASE_URL`。本轮真实 Shadow Eval 对小米 API 使用 `OPENAI_MODEL=mimo-v2.5` 验证通过。

适配器流程：

```text
AgentContext
  -> build_llm_agent_input
  -> OpenAI Responses API strict JSON request
  -> optional OpenAI-compatible chat completions fallback
  -> parse model JSON
  -> validate_llm_agent_output(contract_input)
  -> AgentIntent or safe fallback
```

真实适配器的严格 JSON schema 只允许这些 proposed action：

- `clue.discover`
- `relationship.change`

它故意不允许 `narrative.phase.change`。Python 校验器也会再次拒绝阶段变化，作为第二道防线。

所有适配器失败都会返回无 `proposed_actions`、无 `memory_refs` 的安全拒答。失败包括：

- 直接构造适配器时缺少 API key
- HTTP 或传输错误
- 响应 JSON 非法
- schema 校验失败
- private 原文回显
- 披露声明越过 `LLMDisclosureConstraint`
- 披露声明与最终 speech 的事实触碰不一致
- 尝试推进剧情阶段

适配器永远不写 `WorldEvent`，不修改 `SessionState`，不直接调用 Rule Engine，也不绕过 Narrative Director。

## 运行时审查链路

```text
AgentContext + CharacterInnerContext
  -> build_llm_agent_input
  -> LLM 或 LLMAgentStub 输出 JSON
  -> validate_llm_agent_output
  -> AgentIntent
  -> NarrativeDirector.validate
  -> RuleEngine.apply_agent_intent
  -> 只有被接受的运行时变化才写 WorldEvent
```

`accuse` 保持在 Agent 路径之外。它不调用 `AgentGateway`、真实 LLM 或 `LLMAgentStub`。

## Shadow Eval 合同

LLM Shadow Eval v0 使用同一个 `AgentContext -> AgentIntent -> NarrativeDirector.validate` 合同，但它是只读评测链路：

```text
standard_path state
  -> copied SessionState
  -> build_agent_context
  -> LLMAgentStub 或显式真实 LLM
  -> AgentIntent
  -> NarrativeDirector.validate
  -> llm_shadow_report.json / llm_shadow_report.md
```

Shadow Eval 不执行 Rule Engine intent 应用，不写 `WorldEvent`，不修改 `SessionState`。它默认使用 `LLMAgentStub`；真实 LLM 需要同时设置：

```text
LLM_SHADOW_EVAL=1
LLM_BACKEND=real
OPENAI_API_KEY=...
```

没有 API key 时，Shadow Eval 记录该 step 为 skipped，不调用真实 API，也不让普通测试失败。

即使 Shadow Eval 进程设置了 `LLM_BACKEND=real`，标准路径推进也固定使用 `MockAgent`。真实 LLM 只生成候选 `AgentIntent`，不会接管正式 scenario runtime。

报告只保存结构化摘要、`disclosure_claims` 摘要和 Director 审计结果。候选 speech 和玩家自由文本不公开写入报告，避免在评测产物中泄露 private 原文、forbidden facts、blocked terms 或 solution claims。`--all` 会额外写 `doc/evaluations/llm_shadow/summary.json` 和 `summary.md`。

## 测试要求

合同必须保持这些不变量：

- `LLMAgentContractInput` 包含目标 NPC 自己的 `inner_context`
- 包含目标 NPC 自己的 `inner_portraits`
- 排除其他 NPC 的 private 数据和 impressions
- `LLMAgentStub` 返回合法 `AgentIntent`
- `OpenAILLMAgent` 默认禁用并由环境变量控制
- 真实适配器失败会回退到安全 `AgentIntent`
- LLM 输出剧情阶段变化会在 Rule Engine 前被拒绝
- LLM 输出 private 原文会在公开输出前被拒绝
- StateSummary、WorldEvent payload、snapshots 和 player journey Markdown 不暴露原始 private 数据
- 完整场景 JSON 快照和 player journey Markdown 保持稳定
