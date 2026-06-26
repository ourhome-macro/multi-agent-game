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

`StateSummary.evidence_assets` 是从已发现 `Clue` 和 `PlayerKnowledgeState` 派生出的证据原件公开摘要。它不新增权威状态、不写事件，也不直接读取案件包中尚未被玩家掌握的 `WorldInfo`。每条公开证据摘要包含：

- `id`：证据资产 ID，当前与来源 `clue_id` 对齐。
- `title`：来源线索标题。
- `summary`：来源线索公开描述，不使用 `WorldInfo.description` 作为原件摘要。
- `source`：来源类型，当前主要为 `clue`。
- `clue_id`：产生该证据资产的线索。
- `world_info_id`：玩家已通过该线索掌握的事实锚点，可为空。
- `source_knowledge_id`：来源玩家已知账本条目。
- `unlocked_at_event_id`：解锁该玩家已知的来源事件。

生成条件必须同时满足：`PlayerKnowledgeState` 存在、其 `clue_id` 已在 `session.discovered_clues` 中、且线索仍存在于案件包。仅存在于案件静态配置里的未发现线索、未解锁 `WorldInfo`、高敏案件真相锚点、禁说事实和 solution claim 都不能进入 `evidence_assets`。

## 角色卡

静态角色数据分为公开角色卡和私有角色视角：

- 公开层：`display_name`、`public_role`、`public_description`、`speech`、可见性格 traits 和响应风格。
- 私有层：goals、secrets 和内部 character knowledge。

`private` 不是对 NPC 自己隐藏。目标 NPC 永远知道自己的 private goals、secrets、knowledge 和 impressions。限制点是公开投影、其他 NPC 可见性、对外表达和状态权威。

`AgentContext.target_profile` 只来自公开层。运行时记忆可以使用公开显示名提高可读性，但不得把 private goals、secrets 或内部 knowledge 复制进 `WorldEvent`、`StateSummary`、`AgentContext` 或玩家旅程输出。

`CharacterInnerContext` v0 只把目标 NPC 自己的受控自我视图复制到 `AgentContext.inner_context`。它不会复制其他 NPC 的 private 数据，也不会暴露原始 `CharacterPrivateConfig`。每个 inner item 都带有 `DisclosurePolicy`，让 fallback Agent 能使用认知而不自动泄露。

`private.goals` 表示 NPC 想要什么。`private.secrets` 表示 NPC 正在隐藏什么。`private.knowledge` 表示 NPC 从自身视角知道什么。运行时 `inner_portraits` 表示 NPC 如何看待别人。

Private 数据是角色认知，不是自动公开事实，也不是直接修改状态的通道。

## Safe Fragment 投影

`WorldInfo.claim_graph.safe_fragments` 是可审计的部分事实释放单元。运行时只会把已解锁且当前上下文授权的 safe fragment 投影给 Agent，不会把完整 `WorldInfo.description` 或案件真相锚点直接交给 LLM。

`SafeFactFragmentProjection` 当前包含：

- `world_info_id`
- `fragment_id`
- `ref`
- `summary`
- `aliases`
- `claim_patterns`
- `allowed_modes`
- `source_refs`

`aliases` 和 `claim_patterns` 是合同级检测词表，用于让真实 LLM 输出投影和 Narrative Director 使用同一套可审计匹配边界。新增中文表达时应写入案件包的 safe fragment，而不是硬编码到 Agent 适配器。`source_refs` 只引用玩家已知、阶段或 beat 等解锁来源，不应包含 private 原文。

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
  -> StateSummary.evidence_assets
  -> replay 恢复同一 PlayerKnowledge
```

Hotspot 还可以配置 `backtrack_unlocks`，用于表达“玩家先检查 A，再满足后置条件后回到 A/B 才能发现的新线索”。该配置只声明条件和可解锁 `Clue`，不写状态。运行时语义：

```text
inspect hotspot
  -> RuleEngine checks static discover_clues
  -> RuleEngine checks hotspot.backtrack_unlocks against prior WorldEvent / SessionState
  -> clue.discovered(source_backtrack_unlock_id=...)
  -> player_knowledge.updated
