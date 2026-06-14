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
- `character_fact_awareness`
- `memory_candidates`
- `memory_snapshots`
- `character_impressions`
- `events`

`StateSummary` 是对该状态的公开投影，不是权威状态。运行时记忆快照、角色事实认知账本和私有角色画像刻意不通过 `StateSummary` 暴露。

## 角色卡

静态角色数据分为公开角色卡和私有角色视角：

- 公开层：`display_name`、`public_role`、`public_description`、`speech`、可见性格 traits 和响应风格。
- 私有层：goals、secrets 和内部 character knowledge。

`private` 不是对 NPC 自己隐藏。目标 NPC 永远知道自己的 private goals、secrets、knowledge 和 impressions。限制点是公开投影、其他 NPC 可见性、对外表达和状态权威。

`AgentContext.target_profile` 只来自公开层。运行时记忆可以使用公开显示名提高可读性，但不得把 private goals、secrets 或内部 knowledge 复制进 `WorldEvent`、`StateSummary`、`AgentContext` 或玩家旅程输出。

`CharacterInnerContext` v0 只把目标 NPC 自己的受控自我视图复制到 `AgentContext.inner_context`。它不会复制其他 NPC 的 private 数据，也不会暴露原始 `CharacterPrivateConfig`。每个 inner item 都带有 `DisclosurePolicy`，让 fallback Agent 能使用认知而不自动泄露。

`private.goals` 表示 NPC 想要什么。`private.secrets` 表示 NPC 正在隐藏什么。`private.knowledge` 表示 NPC 从自身视角知道什么。运行时 `inner_portraits` 表示 NPC 如何看待别人。

Private 数据是角色认知，不是自动公开事实，也不是直接修改状态的通道。

## 角色事实认知账本

`CharacterFactAwarenessState` 是 NPC 视角下的事实认知账本。它解决的问题不是“角色卡里写了什么”，而是“运行时当前这个 NPC 对某个 `WorldInfo` 处于什么认知姿态”。

当前字段包括：

- `character_id`：认知所属 NPC。
- `world_info_id`：对齐的事实锚点。
- `stance`：`knows`、`suspects`、`conceals`、`misbelieves`。
- `confidence`：该认知姿态的置信度。
- `source_type`：来源类型，例如 `character_card`、`player_asked_about`、`player_presented_clue`、`player_accused`。
- `source_refs`：来源引用，例如 `secret:xxx`、`knowledge:xxx`、`clue:xxx`、`claim:xxx`。
- `evidence_clue_ids`：关联证据线索。
- `source_event_ids`：运行时事件来源。
- `last_updated_event_id`：最后一次更新事件。

初始化时，系统会从角色 `private.goals`、`private.secrets`、`private.knowledge` 的 `related_world_info_ids` 静默构造初始账本：

- goal / secret 默认表示 `conceals`
- private knowledge 默认表示 `knows`
- 同一 NPC 对同一 `WorldInfo` 同时有 secret 和 knowledge 时，`conceals` 优先，因为表达策略必须按更保守边界处理

静默初始化不会写入 `WorldEvent`，因此不会污染玩家时间线。玩家交互导致认知变化时才写入 `character_fact_awareness.updated`：

```text
player asks about discovered clue
  -> character_fact_awareness.updated(source_type=player_asked_about)

player presents clue
  -> character_fact_awareness.updated(source_type=player_presented_clue)

player accuses with evidence
  -> character_fact_awareness.updated(source_type=player_accused)
```

安全边界：

- 只有运行时派生系统和 Rule Engine 链路能写角色事实认知事件。
- LLM 不能创建、修改或删除角色事实认知。
- `StateSummary` 不暴露 `character_fact_awareness`。
- `player_journey.md` 只记录“私有角色事实认知更新”，不打印具体 payload。
- `AgentContext.inner_context.fact_awareness` 只给目标 NPC 自己，不给其他 NPC。
- 这不是 NPC-NPC 社交模拟，也不会把某 NPC 的认知传播给另一 NPC。

## 事实披露策略

`FactDisclosureStrategy` 是从角色事实认知账本派生出的 Agent 输入投影。它不进入 `SessionState`，也不写事件。它的职责是把“这个 NPC 对某个事实处于什么认知姿态”翻译成“当前对外表达允许到什么程度”。

核心字段：

