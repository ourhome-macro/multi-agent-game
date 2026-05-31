# 角色内心上下文

角色 private 数据表示角色自己的非公开信息。它不是对角色自己隐藏。

目标 NPC 永远知道自己的 `private.goals`、`private.secrets` 和 `private.knowledge`。运行时派生的 private impressions 也属于角色认知。运行时限制的是“对外披露”和“权威状态写入”，不是 NPC 是否能访问自己的视角。

## private 语义

`private.goals` 是内部动机。它会影响行为、偏好、回避、压力反应和决策风格。默认不应逐字告诉玩家或其他 NPC。

`private.secrets` 是 NPC 有理由隐藏的事实或主张。默认非公开。只有当剧情阶段、信任、玩家证据、交互压力和 Narrative Director 校验都允许时，才可能部分表达。

`private.knowledge` 是 NPC 自己视角中知道的内容。它不同于 `forbidden_facts`，也不是绝对禁言。它不能自动暴露给玩家、其他 NPC、公开摘要或玩家旅程。

`inner_portraits` 是 NPC 如何看待别人。v0 只保存 NPC -> player 画像。它是主观、私有、运行时派生的，不是角色卡真相。

## 当前运行时状态

`CasePackage` 中保存角色卡 private，但原始 private 数据不会复制到 `StateSummary`、`WorldEvent` 或 `player_journey.md`。

这是刻意设计的安全边界，不代表 NPC 不知道自己的 private 数据。

`AgentContext.inner_context` 会为目标 NPC 构造受控自我视图，用于 `talk`、`ask_about` 和 `present_clue`。`inspect` 和 `accuse` 不需要它；`accuse` 也不会调用 `AgentGateway`。

## CharacterInnerContext v0

Agent 生成 NPC 回复时使用两种角色视图：

- `AgentCharacterView`：公开角色卡视图，可用于 AgentContext 和公开摘要。
- `CharacterInnerContext`：目标 NPC 专属自我视图，只能用于该 NPC 的生成步骤，不能通过公开 API 返回。

当前结构：

```python
class CharacterInnerContext(BaseModel):
    character_id: str
    inner_goals: list[SelfKnowledgeItem]
    inner_secrets: list[SelfKnowledgeItem]
    inner_knowledge: list[SelfKnowledgeItem]
    inner_portraits: list[CharacterImpression]
```

`CharacterInnerContext` 不是权威状态。它是运行时构造的输入视图，不能写事实、线索、关系、记忆或剧情阶段。任何对外状态变化仍必须通过 `AgentIntent` 提议，并由 Rule Engine 接受。

## SelfKnowledgeItem

`SelfKnowledgeItem` 是目标 NPC 的受控自我知识项，只包含目标角色自己的 selected private 数据：

```python
class SelfKnowledgeItem(BaseModel):
    id: str
    kind: Literal["goal", "secret", "knowledge"]
    summary: str
    priority: Literal["low", "medium", "high"]
    related_clue_ids: list[str]
    related_world_info_ids: list[str]
    tags: list[str]
    disclosure_policy: DisclosurePolicy
    source: Literal["character_card"]
```

生产案件包应使用稳定作者 ID。Loader 仍会把旧字符串条目归一化为 `goal_001`、`secret_001`、`knowledge_001`。

`related_clue_ids` 保留给旧证据触发逻辑；`related_world_info_ids` 是推荐的新事实锚点引用。

## DisclosurePolicy

`DisclosurePolicy` 控制表达，不控制认知。它决定某个自我知识项是否可以对外使用，以及使用到什么粒度。

安全默认值是 `allowed_modes=["deny", "deflect", "hint"]`，并且不允许直接引用原文。

披露策略需要在生成前后共同约束：

- 生成前：只构造目标 NPC 当前动作可用的 inner items 和 disclosure modes。
- 生成后：Narrative Director 校验输出没有越过允许披露范围、没有透露锁定禁说事实、没有违背案件锚点。

## 画像感知披露

`CharacterInnerContext` 会把作者配置的 `DisclosurePolicy` 与目标 NPC 自己的 `inner_portraits` 组合，得到有效披露策略。

该策略只是 Agent 输入投影，不修改案件包，也不写 `WorldEvent`。

当前规则保守：

- 玩家威胁高：收窄到 `deny` / `deflect`
- 触发危险话题：收窄到 `deny` / `deflect`
- 结盟潜力高：可增加 `hint`
- 玩家有相关证据：对匹配 clue 或 WorldInfo 可增加 `partial`
- 不授予 `full`、直接揭露或直接引用 private 原文

## 运行流程

```text
PlayerAction(talk | ask_about | present_clue)
  -> 构造公开 AgentContext
  -> 构造目标 NPC 专属 CharacterInnerContext
  -> AgentGateway.generate(context)
  -> AgentIntent
  -> NarrativeDirector 校验对外发言
  -> RuleEngine 校验 proposed_actions
  -> WorldEvent 只写入被接受的公开/运行时事实
```

只有目标 NPC 能收到自己的 inner context。其他 NPC 不会收到该数据，除非信息已经通过允许的对外发言、记忆或事件外部化。

## MockAgent fallback

`mock_dialogues.yaml` 中配置的 reply 仍优先。没有匹配 reply 时才使用 inner context fallback。

当前 fallback 很小：

- 高优先级且带 `avoid_suspicion` tag 的 goal 会让 fallback 偏向 `conceal`
- 被询问或展示的 clue 命中 `inner_secrets.related_clue_ids` 时，fallback 偏向 `conceal`
- private item 的 `related_world_info_ids` 可与玩家已知 WorldInfo 对齐，用于相关证据判断
- 如果 `direct_reveal_allowed=false`，fallback 不得直接引用 secret summary
- 高威胁 `inner_portraits` 会让回复更谨慎，但不引用画像文本

## 非泄漏要求

原始 `private` 数据不得出现在：

- `StateSummary`
- `player_journey.md`
- 公开 API 响应
- `WorldEvent` payload
- 其他 NPC 的上下文
- 记忆快照，除非它来自允许的公开事件

`character_impression.updated` payload 是用于 replay 的私有运行时事件。玩家旅程 Markdown 可以说明“私有画像更新了”，但不能打印画像正文。

`AgentContext.inner_context` 可以包含目标 NPC 自己的 self summaries，但不能包含其他 NPC 的 private 数据，也不能序列化进公开运行时产物。

NPC 被允许透露某事时，事件日志应记录允许的对外表达，而不是原始 private 配置项。

## 与 Rule Engine 的边界

Private 数据可以影响 `AgentIntent.speech`、`intent`、`emotional_shift` 和 `proposed_actions`。它不能直接修改世界状态。

Rule Engine 仍是以下状态的权威：

- 线索发现
- 关系变化
- 玩家已知
- 记忆候选和快照
- 私有角色画像派生
- 剧情阶段变化
- 指控评估

Narrative Director 仍负责判断对外发言是否安全。