```

`backtrack_unlocks.conditions` 当前支持：`phases`、`completed_beats`、`discovered_clues`、`player_knowledge_ids`、`player_world_info_ids`、`prior_inspected_hotspots` 和 `min_prior_inspections`。`CaseLoader` 会校验这些 ID 必须指向已存在的 phase、beat、clue、hotspot、WorldInfo 或可由线索产生的 PlayerKnowledge。Rule Engine 计算 prior inspection 时排除本次 `player.inspected` 事件，避免第一次检查在后置条件已满足时误触发返场线索。

返场解锁仍然必须发普通 `clue.discovered`，并由现有派生链生成 `PlayerKnowledge`、memory 和 replay 状态。LLM、NPC 回复、mock dialogue 或 `AgentIntent.proposed_actions` 不能绕过 `backtrack_unlocks` 直接修改线索或玩家已知。

`player_knowledge.<clue_id>` 只保留为低层函数对历史事件 replay 的兼容路径。当前 `CaseLoader` 对可到达线索执行 authoring gate：新案件包中每个可到达 `Clue` 都必须显式配置 `reveals_world_info`，并指向已声明的 `WorldInfo`。不能再依赖缺省 `clue_id` 作为事实锚点。

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

`EvidenceAsset` 是面向前端线索板/证据栏的领域投影，用于把“玩家掌握了某个事实”还原成“玩家手上有哪件证据原件”。它不能替代 `PlayerKnowledgeState`：正式 `present_clue` 和 `accuse` 仍由 Rule Engine 检查 `session.discovered_clues` 与 `session.player_knowledge`，而不是信任前端传回的 evidence summary。

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

`DeductionEvaluator` 是当前指控判定的只读解释层。它输入 `case`、`session` 和结构化 `PlayerAction(type=accuse)`，不写事件、不改状态，只返回结构化判定结果：

- `matched_claim`：命中的 `SolutionClaim` id；未知 claim 时为空。
- `missing_evidence`：未覆盖的 `required_evidence`。
- `missing_world_info`：玩家已知账本未覆盖的 `required_world_info`。
- `phase_allowed`：当前 `session.narrative.phase` 是否允许该 claim。
- `target_matches`：action target 是否与 claim target 一致。
- `accepted` / `result`：是否通过规则判定，以及通过后对应的 `correct` / `incorrect` 配置结果。

`RuleEngine.apply_accuse` 复用该 evaluator，并把拒绝码映射回既有 `rule.rejected` 原因，保持旧的 accuse 事件语义。未来 Evidence Graph 可以接到 evaluator 内部，但仍不能绕过 `PlayerKnowledge`、`WorldEvent` 和 Rule Engine 的状态边界。

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

规则来源顺序固定为：先加载 `app/runtime/memory_derivation_rules.yaml`，再加载案件包 `memory_derivation_rules.yaml`。`DerivedEventSystem` 优先应用配置规则；如果配置规则没有为当前事件产生目标 core memory，则保留旧 Python fallback。fallback 判定必须按目标 `memory_id` 执行，而不是只看是否存在同 trigger 规则；否则案件包规则和默认 core 规则的模板不一致时会重复派生语义相同的记忆。

当前已配置化迁移的默认 core episodic memory：

- `player.presented_clue` -> `memory.player.presented_clue.{target_id}.{clue_id}`
- `player.asked_about` -> `memory.player.asked_about.{target_id}.{subject_type}.{subject_id}`

当前仍保留 Python fallback 的 core memory：

- `clue.discovered` -> `memory.player.clue_discovered.{clue_id}`
- `relationship.threshold.crossed` -> `memory.player.relationship_threshold.{source_id}.player.{metric}.{state}`
- `director.blocked` -> `memory.player.director_blocked.{target_id}.{blocked_fact_id}`
- scene-shared `player.presented_clue` -> `memory.player.scene_shared.presented_clue.{scene_id}.{clue_id}`
- `player.accused` -> `memory.player.accused.{target_id}.{claim_id}`
- `accusation.evaluated` -> `memory.player.accusation_evaluated.{target_id}.{claim_id}.{result}`

`player.accused` 暂不迁移到 YAML，因为旧 fallback 的 content 包含 `evidence_clue_ids` 的 Python list 字符串，而当前模板变量白名单和渲染上下文只覆盖标量事件字段。迁移前必须先补稳定的数组渲染契约，否则无法保证 `content` 与旧硬编码语义完全等价。

案件包规则继续用于特定剧情认知，例如 `mist_clock_manor` 中 `jiang_yanhui + empty_capsules` 的 belief / relationship / strategy memory。

当前 scope 语义：

- `case`：案件级安全摘要，例如玩家发现某条线索；默认只允许 `core` 进入 NPC 上下文。
- `session`：本局公共上下文；默认只允许 `working` 进入 NPC 上下文。
- `npc_private`：某个 NPC 对玩家交互形成的私有记忆；默认 typed memory 使用 `npc_private` + `working`。
- `scene_shared`：玩家在公共场景向多人展示线索时形成的共享事件记忆，`visible_to_character_ids` 必须包含当前场景在场 NPC。
- `director_audit`：供 Narrative Director 审计的记忆，普通 NPC `AgentContext` 禁止注入。

当前 layer 语义：

- `core`：可长期作为案件级稳定锚点使用。
- `working`：默认运行时工作记忆。
- `archival`：事件和 replay 必须保留，普通检索不会直接参与 working 排序；只有当常规 `core/working` 检索没有相关命中时，才进入冷召回。

`metadata` 仍以 dict 形式存储以保持事件 JSON 简洁，但键名受模型校验约束。当前允许的稳定键只有：

- `relationship_delta`
- `strategy_id`
- `belief_subject`
- `belief_polarity`
- `emotion_delta`
- `clue_id`
- `world_info_id`
- `claim_id`
- `scene_id`
- `topic_tags`
- `privacy_reason`
- `decay_policy`

禁止新增 `strategy`、`current_strategy`、`npc_strategy`、`deltas` 等漂移键。

Memory v2 在模型层显式引入 `MemoryOperation`：

- `create`：创建新的候选/快照。
- `reinforce`：同一记忆被新事件强化，只合并来源、metadata 和 salience/confidence，不重写 canonical content。
- `revise`：更新 canonical content，用于纠正或收紧已有记忆表述。
- `supersede`：用新表述替代旧记忆，来源链仍保留在 `source_memory_ids` / `source_event_ids`。
- `archive`：把工作记忆降为 `archival`，不删除事件日志。

兼容规则：历史事件里的 `created`、`updated`、`reinforced`、`revised`、`superseded`、`archived`、`seeded` 会在模型校验时归一到 v2 operation。`MemoryArchivalSystem` 现有事件仍可写 `operation=archived`；模型会把它解释为 `archive`，避免历史 replay 和当前归档事件断裂。

`AgentMemorySnapshot` 记录 `last_operation`，用于审计最后一次快照变化的语义。`MemoryCandidateState` 记录 `operation`，由 `MemorySnapshotSystem` 解释并写入 `agent_memory_snapshot.updated.operation`。Postgres `memory_snapshots` 约束要求 active memory 必须有 `source_event_ids`；只有 `archival` 或显式 `metadata.non_authoritative=true` 的记录可以缺少来源。

metadata v2 不允许无约束 dict 漂移：

- ID 型字段必须是非空字符串：`world_info_id`、`claim_id`、`scene_id`、`phase_id`、`clue_id`、`belief_subject`、`strategy_id`、`privacy_reason`。
- `topic_tags` 和 `phase_ids` 必须是字符串列表，并去重保序。
- 叙事链路索引字段必须受校验：`case_thread_id` 和 `chain_node_id` 是非空字符串，`adjacent_clue_ids` 是去重保序字符串列表，`key_clue` 是布尔值。这些字段只描述检索链路，不是新的世界事实，也不能替代 `WorldInfo`、`PlayerKnowledge` 或 `SolutionClaim`。
- `non_authoritative` 必须是布尔值；它只允许存储非权威无来源材料，不允许普通检索把它注入 NPC 上下文。
- `authority_source` 必须来自白名单；缺省 `authority` 归一为 `event_observed`，显式 `non_authoritative=true`、`npc_hearsay`、`llm_summary` 或 `archival` 才会降权。事件锚定 memory 的权威性以 `source_event_ids` 和检索期 authority gate 共同判断，不能因为 metadata 省略 `authority_source` 就默认视为脏记忆。
- `decay_policy` 只能是 `standard`、`sticky`、`ephemeral`、`never_archive`，或只包含 `name`、`archive_after_days`、`reinforced_event_count` 的对象。

2026-06-16 起，运行时派生的 clue 相关 memory 必须自动补齐结构化 metadata，不能只依赖自然语言 `content` 做召回：

- `clue.discovered` -> `memory.player.clue_discovered.{clue_id}` 必须包含 `clue_id`、可用的首个 `world_info_id` 和 `topic_tags`。
- `player.asked_about` 的 clue subject memory 必须包含同一套 clue metadata。
- `player.presented_clue` 的私有 memory 必须包含同一套 clue metadata，并写 `privacy_reason=private_presentation`。
- scene-shared `player.presented_clue` memory 必须额外写 `scene_id` 和 `privacy_reason=scene_shared_presentation`。
- `topic_tags` 由 `clue_id` 的 snake_case 分词、完整 `clue_id`、`related_events`、`related_characters` 去重保序生成。
- 当某个 `clue_id` 出现在 `solution_claims` 中 `result=correct` 且 `allowed_phases` 包含 `reconstruction` 或 `resolved` 的 `required_evidence` 里，`clue.discovered` memory 还必须写入 `case_thread_id=<claim.id>`、`chain_node_id=<clue_id>`、`adjacent_clue_ids=<同 claim 其他 required_evidence>`、`key_clue=true` 和 `is_plot_critical=true`。这让检索器可以从一个已命中的线索节点扩展到同一案件线程的兄弟节点。普通 reveal/expose 型正式指控不自动进入该 reconstruction 链路机制。
- 同一类关键线索发现还会派生 reconstruction/resolved 阶段可见的 case/core `belief` 与 `strategy` memory，分别表示“玩家正在围绕重建线程组织证据”和“重建时应把线索作为链路节点连接”。这些 typed memory 必须由 `memory_candidate.created` 与 `agent_memory_snapshot.updated` 写入，正文不得包含正式指控结论、凶手主观恶意或未解锁真相。
- 当 reconstruction claim 的全部 `required_evidence` 已被玩家发现时，派生系统会额外为案件内每个 NPC 生成角色私有 `belief` / `strategy` memory。它们使用 `memory_scope=npc_private`、`memory_layer=working`、`owner_character_id=<npc_id>`、`visible_to_character_ids=[<npc_id>]`，并通过 `source_memory_ids` 指向触发的线索发现 memory。该状态只表达该 NPC 在重建阶段的应对立场，不新增世界事实、不改变 `PlayerKnowledge`、不扩大其他 NPC 可见性。
- `case_thread_id` 兄弟节点扩展和 reconstruction 选前重排都是检索期策略，不是 replay 状态副作用。它们只在 `reconstruction` / `resolved` 阶段启用；investigation 阶段仍只能通过直接锚点或 `source_memory_ids` 父子链召回，防止早期调查因为一个关键词把整条案件链路提前注入 NPC 上下文。重排只改变已合法候选的投影顺序，不写回 `AgentMemorySnapshot`。

配置化 `MemoryDerivationRule` 与 Python fallback 必须产生一致的默认 metadata。案件规则可以显式覆盖或补充 metadata，但不能移除 `clue_id` 这类召回锚点，否则会破坏 matrix 评测和可回放检索。

2026-06-26 起，Python fallback 和 scene-shared 派生中的稳定 `memory_id`、clue metadata、reconstruction thread metadata 与 `topic_tags` 组装必须通过 `app.runtime.derivation_utils` 的集中 helper 完成。helper 只负责确定性字符串和结构化 metadata 组装，不读取或修改 `SessionState`，也不替代 `MemoryDerivationRule` 模板、`MemoryRetriever` 过滤或 replay 权威。派生层仍必须把结果写成 `memory_candidate.created`，再由 `MemorySnapshotSystem` 产生 `agent_memory_snapshot.updated`；回放只应用事件日志中的 payload，不能重新运行 helper 推导状态。

迁移路径：

1. 旧规则不配置 `operation` 时按 `create` 处理；同一 `memory_id` 已存在时，`MemorySnapshotSystem` 会自动把重复 create 降为 `reinforce`。
2. 新规则需要纠错或替代时再显式配置 `revise` / `supersede`。
3. 归档事件继续兼容 `archived`，后续存储层迁移完成后可统一写 `archive`。
4. 新案件应优先补 `world_info_id`、`claim_id`、`scene_id` 和 `topic_tags`，让检索、审计和后续索引不用解析自然语言 content。

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
  -> npc_private belief/strategy: 为每个在场 NPC 生成各自的立场和应对记忆
  -> source_memory_ids=[scene_shared episodic memory id]
```