- `world_info_id`：策略约束的事实锚点。
- `stance`：来自 `CharacterFactAwarenessState`。
- `allowed_modes`：允许表达模式，例如 `deny`、`deflect`、`hint`、`partial`。
- `forbidden_modes`：禁止表达模式，默认始终禁止 `full`。
- `rhetoric_tactics`：允许的话术战术，例如 `answer_adjacent_truth`、`shift_focus`、`counter_question`、`qualify_certainty`、`emotional_screen`。
- `must_not_claim`：禁止 LLM 直接宣称的内容，例如 `full_reveal:<world_info_id>`。
- `safe_fact_refs`：当前允许围绕其说话的证据线索引用。
- `source_awareness_id`：来源认知账本条目。

它不是“撒谎许可”。`stance=conceals` 只表示 NPC 正在隐藏或规避某个事实；实际表达可以是沉默、回避、暗示、半真半假的蒙太奇话术或部分承认。直接撒谎仍应被单独配置和审查，不能由 LLM 自由决定。

当前策略原则：

- `conceals`：默认允许 `deny` / `deflect` / `hint`，有相关证据压力时可允许 `partial`。
- `knows`：默认允许 `hint` / `partial`。
- `suspects`：默认允许 `deflect` / `hint`，强调不确定性。
- `misbelieves`：默认只允许保守回避，保留给后续误导和反转。
- 高威胁或危险话题会收窄到 `deny` / `deflect`。
- 结盟潜力高可以增加 `hint`，但不能授予 `full`。

MockAgent 和未来 LLM 都读取同一个策略层。LLM 负责把策略写成自然台词，但不能突破 `allowed_modes`、`forbidden_modes` 和 `must_not_claim`。

## 案件可配置披露风格

案件作者可以在 `characters.yaml` 的 `private.disclosure_style` 下配置角色级表达偏好。它只影响策略投影，不修改事实、玩家已知、角色认知或剧情阶段。

最小配置：

```yaml
private:
  disclosure_style:
    preferred_tactics:
      - answer_adjacent_truth
      - shift_focus
    forbidden_tactics:
      - emotional_screen
    max_mode_by_world_info:
      will_swapped: hint
```

语义：

- `preferred_tactics`：角色偏好的话术战术，会加入策略候选。
- `forbidden_tactics`：该角色不使用的话术战术，会从策略中移除。
- `max_mode_by_world_info`：指定某个 `WorldInfo` 的最高披露等级，只能收紧，不能放宽。

例如 `will_swapped: hint` 表示即使玩家有证据压力，管家对 `will_swapped` 也最多只能暗示，不能 partial 或 full。反过来，配置 `desk_forced_open: full` 也不会让系统允许 full，因为通用策略和 Director 仍然禁止未授权 full reveal。

Loader 会校验 `max_mode_by_world_info` 中的每个 `world_info_id` 必须存在；悬空引用会导致案件加载失败。

## WorldInfo 事实锚点

当前运行时将 `WorldInfo` 作为核心事实锚点使用。`WorldInfo` 不替代线索、记忆或关系，而是为“可被发现、隐藏、禁说、推断、指控”的事实提供稳定 ID。

边界如下：

- `Clue` 是证据，描述玩家在场景中发现了什么。
- `WorldInfo` 是事实锚点，描述证据指向的世界事实。
- `PlayerKnowledge` 是玩家已知账本，记录玩家通过哪个来源掌握了哪个 `WorldInfo`。
- `ForbiddenFact` 是叙事禁说规则，把禁说词和剧情阶段绑定到某个 `WorldInfo`。
- `SolutionClaim` 是正式指控规则，声明成立指控需要哪些证据和事实锚点。

`WorldInfo` 还可以配置两个文本审计辅助字段：

- `aliases`：该事实在自然语言里可能出现的常见说法。
- `claim_patterns`：用于识别事实变体表达的正则 pattern。

这两个字段不是新事实，不是运行时状态，也不会让玩家或 NPC 自动知道任何内容。它们只供 `NarrativeDirector` 在生成后审计 `speech` 是否实际触碰某个事实锚点。旧案件不配置这两个字段仍然合法，默认按空列表处理。

Loader 会校验每个 `claim_patterns` 是否是合法正则。非法正则会让案件加载或 `case validate` 失败，避免运行时审计链路带着坏 pattern 启动。

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
- `presentation_mode`：`private` 或 `scene_shared`
- `scene_id`，只允许在 `presentation_mode=scene_shared` 时写入
- `present_character_ids`，可选；由后端根据 `scene_id` 计算当前场景在场 NPC
- `knowledge_id`
- `text`
- `interaction_pressure`

该事件本身不修改线索状态。它是可审计的玩家施压/试探动作，会影响 `AgentContext`、MockAgent 回复选择、Director 检查和 Rule Engine 对 proposed actions 的处理。它不表示线索证明目标 NPC 有罪。

