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
    item_kind: Literal["goal", "secret", "knowledge", "forbidden_fact"]
    allowed_modes: list[DisclosureMode]
    direct_reveal_allowed: bool
    direct_quote_allowed: bool
    related_clue_ids: list[str]
    related_world_info_ids: list[str]
    blocked: bool
```

这些约束控制表达，不控制认知。目标 NPC 可以知道自己的 private 数据，但 LLM 必须遵守允许的披露模式。

`allowed_modes` 是当前 `AgentContext` 下的有效模式，不只是角色卡默认值。运行时可根据目标 NPC 对玩家的私有画像收窄或放宽：

- 威胁或危险话题：收窄到 `deny` / `deflect`
- 结盟倾向：可允许 `hint`
- 玩家有相关证据：可允许 `partial`

该投影永远不会授予 `full` 披露，也不会允许直接引用 private 原文。

## 输出

要求输出严格匹配 `AgentIntent` 的 JSON：

```json
{
  "speech": "自然语言回复",
  "intent": "answer | conceal | lie | refuse | probe | panic",
  "emotional_shift": {},
  "proposed_actions": [],
  "memory_refs": []
}
```

允许的 proposed action 类型仍受运行时模型限制。LLM 合同比通用 `AgentIntent` 更严格：它拒绝直接提出 `narrative.phase.change`。剧情推进属于 `RuleTriggerSystem`。

当 `validate_llm_agent_output` 收到来源 `LLMAgentContractInput` 时，还会拒绝输出中逐字引用目标 private 文本的情况，除非对应 self-knowledge item 的 `DisclosurePolicy.direct_quote_allowed=true`。校验错误不会包含 private 文本。

同一校验器还会拒绝逐字引用目标 `inner_portraits` 文本，例如 `personality_impression`、`perceived_motive` 或 `trust_boundary`。LLM 可以用画像选择更安全的意图，但不能把私有画像原文发布出去。

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
```

如果设置了 `LLM_BACKEND=real` 但没有 `OPENAI_API_KEY`，`AgentGateway` 仍保持 `MockAgent`。因此 CI、本地测试和完整场景快照默认继续使用 mock。

适配器流程：

```text
AgentContext
  -> build_llm_agent_input
  -> OpenAI Responses API strict JSON request
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