这些记忆仍必须先作为 `memory_candidate.created` 出现，再由 `MemorySnapshotSystem` 写入 `agent_memory_snapshot.updated`。LLM 和 AgentIntent 不能直接创建 typed memory。

`MemorySnapshotSystem` 只消费 `memory_candidate.created`，更新 `session.memory_snapshots`，并写入 `agent_memory_snapshot.updated`。Agent、LLM 和 `AgentIntent.proposed_actions` 都不能写记忆快照。

Memory P2 增加 `MemoryArchivalSystem`。它不消费 LLM 输出，只在运行时已有事件时间线上检查 `AgentMemorySnapshot`：

- 只归档 `session`、`npc_private`、`scene_shared` 中的 `working` memory。
- `case/core`、`director_audit`、已经是 `archival` 的 memory 不会被降级。
- 默认只有超过 7 天未更新，且 `source_event_ids` 未达到 2 个独立来源的 memory 会被降级。
- 降级必须写入 `agent_memory_snapshot.updated`，`operation=archive`，并把 `memory_layer` 改为 `archival`。
- Replay 直接应用该 snapshot update 事件，不重新计算归档策略。

Agent-backed action 会在构造 `AgentContext` 前执行归档检查，因此本轮检索看到的是已降级后的 snapshot。这个过程仍然是事件化状态变化，不是检索器静默改状态。