`presentation_mode=private` 表示私下展示，Rule Engine 禁止同时传入 `scene_id`，派生出的玩家互动记忆只对目标 NPC 可见。`presentation_mode=scene_shared` 表示当众展示，必须传入 `scene_id`；Rule Engine 必须校验目标 NPC 位于该场景，并把场景角色列表写入 `present_character_ids`。缺失 `presentation_mode` 的旧请求按 `scene_id` 做兼容推断，但新 UI / API / REPL 入口必须显式提交该字段，不能因为案件静态场景里有多名角色就默认扩散记忆。

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
- `rule_id`
- `memory_type`：`episodic`、`belief`、`relationship`、`strategy`
- `memory_scope`：`case`、`session`、`npc_private`、`scene_shared`、`director_audit`
- `memory_layer`：`core`、`working`、`archival`
- `subject_id`
- `owner_character_id`
- `visible_to_character_ids`
- `content`
- `source_event_ids`
- `source_memory_ids`
- `salience`
- `confidence`
- `visibility`
- `metadata`
- `last_updated_event_id`
- `created_at`
- `updated_at`

Memory v1 把“NPC 记得事件”升级为“NPC 基于事件形成主观认知”。当前只支持四类 typed memory：

- `episodic`：事件记忆，记录玩家做过什么。
- `belief`：信念记忆，记录 NPC 相信或怀疑什么。
- `relationship`：关系记忆，记录 NPC 对玩家信任、怀疑、恐惧等变化。
- `strategy`：策略记忆，记录 NPC 接下来倾向如何应对。

当前不引入 `theory`、`contradiction`、`commitment`、向量记忆或 graph memory。

Memory v1.1 将硬编码派生收口为 `MemoryDerivationRule`，并把记忆分成 scope 与 layer：

```text
MemoryDerivationRule
  -> id
  -> trigger_event_type / trigger_action_type
  -> target_id / target_character_id
  -> clue_id / subject_id / claim_id
  -> produces: list[MemoryEffect]
```

所有 `memory_candidate.created` 和 `agent_memory_snapshot.updated` 都必须带 `rule_id`、`memory_scope`、`memory_layer`，便于审计哪条规则产生了记忆，以及它属于哪个投影边界。每条 typed memory 必须带 `source_event_ids`，同一 `source_event_id` 对同一 memory / portrait 只能应用一次。

Memory v1.4 中，`MemoryEffect` 可以声明完整候选记忆字段：

- `rule_id`：可覆盖外层规则 id；默认使用外层 `MemoryDerivationRule.id`。
- `memory_id` / `memory_id_template`
- `memory_type`
- `memory_scope`
- `memory_layer`
- `subject_id`
- `owner_character_id`
- `visible_to_character_ids`
- `content` / `content_template`
- `salience` 或 `salience_from_event` + `min_salience`
- `confidence`
- `source_event_ids`
- `source_memory_ids`
- `metadata`

模板变量只来自受控 `WorldEvent.payload` 和安全 case lookup，例如 `{target_id}`、`{target_name}`、`{clue_id}`、`{clue_title}`、`{subject_type}`、`{subject_id}`、`{claim_id}`、`{interaction_pressure}`、`{knowledge_id}`、`{scene_id}`、`{source_event_id}`。模板渲染是纯确定性逻辑，不调用 LLM。

规则来源顺序固定为：先加载 `app/runtime/memory_derivation_rules.yaml`，再加载案件包 `memory_derivation_rules.yaml`。`DerivedEventSystem` 优先应用配置规则；如果配置规则没有为当前事件产生目标 core memory，则保留旧 Python fallback。当前已配置化迁移 `player.presented_clue` 的 core episodic memory，以及 `mist_clock_manor` 中 `jiang_yanhui + empty_capsules` 的 belief / relationship / strategy memory。其他 core 派生在未迁移前继续走 fallback。

当前 scope 语义：

- `case`：案件级安全摘要，例如玩家发现某条线索；默认只允许 `core` 进入 NPC 上下文。
- `session`：本局公共上下文；默认只允许 `working` 进入 NPC 上下文。
- `npc_private`：某个 NPC 对玩家交互形成的私有记忆；默认 typed memory 使用 `npc_private` + `working`。
- `scene_shared`：玩家在公共场景向多人展示线索时形成的共享事件记忆，`visible_to_character_ids` 必须包含当前场景在场 NPC。
- `director_audit`：供 Narrative Director 审计的记忆，普通 NPC `AgentContext` 禁止注入。

当前 layer 语义：

