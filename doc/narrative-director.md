# Narrative Director

当前 Narrative Director 是一个最小防剧透安全层。它会在 NPC 台词写入 `npc.replied` 事件之前校验文本。它不推进剧情阶段，也不完成 beats；这些仍由 `narrative_rules.yaml` 和 `RuleTriggerSystem` 负责。

## 配置来源

禁说事实写在每个案件包的 `forbidden_facts.yaml`。

每个 forbidden fact 包含：

- `id`：稳定禁说事实 ID
- `world_info_id`：对应的 WorldInfo 事实锚点
- `text`：内部事实描述
- `blocked_terms`：在 reveal 前触发阻止的词
- `reveal_phase`：该事实允许被说出的阶段

`text` 和 `blocked_terms` 是内部安全配置，不得出现在 `StateSummary`、`AgentContext` 或 `player_journey.md`。

## 当前校验

`NarrativeDirector.validate(case, narrative, intent)` 会扫描 `intent.speech`。

如果台词在 `reveal_phase` 之前包含某个禁说事实的 `blocked_terms`，Director 会拒绝该回复。

被阻止时：

- 不写入 `npc.replied`
- 写入 `director.blocked`
- 响应返回安全台词
- `ActionResponse.accepted=false`

`director.blocked` 可以包含 blocked fact id 用于审计，但不得包含禁说事实原文或 blocked terms。

## 角色 private 披露边界

角色 `private` 数据是目标 NPC 自己的非公开视角，不是对 NPC 自己隐藏。目标 NPC 永远知道自己的 private goals、secrets 和 knowledge。

运行时限制的是对外台词、公开投影、其他 NPC 可见性和权威状态写入。`private` 不是永久禁言，也不同于 `forbidden_facts`。

`CharacterInnerContext` v0 会把目标 NPC 专属的受控自我视图传入 `AgentContext.inner_context`。它不会传入其他 NPC 的 private 数据，也不会把 private 数据写入公开运行时输出。对外表达仍必须通过 Narrative Director 校验。

未来 Director 应进一步检查生成台词是否：

- 透露锁定的禁说事实
- 超过 `DisclosurePolicy` 允许的披露模式
- 在只允许回避、暗示或部分披露时引用 private 原文
- 与案件锚点、玩家已解锁知识或剧情阶段冲突
- 未经允许把一个 NPC 的 private 数据暴露给另一个 NPC

## Rule Engine 边界

Narrative Director 只判断台词是否安全，不负责让状态变化生效。

Rule Engine 仍负责决定 `AgentIntent.proposed_actions` 是否变成真实 `WorldEvent`。知道 private 信息不代表 NPC 可以直接修改世界状态、线索状态、关系状态、记忆快照或剧情阶段。

## 当前限制

v0 只对 `AgentIntent.speech` 做基于词项的 forbidden fact 检查。

`CharacterInnerContext` 已能在生成前根据 private impressions 计算有效 allowed disclosure modes。但 Director 还没有做语义级防剧透、完整披露策略后校验、多跳矛盾检查，或除当前确定性 fallback 行为之外的通用 private-item 脱敏。