NPC 记忆隔离规则：

- `owner_character_id` 表示这条记忆属于哪个 NPC 的可检索经历。
- `visible_to_character_ids` 表示允许哪些 NPC 在普通 Agent turn 中检索该记忆。
- 玩家与某个 NPC 的互动记忆默认只对该 NPC 可见。
- 线索发现记忆默认作为 `case/core` 玩家已知探索状态，对案件内 NPC 可见，但仍只暴露 clue/world info 的安全摘要。
- Director 审计视角可以通过专门检索入口查看所有非 archival 的 player-scoped 记忆摘要，包括 `director_audit`；这不等于把记忆注入某个 NPC 上下文。
- 普通 NPC `AgentContext` 禁止注入 `director_audit`、其他 NPC 的 `npc_private`、其他 NPC 的 portrait。`archival` memory 只能通过冷召回进入上下文，且必须继续满足当前 NPC 的 scope、owner / visible_to、memory type、forbidden fact 过滤。

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

`MemoryRetriever` 的过滤顺序固定为：先过滤 `memory_scope`，再过滤 `visible_to_character_ids` / `owner_character_id`，最后过滤 `memory_layer`。常规检索只允许注入：

- `case/core`
- `session/working`
- 当前 NPC 可见的 `npc_private`
- 当前 NPC 可见的 `scene_shared`
- 当前 NPC 自己的 `portrait_summary`