- `core`：可长期作为案件级稳定锚点使用。
- `working`：默认运行时工作记忆。
- `archival`：事件和 replay 必须保留，但默认不注入 NPC `AgentContext`，当前也不做真正 archival search。

`metadata` 仍以 dict 形式存储以保持事件 JSON 简洁，但键名受模型校验约束。当前允许的稳定键只有：

- `relationship_delta`
- `strategy_id`
- `belief_subject`
- `belief_polarity`
- `emotion_delta`
- `clue_id`

禁止新增 `strategy`、`current_strategy`、`npc_strategy`、`deltas` 等漂移键。

当前 seed 规则示例：

```text
player.presented_clue target=jiang_yanhui clue=empty_capsules
  -> episodic: 玩家向江医生展示空胶囊
  -> belief: 江医生认为玩家正在接近药物线索
  -> relationship: suspicion +0.2, trust -0.1
  -> strategy: avoid_medicine_topic
  -> memory_scope=npc_private
  -> memory_layer=working

player.presented_clue target=jiang_yanhui clue=empty_capsules presentation_mode=scene_shared scene_id=study
  -> scene_shared episodic: 玩家在 study 当众展示空胶囊
  -> visible_to_character_ids=[study.characters]
  -> memory_layer=working
```

这些记忆仍必须先作为 `memory_candidate.created` 出现，再由 `MemorySnapshotSystem` 写入 `agent_memory_snapshot.updated`。LLM 和 AgentIntent 不能直接创建 typed memory。

`MemorySnapshotSystem` 只消费 `memory_candidate.created`，更新 `session.memory_snapshots`，并写入 `agent_memory_snapshot.updated`。Agent、LLM 和 `AgentIntent.proposed_actions` 都不能写记忆快照。

NPC 记忆隔离规则：

- `owner_character_id` 表示这条记忆属于哪个 NPC 的可检索经历。
- `visible_to_character_ids` 表示允许哪些 NPC 在普通 Agent turn 中检索该记忆。
- 玩家与某个 NPC 的互动记忆默认只对该 NPC 可见。
- 线索发现记忆默认作为 `case/core` 玩家已知探索状态，对案件内 NPC 可见，但仍只暴露 clue/world info 的安全摘要。
- Director 审计视角可以通过专门检索入口查看所有非 archival 的 player-scoped 记忆摘要，包括 `director_audit`；这不等于把记忆注入某个 NPC 上下文。
- 普通 NPC `AgentContext` 禁止注入 `director_audit`、其他 NPC 的 `npc_private`、其他 NPC 的 portrait 和 `archival` memory。

示例：

```text
player.presented_clue target=jiang_yanhui clue=empty_capsules
  -> memory.player.presented_clue.jiang_yanhui.empty_capsules
  -> owner_character_id=jiang_yanhui
  -> visible_to_character_ids=[jiang_yanhui]

player.asked_about target=shen_zhaoye subject=empty_capsules
  -> memory.player.asked_about.shen_zhaoye.clue.empty_capsules
  -> owner_character_id=shen_zhaoye
  -> visible_to_character_ids=[shen_zhaoye]
```

`MemoryRetriever.retrieve(...)` 必须按 `action.target_id` 过滤可见性。`MemoryRetriever.retrieve_for_director(...)` 是 Director 审计入口，可以看到所有 player-scoped 记忆摘要，但不能绕过 Director/Rule Engine 造成状态变化。

`MemoryRetriever` 的过滤顺序固定为：先过滤 `memory_scope`，再过滤 `visible_to_character_ids` / `owner_character_id`，最后过滤 `memory_layer`。`build_agent_context(...)` 只允许注入：

- `case/core`
- `session/working`
- 当前 NPC 可见的 `npc_private`
- 当前 NPC 可见的 `scene_shared`
- 当前 NPC 自己的 `portrait_summary`

Memory v1.2 的 `MemoryProjectionSkill` 和 `MemoryRetrievalPlan` 不是世界状态，不写入 `WorldEvent`，也不参与 replay 权威。它们只是在构造 `AgentContext` 时解释“当前动作、阶段和 completed beats 下应该投影哪些安全记忆”。Plan 可以收窄 memory type/scope/layer、限制条数、关闭画像摘要或 recent events；但不能让 `director_audit`、`archival`、其他 NPC private、其他 NPC portrait 或 forbidden fact 文本进入普通 NPC 上下文。

Memory v1.3 的检索质量分数同样不是世界状态。`MemoryRetriever` 可以在过滤后使用结构化锚点、中文/英文 token、`updated_at` recency、`source_event_ids` reinforcement、salience 和 confidence 做排序，但这些分项不得写入 `memory_candidate.created`、`agent_memory_snapshot.updated`、snapshot `metadata` 或 replay 结果。recency 的“当前时间”来自事件流或已有 snapshot 时间，禁止使用 wall-clock `now()` 影响可复现性。

