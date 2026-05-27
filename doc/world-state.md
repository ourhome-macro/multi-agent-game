# 世界状态与数据模型

世界状态由 `SessionState` 承载，案件静态配置由 `CasePackage` 承载。当前全部使用内存存储。

## Case Package

fake case 位于 `cases/fake_case_001` 和 `cases/fake_case_002`：

- `case.yaml`：案件元信息和初始剧情阶段。
- `characters.yaml`：角色设定、秘密、目标和认知。
- `scenes.yaml`：场景、角色和可调查热点。
- `clues.yaml`：线索、真假状态、关联角色和关键性。
- `relationships.yaml`：初始关系。
- `forbidden_facts.yaml`：Director 禁说事实。
- `mock_dialogues.yaml`：mock Agent 回复和关系变化意图。
- `narrative_rules.yaml`：剧情阶段、beat 条件和 phase 推进。

加载时会校验角色、线索、场景、热点、关系和 mock 对话引用。引用错误会抛出 `CaseLoadError`。

命名已经在当前阶段冻结：玩家行为目标使用 `target_id`，关系端点使用 `source_id` 和 `target_id`。

## SessionState

`SessionState` 包含：

- `id`
- `case_id`
- `narrative.phase`
- `narrative.completed_beats`
- `relationships`
- `relationship_thresholds_crossed`
- `discovered_clues`
- `player_knowledge`
- `memory_candidates`
- `events`

`discovered_clues` 是权威线索发现状态；`StateSummary.discovered_clues` 只是从该集合映射出的展示摘要。

`StateSummary.player_knowledge` 是玩家公开认知摘要，只暴露 `knowledge_id`、`clue_id`、`title` 和 `summary`。`StateSummary` 仍禁止泄露角色秘密、角色目标、角色认知、线索真假状态和 Director 禁说事实。

## WorldEvent

所有可回放行为都写入事件：

- `session.created`
- `player.inspected`
- `player.talked`
- `npc.replied`
- `director.blocked`
- `rule.rejected`
- `clue.discovered`
- `relationship.changed`
- `relationship.threshold.crossed`
- `player_knowledge.updated`
- `memory_candidate.created`
- `narrative.beat.completed`
- `narrative.phase.changed`

事件包含 `case_id`、`session_id`、`actor_id`、`type`、`payload`、`caused_by_event_id` 和 `created_at`。

## Rule Engine 写入原则

- `inspect desk` 通过热点配置解锁 `scratched_drawer`。
- `inspect portrait` 通过热点配置解锁 `dustless_frame`。
- 重复发现同一线索不会重复写 `clue.discovered`。
- `clue.discovered` 会派生 `player_knowledge.updated` 和 `memory_candidate.created`。
- Agent 提出的未知线索、未知关系端点或未知关系指标会写 `rule.rejected`，不会污染状态。
- Agent `proposed_actions` 的动作类型由 `ProposedActionType` 白名单约束。
- Agent 提出的 phase change 会写 `rule.rejected`；phase 只能由 `narrative_rules.yaml` 触发。
- relationship metrics 会被 clamp 到 `-1.0 .. 1.0`。阈值首次跨过时写 `relationship.threshold.crossed`，当前硬编码阈值包括 `suspicion >= 0.7`、`fear >= 0.7`、`trust >= 0.7`。
- `director.blocked` 和 `relationship.threshold.crossed` 也会派生 `memory_candidate.created`，当前只生成 player 侧 memory candidate。
- `replay_events(case, events)` 会根据事件日志重建 `SessionState`，用于验证存档和调试链路。
- `truth_status` 支持 YAML 布尔值归一化，但 fake case 中显式写成字符串，避免配置歧义。