如果常规检索没有任何结构化或文本相关命中，`MemoryRetriever` 会执行一次 archival cold recall。冷召回只放宽 `memory_layer=archival`，不放宽 `memory_scope`、NPC 可见性、memory type、forbidden fact 或 `max_memory_items`。若 archival 也没有相关命中，则不会因为 salience 高而召回无关 archival memory。

Memory DB-backed retrieval 第一阶段只改变候选读取来源，不改变世界状态权威。`MemoryStore` 是 `MemoryRetriever` 的读侧接口；默认 `InMemoryMemoryStore` 从 replay 后的 `session.memory_snapshots` 读取，PostgreSQL runtime builder 注入 `PostgresMemoryStore` 从 PostgreSQL `memory_snapshots` 投影表读取。Postgres 查询可以按 `session_id`、目标 NPC 可见性、scope、layer、memory type 和 metadata phase 做预筛，并可使用 `MemoryStoreQuery.query_anchors/query_tokens` 对 `metadata`、`source_event_ids/source_memory_ids`、`memory_id` 和 `content` 做轻量 query term 预筛。`query_tokens` 必须来自检索 query 的 semantic tokens，而不是只来自原始玩家文本；否则中文改写、world_info alias 和 clue alias 扩展会在 Postgres 后端先于 semantic scorer 被过滤掉。SQL 预筛不能替代代码级 hard filters，也不能让 LLM、Agent 或数据库查询直接修改 memory。store trace 只能记录 backend、请求过滤项、query anchor/token 数量、是否启用 query 预筛和候选数量，禁止记录具体 query term、memory content 或未选中内容。