AgentLoop 中的 `memory_snapshots`、`memory_ids_used`、trace `memory_projection` 和 tool `search_memory` 摘要必须来自同一次注入 retriever 的结果。`build_agent_context(...)` 只有在调用方未传入已检索 snapshot 时才执行内部 fallback 检索；该 fallback 是兼容路径，不是普通 turn 的事实源。

运行时生成的 memory id 是语义化且稳定的，足以被案件配置的 mock dialogue 条件引用，例如：

- `memory.player.clue_discovered.scratched_drawer`
- `memory.player.presented_clue.butler.scratched_drawer`

它们不得依赖运行时 UUID。

成功指控也进入记忆路径，例如：

- `memory.player.accused.butler.butler_moved_key`
- `memory.player.accusation_evaluated.butler.butler_moved_key.correct`

这不是向量记忆、RAG、LLM 摘要或数据库持久化。快照状态必须能从 `WorldEvent` replay。

## 私有角色画像

`CharacterImpression` 是观察者角色拥有的私有认知。它继承 `NPCPortraitState`，不是角色卡真相，也不是公开资料。它记录某个 NPC 如何看待玩家。

`NPCPortraitState` 当前字段包括：

- `owner_character_id`
- `subject_id`
- `trust`
- `suspicion`
- `fear`
- `traits`
- `current_strategy`
- `source_memory_ids`

`CharacterImpression` 在此基础上继续保留解释性画像字段：

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

Memory v1 中，画像更新会消费同一套 typed-memory 规则结果。例如江医生看到 `empty_capsules` 后，画像会记录 `suspicion` 上升、`trust` 下降、`current_strategy=avoid_medicine_topic`，并把对应 belief / relationship / strategy memory id 写入 `source_memory_ids`。

静态人物设定、作者侧角色画像说明可以继续用 Markdown 或案件包文档维护；运行时 NPC 对玩家的画像不能只维护在 Markdown 中，必须落到 `character_impression.updated` 事件和 `session.character_impressions`，否则无法 replay、审计或隔离。

画像还会影响 `CharacterInnerContext` 中的有效披露模式：高威胁或危险话题会收窄表达；结盟潜力可允许 hint；相关证据可对匹配 self-knowledge 允许 partial。该投影不修改 `SessionState`，也不授予 full reveal。

Replay 直接应用 `character_impression.updated`，不得重新运行画像派生。

角色事实认知账本 replay 分两步：

1. 从案件包静默重建初始认知。
2. 按事件日志应用 `character_fact_awareness.updated`。

这样 replay 后的 `session.character_fact_awareness` 必须与原 session 一致，同时不会要求 session 创建事件显式存储私有角色卡内容。

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
- `character_fact_awareness.updated`
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
- `character_fact_awareness.updated` 从事件日志 replay，不让 LLM 或 Agent 直接写入。
- `character_impression.updated` 从事件日志 replay，不重新运行画像派生。

## 泄漏边界

公开摘要不得暴露角色 `secrets`、角色 `goals`、内部角色 `knowledge`、角色事实认知账本、私有角色画像、角色卡 `private` 对象、线索 `truth_status`、禁说事实原文、blocked terms、`forbidden_facts` 或 `solution_claims`。

`StateSummary`、`WorldEvent` payload 和 `player_journey.md` 也不得暴露 `inner_context` 或原始 private summaries。

`director.blocked` 事件可以记录 `world_info_id`、`matched_by`、`detected_directness`、`pattern_id` 等审计元数据，但公开 payload 中的 `matched_text` 必须脱敏，不能把被拦截的禁说词、private 原文或敏感事实原文再次回显给玩家。

## 案件扩写注意事项

`mist_clock_manor` 的 2026-06-14 扩写采用“可选证据厚度层”写法：新增 `Clue` 和 `WorldInfo` 必须挂到新 hotspot 或标准路径不检查的 hotspot，除非同步更新 `scenarios/standard_path.yaml` 的 `expected_events`、`expected_phase` 和 `expected_player_world_info_ids`。

可选线索允许产生新的 `PlayerKnowledge`，但不能无意成为核心 beat 的 `all_discovered` 条件；核心 phase 推进仍由原六条证据控制。新增公开线索标题、描述和 `WorldInfo.description` 必须按公开摘要处理，不能写 private summary、forbidden blocked term 组合或最终责任链结论。
