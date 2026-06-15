# SillyTavern Reference Review for Frontend Direction - 2026-06-15

## 结论

SillyTavern 相关指导对本项目有参考价值，但它不是本项目的架构路线图。

它适合作为前端交互、证据库体验、对话运行壳、扩展事件和工具调用体验的参考；不适合作为后端权威状态、案件规则、证据解锁和结局判定的替代方案。

本项目已经走向更生产化的结构：

```text
PlayerAction
  -> ActionService
  -> RuleEngine / NarrativeDirector / AgentLoop
  -> WorldEvent
  -> Postgres event store
  -> replayable SessionState
```

因此正确吸收方式是：

- 不学习 SillyTavern 的前端状态权威。
- 学习它的对话体验、证据资料呈现、扩展事件、快捷操作和工具调用交互。
- 保持本项目后端规则、事件流、Director、Postgres 作为真相源。

一句话：SillyTavern 适合作为产品/UI/交互参考，不适合作为本系统的架构替代方案。

## 已经实现或方向一致的部分

| SillyTavern 指导原则 | 本项目当前状态 |
| --- | --- |
| AI 只负责表现，系统负责真相 | 已实现。LLM 输出结构化 intent，真实状态变化走 `RuleEngine` 和 `WorldEvent`。 |
| 玩家行为先结构化 | 已实现。入口是 `PlayerAction`，不是自由文本直接改世界状态。 |
| 状态变化必须可回放 | 已实现。`WorldEvent`、`replay_events`、Postgres event store 已存在。 |
| 状态不能靠 prompt 维护 | 已实现。session state、clue、memory、phase 都在后端模型里。 |
| 证据解锁由规则控制 | 部分实现。已有 `clue.discovered`、`player_knowledge.updated`、规则触发，但证据图谱还不完整。 |
| NPC 不应知道全局真相 | 部分实现。Agent context、memory scope、Director 都在控视角。 |
| AI 请求，代码裁决 | 架构上已实现。当前不是前端 function tool，而是 `ActionService -> RuleEngine`。 |
| World Info 不能存完整真相 | 已升级为 `world_info`、`claim_graph`、Fact Gateway 方向。 |
| Memory 不能乱摘要 | 已进入 Memory v2：operation、metadata、scope、retrieval matrix。 |
| 幂等、顺序、回放 | 已实现到 Postgres runtime：sequence、idempotency key、stale sequence。 |
| LLM fallback 要可观测 | 已部分实现：`llm_error`、`llm_fallback_used`、trace 字段。 |

## 可以参考的前端方向

### 1. Data Bank / 证据库体验

SillyTavern 的 Data Bank 思路值得参考。悬疑游戏前端需要一个证据原件资产层，不只是 clue summary。

建议前端拆出：

- 案件隐藏资产。
- 玩家已发现证据。
- 当前 session 可见证据。
- 可进入 prompt 的证据摘要。
- 原件视图：报告、日志、聊天记录、图片 OCR、录音转写、邮件等。

关键原则：隐藏证据不能进入检索库，也不能进入 prompt。证据解锁后，前端只展示后端允许展示的证据内容。

### 2. 事件驱动 UI

SillyTavern 的事件总线对前端设计有启发，但本项目不应照搬它的事件名。前端应围绕后端 `WorldEvent` 建立 UI 事件。

建议前端关注：

```text
action.submitted
world_events.received
clue.discovered
player_knowledge.updated
memory.injected
director.blocked
phase.changed
relationship.changed
```

这样 UI 的证据板、时间线、人物状态和任务日志都可以从事件流派生，而不是各自维护一套隐式状态。

### 3. Quick Reply / 快捷操作

SillyTavern 的 Quick Reply / Slash Command 适合 MVP 阶段验证交互闭环。

本项目前端可以先做低成本按钮：

- 调查地点。
- 询问人物。
- 展示线索。
- 查看证据。
- 提交推理。

但按钮只能提交结构化 `PlayerAction`，不能直接改状态。

### 4. Tool Calling 体验

SillyTavern 的工具调用体验值得参考，但本项目的状态裁决仍应在后端。

前端可以把某些交互包装成“模型请求、代码裁决”的体验：

- 模型建议检查某份证据。
- 前端展示可点击操作。
- 玩家确认后提交结构化 action。
- 后端决定是否允许、是否解锁、是否写入事件。

工具调用不应成为绕过 `RuleEngine` 的入口。

### 5. Swipe / Regenerate 的分支风险

SillyTavern 支持重生成和候选回复，这对聊天体验有用，但对游戏状态是高风险点。

如果本项目未来支持重生成 NPC 回复，必须引入：

- canonical response。
- event revision。
- 未采纳分支的废弃策略。
- 已提交状态的回滚或重算机制。
- UI 明确提示当前哪条分支是有效剧情。

没有 canonical 分支策略前，不建议开放会影响状态的 regenerate。

### 6. 向量检索边界

SillyTavern 的向量检索思路可以参考，但只能索引已授权资料。