Memory v1.2 的 `MemoryProjectionSkill` 和 `MemoryRetrievalPlan` 不是世界状态，不写入 `WorldEvent`，也不参与 replay 权威。它们只是在构造 `AgentContext` 时解释“当前动作、阶段和 completed beats 下应该投影哪些安全记忆”。Plan 可以收窄 memory type/scope/layer、限制条数、关闭画像摘要或 recent events；但不能让 `director_audit`、`archival`、其他 NPC private、其他 NPC portrait 或 forbidden fact 文本进入普通 NPC 上下文。

Memory v1.3 的检索质量分数同样不是世界状态。`MemoryRetriever` 可以在过滤后使用结构化锚点、中文/英文 token、`updated_at` recency、`source_event_ids` reinforcement、salience 和 confidence 做排序，但这些分项不得写入 `memory_candidate.created`、`agent_memory_snapshot.updated`、snapshot `metadata` 或 replay 结果。recency 的“当前时间”来自事件流或已有 snapshot 时间，禁止使用 wall-clock `now()` 影响可复现性。P2 的归档判断同样使用事件流和 snapshot 时间；只有归档事件本身的 `created_at` 由 `EventRecorder` 生成并进入事件日志。

结构化召回规则：`MemoryRetriever` 会从动作字段和玩家文本中提取 clue / world_info / claim 锚点。英文和数字 token 会拆分 snake_case，例如 `scratched_drawer` 可由 `drawer` 或 `scratched` 命中；中文仍按连续文本和 2/3 字窗口分词。只有当本轮没有任何具体结构化锚点时，才允许使用 `target_id` 作为弱锚点。这样可以让 `memory.player.clue_discovered.scratched_drawer` 被 “drawer scratches” 命中，同时避免同一 NPC 可见的 `dustless_frame` 被无关注入。

AgentLoop 中的 `memory_snapshots`、`memory_ids_used`、trace `memory_projection` 和 tool `search_memory` 摘要必须来自同一次注入 retriever 的结果。`build_agent_context(...)` 只有在调用方未传入已检索 snapshot 时才执行内部 fallback 检索；该 fallback 是兼容路径，不是普通 turn 的事实源。

