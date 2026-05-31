# 世界状态

`SessionState` 是内存中的权威运行时状态。静态案件内容保存在 `CasePackage` 中。

## SessionState

当前 session 状态包括：

- `id`
- `case_id`
- `narrative.phase`
- `narrative.discovered_clues`
- `narrative.completed_beats`
- `relationships`
- `relationship_thresholds_crossed`
- `discovered_clues`
- `player_knowledge`
- `memory_candidates`
- `memory_snapshots`
- `character_impressions`
- `events`

`StateSummary` 是对该状态的公开投影，不是权威状态。运行时记忆快照和私有角色画像刻意不通过 `StateSummary` 暴露。

## 角色卡

静态角色数据分为公开角色卡和私有角色视角：

- 公开层：`display_name`、`public_role`、`public_description`、`speech`、可见性格 traits 和响应风格。
- 私有层：goals、secrets 和内部 character knowledge。

`private` 不是对 NPC 自己隐藏。目标 NPC 永远知道自己的 private goals、secrets、knowledge 和 impressions。限制点是公开投影、其他 NPC 可见性、对外表达和状态权威。

`AgentContext.target_profile` 只来自公开层。运行时记忆可以使用公开显示名提高可读性，但不得把 private goals、secrets 或内部 knowledge 复制进 `WorldEvent`、`StateSummary`、`AgentContext` 或玩家旅程输出。

`CharacterInnerContext` v0 只把目标 NPC 自己的受控自我视图复制到 `AgentContext.inner_context`。它不会复制其他 NPC 的 private 数据，也不会暴露原始 `CharacterPrivateConfig`。每个 inner item 都带有 `DisclosurePolicy`，让 fallback Agent 能使用认知而不自动泄露。

`private.goals` 表示 NPC 想要什么。`private.secrets` 表示 NPC 正在隐藏什么。`private.knowledge` 表示 NPC 从自身视角知道什么。运行时 `inner_portraits` 表示 NPC 如何看待别人。

Private 数据是角色认知，不是自动公开事实，也不是直接修改状态的通道。

## WorldInfo 事实锚点

当前运行时将 `WorldInfo` 作为核心事实锚点使用。`WorldInfo` 不替代线索、记忆或关系，而是为“可被发现、隐藏、禁说、推断、指控”的事实提供稳定 ID。

边界如下：

- `Clue` 是证据，描述玩家在场景中发现了什么。
- `WorldInfo` 是事实锚点，描述证据指向的世界事实。
- `PlayerKnowledge` 是玩家已知账本，记录玩家通过哪个来源掌握了哪个 `WorldInfo`。
- `ForbiddenFact` 是叙事禁说规则，把禁说词和剧情阶段绑定到某个 `WorldInfo`。
- `SolutionClaim` 是正式指控规则，声明成立指控需要哪些证据和事实锚点。

当前链路：

```text
inspect hotspot
  -> clue.discovered
  -> clue.reveals_world_info
  -> player_knowledge.updated(world_info_id)
  -> StateSummary.player_knowledge
  -> replay 恢复同一 PlayerKnowledge
```

如果旧线索没有配置 `reveals_world_info`，运行时会回退到 `player_knowledge.<clue_id>`，用于兼容历史案件包。新案件应显式配置 `reveals_world_info`。

## 角色私有认知对齐

角色卡中的 `private.goals`、`private.secrets`、`private.knowledge` 可以继续保留 `related_clue_ids`，但新案件应同时配置 `related_world_info_ids`。

```text
CharacterPrivateConfig
  -> related_clue_ids          # legacy evidence trigger
  -> related_world_info_ids    # preferred fact anchor
  -> CharacterInnerContext
  -> SelfKnowledgeItem.related_world_info_ids
```

安全边界：

- `related_world_info_ids` 只进入目标 NPC 自己的 `CharacterInnerContext`。
- 其他 NPC 不会收到该角色的 private world info refs。
- `StateSummary` 不暴露 private world info refs。
- `player_journey.md` 不输出角色 private 原文。
- LLM 只能读取受控上下文，不能修改玩家已知或角色认知状态。

## 玩家已知

`clue.discovered` 会派生 `player_knowledge.updated`。玩家只有在以下条件同时成立时才能 `present_clue`：

- clue 存在于 `session.discovered_clues`
- 对应 `player_knowledge.<world_info_id>` 存在于 `session.player_knowledge`

这防止 UI 或未来 Agent 使用案件包中存在但尚未进入玩家公开知识的线索。

`PlayerKnowledgeState` 当前记录：

- `world_info_id`：玩家掌握的事实锚点。
- `clue_id`：产生该事实掌握的证据来源。
- `confidence`：当前掌握置信度，发现线索派生默认为 `1.0`。
- `acquisition`：获得方式，例如 `discovered`。
- `source_type`：来源类型，例如 `clue`。
- `source_event_id`：来源事件。

事件日志中的 `player_knowledge.updated` 必须包含这些字段。Replay 直接恢复该状态，不重新推导不确定内容。

## ask_about 与 present_clue

`ask_about` 在 Rule Engine 校验 subject 后写入 `player.asked_about`：

- `target_id`
- `subject_type`
- `subject_id`
- `text`
- `interaction_pressure`
- `knowledge_id`，当 subject 是玩家已知线索时存在

`ask_about` 压力低于 `present_clue`，但当 subject 敏感时仍可能让 NPC 更警惕。

合法 `present_clue` 写入 `player.presented_clue`：

- `target_id`
- `clue_id`
- `knowledge_id`
- `text`
- `interaction_pressure`

该事件本身不修改线索状态。它是可审计的玩家施压/试探动作，会影响 `AgentContext`、MockAgent 回复选择、Director 检查和 Rule Engine 对 proposed actions 的处理。它不表示线索证明目标 NPC 有罪。

