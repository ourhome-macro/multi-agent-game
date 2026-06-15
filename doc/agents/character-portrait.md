# 私有角色画像 v0

私有角色画像用于记录 NPC 对玩家的主观认知。设计笔记里也称为 character portrait，运行时事件名是 `character_impression.updated`。

## 定义

- Character Card：作者定义的角色真实设定。
- CharacterInnerContext：目标 NPC 专属的受控私有认知输入。
- `private.goals`：我想要什么。
- `private.secrets`：我正在隐藏什么。
- `private.knowledge`：我从自身视角知道什么。
- `inner_portraits`：我如何看待别人。
- Relationship Metrics：数值化社交状态，例如 `trust`、`suspicion`、`fear`。
- Character Impression：某个观察者对某个目标的主观判断、偏见、假设、信任边界、结盟潜力和威胁感。
- Memory Snapshot：运行时从事件派生的重要经历快照。
- Narrative Rules：阶段、beat 和结案条件。
- RuleEngine：接受状态变化的权威。
- NarrativeDirector：输出安全和防剧透权威。

## 边界

角色画像不是角色卡真相。它不说明目标真实是什么样，只记录 `observer_id` 当前如何解释 `target_id`。

v0 只支持 NPC -> player：

```text
session.character_impressions[npc_id]["player"]
```

当前运行时不支持 player -> NPC 或 NPC -> NPC 画像。

## 模型

运行时画像的基础模型是 `NPCPortraitState`：

- `owner_character_id`
- `subject_id`
- `trust`
- `suspicion`
- `fear`
- `traits`
- `current_strategy`
- `source_memory_ids`

`CharacterImpression` 继承 `NPCPortraitState`，并继续包含：

- `observer_id`
- `target_id`
- `personality_impression`
- `perceived_motive`
- `suspected_knowledge_refs`
- `suspicious_points`
- `trust_boundary`
- `alliance_potential`
- `threat_level`
- `manipulation_risk`
- `usefulness`
- `tags`
- `confidence`
- `source_event_ids`
- `last_updated_event_id`

文本字段必须来自安全运行时信号。不得复制禁说事实原文、blocked terms、角色 private secrets 或 solution claim 配置。

静态人物画像、作者注释和角色写作参考可以用 Markdown 维护；运行时 NPC 对玩家的画像不能只写在 Markdown 中，必须通过 `character_impression.updated` 落入事件日志，才能 replay、审计和隔离。

## 派生来源

v0 画像由运行时代码派生，不由 LLM 输出。

派生来源包括：

- `player.asked_about`
- `player.presented_clue`
- `player.accused`
- `relationship.threshold.crossed`
- `director.blocked`
- `accusation.evaluated`

每次更新都会写入 `character_impression.updated`。Replay 直接应用该事件，不重新运行画像派生逻辑。

Memory v1 中，画像也会记录 typed memory 的来源。例如江医生看到 `empty_capsules` 后，规则会派生：

- `belief`：玩家正在接近药物线索
- `relationship`：`suspicion +0.2`、`trust -0.1`
- `strategy`：`avoid_medicine_topic`

画像随后把这些 memory id 写入 `source_memory_ids`，并更新 `suspicion`、`trust` 和 `current_strategy`。这仍然是规则派生，不由 LLM 生成。

同一个 `source_event_id` 对同一个 portrait 只能应用一次。Replay 直接应用 `character_impression.updated` 中的完整画像状态，不根据 relationship memory 再叠加数值。

## Agent 输入

`CharacterInnerContext.inner_portraits` 只暴露当前目标 NPC 自己的画像。如果 butler 对 player 有画像，butler 可以在 `inner_portraits` 中看到；另一个 NPC 看不到。

`AgentContext.recent_events` 会过滤 `character_impression.updated`，避免一个 NPC 通过近期事件流看到其他 NPC 的私有画像。

`AgentContext.portrait_summary` 会注入当前目标 NPC 自己的低泄漏画像摘要，例如“江医生当前对玩家高度警惕”。它不是新的状态源，也不替代 `inner_portraits`。

`portrait_summary` 只能描述当前目标 NPC 自己可见的主观状态。它不得包含其他 NPC 的私有 memory、Director audit 结论、未发现真相、memory id、source event id 或“某 NPC 不知道某事”这类跨视角判断。

LLM Agent 可以读取目标 NPC 自己的 `inner_portraits` 和 `portrait_summary`，但不能直接修改 `SessionState`。未来任何画像写入仍必须是运行时派生的 `character_impression.updated` 事件。

## 画像感知披露 v0

`inner_portraits` 会影响目标 NPC `CharacterInnerContext` 中的有效披露策略。这是运行时输入投影，不是状态变更。

当目标 NPC 对玩家的画像具有以下特征时：

- `threat_level` 高：披露模式收窄到 `deny` / `deflect`
- `alliance_potential` 高：可能允许 `hint`
- `has_relevant_evidence`：匹配的 self-knowledge 可允许 `partial`
- `dangerous_topic_triggered`：披露模式收窄到 `deny` / `deflect`

v0 永远不会因为画像授予 `full` 披露，也不会允许直接引用 private 原文。

MockAgent fallback 会消费有效披露模式：

- 有相关证据且允许 `partial` 时，给出部分真相风格回复
- 有结盟潜力且允许 `hint` 时，给出谨慎提示
- 危险话题倾向拒答
- 高威胁倾向谨慎隐瞒

## 输出安全

画像是私有认知，不得通过以下渠道暴露：

- `StateSummary`
- `player_journey.md` 原文
- 另一个 NPC 的 `AgentContext`
- `AgentIntent.proposed_actions`

玩家旅程 Markdown 可以提到私有画像发生了更新，但不能打印 `personality_impression`、`perceived_motive` 或 `trust_boundary` 文本。

NarrativeDirector 仍校验对外发言。RuleEngine 仍校验状态变化 proposed actions。