Memory Retrieval Matrix 是评测层，不是世界状态。矩阵只声明某个 `case_id + phase + PlayerAction + target_id` 下 expected / forbidden 的 `memory_id` 集合，并读取 `MemoryRetriever` 或 `AgentContext.memory_snapshots` 的结果做断言。它不得写入 `SessionState`、`WorldEvent`、`AgentMemorySnapshot.metadata` 或 replay 结果。换检索算法、embedding、reranker 或 projection skill 时，应使用同一矩阵确认召回集合没有漂移；如果业务需要锁定排序，必须另加排序评测，不能把排序假设隐式塞进 expected 集合。

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
- 返场线索必须通过 `backtrack_unlocks` 条件和 Rule Engine 解锁，不能只靠 NPC 文案暗示。
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

P0 硬链路要求：prompt、LLM output contract、`disclosure_claims` 和 repair 都不是状态权威。它们只能影响一次 NPC turn 的候选表达。真实状态只来自 `RuleEngine`、`DerivedEventSystem`、`MemorySnapshotSystem`、`MemoryArchivalSystem`、`RuleTriggerSystem` 和 `EventRecorder` 写出的 `WorldEvent`。

不得把这些内容作为 prompt 事实通道交给 LLM：原始 `CasePackage`、原始 `SessionState`、角色原始 `private`、其他 NPC private、`director_audit` memory、未选中 memory content、线索 `truth_status`、forbidden fact 原文、blocked terms、solution claims 和正式指控真相配置。需要给 LLM 的边界只能以 `blocked_fact_ids`、`revealable_fact_ids`、`LLMDisclosureConstraint`、`FactDisclosureStrategy`、safe refs、`must_not_claim` 和 output schema 的形式出现。

集中说明见 `doc/architecture/p0-hard-chain-2026-06-16.md`。

## 泄漏边界

公开摘要不得暴露角色 `secrets`、角色 `goals`、内部角色 `knowledge`、角色事实认知账本、私有角色画像、角色卡 `private` 对象、线索 `truth_status`、禁说事实原文、blocked terms、`forbidden_facts` 或 `solution_claims`。

`StateSummary`、`WorldEvent` payload 和 `player_journey.md` 也不得暴露 `inner_context` 或原始 private summaries。

`director.blocked` 事件可以记录 `world_info_id`、`matched_by`、`detected_directness`、`pattern_id` 等审计元数据，但公开 payload 中的 `matched_text` 必须脱敏，不能把被拦截的禁说词、private 原文或敏感事实原文再次回显给玩家。

## 案件扩写注意事项

`mist_clock_manor` 的 2026-06-14 扩写采用“可选证据厚度层”写法：新增 `Clue` 和 `WorldInfo` 必须挂到新 hotspot、标准路径不检查的 hotspot，或受 `backtrack_unlocks` 控制的返场 hotspot，除非同步更新 `scenarios/standard_path.yaml` 的 `expected_events`、`expected_phase` 和 `expected_player_world_info_ids`。

可选线索允许产生新的 `PlayerKnowledge`，但不能无意成为核心 beat 的 `all_discovered` 条件；核心 phase 推进仍由原六条证据控制。新增公开线索标题、描述和 `WorldInfo.description` 必须按公开摘要处理，不能写 private summary、forbidden blocked term 组合或最终责任链结论。
## NPC Skill WorldEvent 边界

- `npc_skill.selected` 和 `npc_skill.rejected` 是审计事件，不直接改变世界事实、线索、关系或剧情阶段。
- replay 必须保留这些事件在 `SessionState.events` 中；第一阶段没有新增 session projection，因此回放时不产生额外状态副作用。
- selected/rejected 的 `caused_by_event_id` 指向触发本轮 agent-backed turn 的玩家/规则事件，用来还原技能授权与玩家动作之间的因果链。
- payload 必须保持可公开审计的安全投影：只写 skill id、refs、枚举型允许范围和拒绝原因，不写玩家原文、safe fragment summary、角色 private summary、memory content 或 prompt 文本。
- cooldown 状态尚未产品化。`npc_skill.cooldown.updated` 可作为后续恢复型状态事件使用，但在引入前必须定义 replay projection 和测试。