非法 `ask_about` 或 `present_clue` 会写入 `rule.rejected`，不会产生 NPC 回复或关系变化。

## accuse

`accuse` 是正式结构化指控，包含 `claim_id`、目标角色、提交的 evidence clue ids 和可选玩家文本。它只由 Rule Engine 根据案件编写的 `solution_claims.yaml` 评估。

合法 accuse 写入：

- `player.accused`
- `accusation.evaluated`

非法 accuse 只写入 `rule.rejected`。它不调用 AgentGateway，不产生 `npc.replied`，不修改关系，也不直接改变 `narrative.phase`。

`accusation.evaluated` 可以包含配置结果，但 `StateSummary` 不得暴露 solution claim 配置或内部真相数据。

叙事结案 v0 是事件驱动：

```text
accusation.evaluated(result=correct)
  -> narrative.beat.completed(case_solved)
  -> narrative.phase.changed(reveal -> resolved)
```

阶段变化仍归 `RuleTriggerSystem` 和 `narrative_rules.yaml` 所有。

## 交互压力

`interaction_pressure` 由后端计算：

- `talk`：`0.1`
- `ask_about`：`0.3`
- `present_clue`：`0.6`
- 关联 subject 或 clue 命中 NPC：`+0.2`
- 关键线索：`+0.1`
- 最终限制在 `0.0 .. 1.0`

当 subject 与目标 NPC 相关，或 subject 是关键线索时，`subject_is_sensitive=true`。

## 运行时记忆

`memory_candidate.created` 是派生的候选记忆事件。它表示某个来源事件可能对未来 Agent 上下文重要，但还不是稳定记忆状态。

`AgentMemorySnapshot` 是运行时从候选事件归并出的结构化记忆状态。v0 只支持 `subject_id="player"`，包含：

- `memory_id`
- `subject_id`
- `content`
- `source_event_ids`
- `salience`
- `visibility`
- `last_updated_event_id`
- `created_at`
- `updated_at`

`MemorySnapshotSystem` 只消费 `memory_candidate.created`，更新 `session.memory_snapshots`，并写入 `agent_memory_snapshot.updated`。Agent、LLM 和 `AgentIntent.proposed_actions` 都不能写记忆快照。

运行时生成的 memory id 是语义化且稳定的，足以被案件配置的 mock dialogue 条件引用，例如：

- `memory.player.clue_discovered.scratched_drawer`
- `memory.player.presented_clue.butler.scratched_drawer`

它们不得依赖运行时 UUID。

成功指控也进入记忆路径，例如：

- `memory.player.accused.butler.butler_moved_key`
- `memory.player.accusation_evaluated.butler.butler_moved_key.correct`

这不是向量记忆、RAG、LLM 摘要或数据库持久化。快照状态必须能从 `WorldEvent` replay。

## 私有角色画像

`CharacterImpression` 是观察者角色拥有的私有认知。它不是角色卡真相，也不是公开资料。它记录某个 NPC 如何看待玩家：

- personality impression
- perceived motive
- suspected knowledge refs
- suspicious points
- trust boundary
- alliance potential
- threat level
- manipulation risk
- usefulness
- tags and confidence

v0 只支持 NPC -> player，存储结构为：

```text
session.character_impressions[npc_id]["player"]
```

画像由运行时代码从安全事件信号派生：

- `player.asked_about`
- `player.presented_clue`
- `player.accused`
- `relationship.threshold.crossed`
- `director.blocked`
- `accusation.evaluated`

每次变化写入 `character_impression.updated`。Agent 和 LLM 可以通过 `CharacterInnerContext` 读取当前目标 NPC 自己的画像，但不能直接写入或修改画像状态。

画像还会影响 `CharacterInnerContext` 中的有效披露模式：高威胁或危险话题会收窄表达；结盟潜力可允许 hint；相关证据可对匹配 self-knowledge 允许 partial。该投影不修改 `SessionState`，也不授予 full reveal。

Replay 直接应用 `character_impression.updated`，不得重新运行画像派生。

## WorldEvent 类型

- `session.created`
- `player.inspected`
- `player.talked`
- `player.asked_about`
- `player.presented_clue`
- `player.accused`
- `accusation.evaluated`
- `npc.replied`
- `director.blocked`
- `rule.rejected`
- `clue.discovered`
- `relationship.changed`
- `relationship.threshold.crossed`
- `player_knowledge.updated`
- `memory_candidate.created`
- `agent_memory_snapshot.updated`
- `character_impression.updated`
- `narrative.beat.completed`
- `narrative.phase.changed`

## Rule Engine 原则

- 重复发现同一线索必须幂等，不重复写 `clue.discovered`。
- 关系指标限制在 `-1.0 .. 1.0`。
- 关系阈值每个 session 每个 threshold 只触发一次。
- Agent 提出的剧情阶段变化必须被拒绝。
- 指控结果评估属于 Rule Engine，不属于 Agent 或 LLM 输出。
- `accuse` 不直接修改剧情阶段。
- 所有被接受的状态变化都必须表示为 `WorldEvent`。
- `replay_events(case, events)` 必须重建等价关键状态并保持事件数量。
- `agent_memory_snapshot.updated` 从事件日志 replay，不重新运行记忆派生。
- `character_impression.updated` 从事件日志 replay，不重新运行画像派生。

## 泄漏边界

公开摘要不得暴露角色 `secrets`、角色 `goals`、内部角色 `knowledge`、私有角色画像、角色卡 `private` 对象、线索 `truth_status`、禁说事实原文、blocked terms、`forbidden_facts` 或 `solution_claims`。

`StateSummary`、`WorldEvent` payload 和 `player_journey.md` 也不得暴露 `inner_context` 或原始 private summaries。