本项目未来接 `pgvector` 或全文检索时必须坚持：

- 已发现证据可索引。
- NPC 当前视角可见记忆可索引。
- 玩家已知案卷可索引。
- 隐藏真相、未发现证据、结局条件不能进向量库。

向量相似度不能决定案件真相，只能帮助召回已授权资料。

### 7. World Info 的交互机制

SillyTavern World Info 的 sticky、cooldown、delay、inclusion group 可以转译为本项目的检索和披露策略：

- sticky：刚发现线索短期提高注入权重。
- cooldown：避免同一事实反复注入。
- inclusion group：同组事实只注入当前阶段允许的一条。
- delay：剧情阶段、beat 或证据条件满足后才允许披露。

这些规则应进入 `MemoryRetriever`、`FactGateway`、`NarrativeDirector`，不要直接由前端 prompt 拼接决定。

## 不应照搬的部分

### 1. 前端扩展不应成为权威状态机

SillyTavern 建议 MVP 先做前端扩展，这对它自己的生态合理，但不适合本项目的生产目标。

本项目的权威状态应该继续是：

```text
Postgres world_events
  -> replay
  -> SessionState
```

前端可以缓存和展示状态，但不能成为真相源。

### 2. Chat Metadata / Variables 只能做 UI 缓存

如果前端需要缓存当前面板状态、筛选条件、展开项、未读提示，可以用本地状态或 metadata。

但这些不能用于：

- 证据是否已解锁。
- NPC 是否知道某秘密。
- 剧情阶段是否推进。
- 玩家是否破案。
- 结局是否达成。

这些必须来自后端事件和规则。

### 3. World Info 不能替代 Rule Engine

World Info 适合表达“当前可以让模型知道什么”，不适合决定：

- 是否解锁证据。
- 是否推进阶段。
- 是否允许提交指控。
- 是否进入结局。

这些必须由后端规则和事件流完成。

### 4. Regex 不能作为防泄底主方案

Regex 可以做输出清洗，但不能作为长期剧透防护主方案。

本项目应继续推进：

- claim graph。
- safe fragments。
- forbidden inferences。
- unlock conditions。
- Director 前后置校验。

### 5. 通用 Memory 不适合悬疑游戏

通用聊天摘要容易把未证实推测写成事实，也容易丢失来源。

本项目应继续走 typed memory：

- 每条 memory 带 source event。
- 每条 memory 有 visibility/scope/layer。
- 每次注入可追踪。
- 检索结果可评测。
- 未相关命中时禁止按 salience fallback 注入。

## 前端后续建议

### P0：证据板和人物面板

优先做正式游戏 UI，而不是继续把所有交互压在聊天框里。

最小 UI：

- 已发现证据列表。
- 证据详情原件视图。
- 人物档案。
- 当前地点。
- 当前阶段。
- 可执行动作按钮。
- 提交推理入口。

所有数据从 API `StateSummary` 和 `WorldEvent` 派生。

### P1：事件流驱动的 UI 状态

前端应把后端事件流当作 UI 更新来源。

示例：

- `clue.discovered` 更新证据板。
- `player_knowledge.updated` 更新玩家已知事实。
- `relationship.changed` 更新人物面板。
- `director.blocked` 更新审计/异常提示。
- `narrative.phase.changed` 更新阶段 UI 和可用操作。

### P2：证据原件资产层

为每条 evidence/clue 建立更完整的前端展示结构：

- title。
- summary。
- original_text。
- source。
- credibility。
- related_people。
- related_time。
- related_location。
- unlocked_at_event_id。

后端只返回已解锁资产。

### P3：可控重生成

在没有 canonical 分支机制前，前端不要开放会影响状态的 regenerate。

如果要支持：

- 只能重生成未提交状态的表达层回复。
- 或者生成候选不写事件，玩家选择后才提交 canonical event。
- 已写入 `WorldEvent` 的结果必须有明确撤销/重放策略。

## 最小可落地前端闭环

建议最小闭环：

```text
1. 玩家点击地点热点
2. 前端提交 PlayerAction.inspect
3. 后端返回 new_events + StateSummary
4. 前端根据 clue.discovered 更新证据板
5. 玩家选择 NPC 和证据，点击展示线索
6. 前端提交 PlayerAction.present_clue
7. 后端返回 NPC speech、关系变化、记忆变化、Director 结果
8. 前端更新人物面板、证据板、对话区
9. 玩家提交推理
10. 后端 RuleEngine 判定是否满足证据链
```

这条链路比“聊天框 + prompt”更符合本项目的生产目标。

## 审判结论

SillyTavern 指导的核心原则对本项目高度有效：

- 真相不进 prompt。
- 模型负责演绎，代码负责规则。
- 已发现证据才进入上下文。
- 工具调用/动作接口是状态变更入口。
- 重生成必须绑定分支策略。

但它的实现路线只适合基于 SillyTavern 做游戏壳的项目。

本项目应吸收其产品交互经验，继续坚持当前后端权威架构。
