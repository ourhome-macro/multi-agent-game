# Multi-Agent Meeting And Voting V1

## 当前编排

当前多 Agent V1 是场景驱动的确定性世界循环：

```text
TownOrchestrator.tick_once
  -> town.tick.advanced
  -> NpcAutonomyIntent candidate
  -> NarrativeDirector.precheck_npc_autonomy
  -> RuleEngine.apply_npc_autonomy_intent
  -> npc.location.changed / rule.rejected
  -> PerceptionSystem
  -> npc.observed
  -> DerivedEventSystem
  -> memory_candidate.created
  -> MemorySnapshotSystem
  -> agent_memory_snapshot.updated
  -> replay restores town_clock + npc_locations + memory projection
```

它刻意不做全员 LLM tick、不做 NPC 群聊、不让 NPC 直接共享 memory，也不允许 NPC 自主解锁关键线索或推进 phase。这个边界是正确的：先保证位置、可见性、记忆来源、replay 和规则裁决稳定，再引入高价值社交场景。

## 大会议的定位

大会议可以做，但不能成为 town tick 的默认主循环。它应该是一个被剧情阶段、玩家行动或 Director 触发的特殊场景/流程：

```text
player / director triggers meeting
  -> meeting.session.started
  -> meeting.turn.opened
  -> selected NPC speech intent candidates
  -> Director precheck
  -> LLM only for selected speakers
  -> RuleEngine records meeting.message.posted
  -> optional vote.intent.proposed
  -> RuleEngine records vote.cast
  -> Director + RuleEngine evaluate verdict
  -> meeting.verdict.proposed
  -> meeting.verdict.accepted / rejected
  -> narrative.phase.changed only when rule conditions pass
```

会议是“案件审理/公开对质/终局推理”的 UI 和规则容器，不是 NPC 自由聊天容器。

## 必须新增的后端事件

第一版会议需要这些事件，不应直接复用 `npc.replied` 或 `PlayerAction`：

- `meeting.session.started`
- `meeting.session.ended`
- `meeting.turn.opened`
- `meeting.message.proposed`
- `meeting.message.posted`
- `meeting.message.rejected`
- `meeting.vote.opened`
- `meeting.vote.cast`
- `meeting.verdict.proposed`
- `meeting.verdict.accepted`
- `meeting.verdict.rejected`

`meeting.message.proposed` 是候选，不改变事实。`meeting.message.posted` 只是公开发言记录。`meeting.vote.cast` 是角色态度或判断，不等于案件真相。最终裁决必须由 Rule Engine 根据已发现证据、玩家知识、案件 phase 和 solution claim 校验。

## 会议发言权限

V1 不允许全员无限发言。每轮最多选择少量 speaker：

- 玩家当前点名的 NPC。
- 与当前 evidence / topic 直接相关的 NPC。
- 当前场景或会议中可见该事件的 NPC。
- Director 指定的反驳者或关键沉默者。

NPC 发言只能基于：

- 已写入自身 `npc_private` / 可见 `scene_shared` / session memory 的内容。
- 当前会议已经公开的 `meeting.message.posted`。
- 玩家已公开展示的 evidence。
- 案件配置允许的公开角色设定。

NPC 不能因为会议存在就读取全局真相、其他 NPC 私有记忆或 Director 审计内容。

## 投票与最终判决

投票不是状态裁决源，只是叙事压力和角色立场输入。正确顺序是：

```text
meeting.vote.cast
  -> relationship / pressure candidate
  -> meeting.verdict.proposed
  -> RuleEngine validates required_evidence + required_world_info + phase
  -> accepted: accusation.evaluated / narrative.phase.changed
  -> rejected: meeting.verdict.rejected / rule.rejected
```

因此“大家投票认为某人有罪”不能直接让案件 resolved。它最多进入低权威 belief 或关系压力，不能替代证据链。

## 前端形态

前端应该单开一个类似 QQ 群的会议界面，但它不是普通聊天：

- 左侧：会议参与者、当前位置、是否已发言、是否已投票。
- 中间：按事件流渲染消息气泡，来源必须是 `meeting.message.posted`。
- 右侧：证据栏、当前议题、投票面板、裁决按钮。
- 底部：玩家发言输入、展示证据、点名追问、发起投票。

消息 UI 可以像群聊，但交互必须是结构化 action：

- `meeting_speak`
- `meeting_present_evidence`
- `meeting_ask`
- `meeting_open_vote`
- `meeting_cast_vote`
- `meeting_propose_verdict`

前端不得把自由文本群聊直接当成事实更新。所有输入仍要转成结构化 action，再进入 Director + RuleEngine。

## 推荐实现顺序

1. 先做只读会议时间线：从事件流渲染 `meeting.message.posted`。
2. 再做玩家发言和展示证据，后端写 `meeting.message.posted`。
3. 再做 NPC 单轮回应，每轮最多 1-2 个 speaker 调 LLM。
4. 再做投票，投票只写 `meeting.vote.cast`。
5. 最后接 `meeting.verdict.proposed`，由 RuleEngine 决定是否进入正式 accuse / phase change。

不要一开始做全员自由群聊。那会让 memory 权限、线索释放、剧情阶段和 replay 全部失控。

## 2026-06-27 V1 落地状态

已实现第一版可运行闭环：

- 新增结构化会议 action：`meeting_start`、`meeting_speak`、`meeting_present_evidence`、`meeting_ask`、`meeting_open_vote`、`meeting_cast_vote`、`meeting_propose_verdict`。
- 新增会议事件：`meeting.session.started`、`meeting.turn.opened`、`meeting.message.proposed`、`meeting.message.posted`、`meeting.message.rejected`、`meeting.vote.opened`、`meeting.vote.cast`、`meeting.verdict.proposed`、`meeting.verdict.accepted`、`meeting.verdict.rejected`。
- `SessionState.meeting` 保存会议投影：是否活跃、参会 NPC、投票目标、投票记录、裁决状态。消息正文不复制进 state，仍以 WorldEvent 流为权威。
- `RuleEngine.apply_meeting_action(...)` 负责会议动作裁决。`meeting_propose_verdict` 复用 `DeductionEvaluator`，只有证据、玩家知识、phase 和 solution claim 全部通过时，才写正式 `player.accused` / `accusation.evaluated`。
- `ActionService` 对 `meeting_ask` 和 `meeting_open_vote` 只生成确定性 NPC 回应/投票，不调 LLM。
- replay 能还原 `SessionState.meeting`。
- 前端新增 `MeetingPanel`，以 QQ 群组形态展示公开会议事件流，并提交结构化会议 action。

仍未实现：

- 少量 speaker 的 LLM 会议发言。
- 会议消息派生长期 NPC 记忆。
- NPC 对 NPC 的自由辩论。
- 基于会议议程的复杂 turn scheduler。
## 2026-06-27 测试与文档收口切片

本次收口只核对会议 V1 已落地边界，不把下一阶段能力伪装成已完成。当前可确认的代码事实是：会议 action / event / replay 投影已经存在，`meeting_ask` 与 `meeting_open_vote` 仍是确定性路径，`meeting_propose_verdict` 已接 DeductionEvaluator。

### Speaker selector

已实现：

- `meeting_ask` 校验会议已开启与目标 NPC 合法后，会写入玩家的 `meeting.message.posted`。
- `ActionService._deterministic_meeting_reply(...)` 只为被点名的 `target_id` 追加一条 `message_kind=npc_reply` 的 `meeting.message.posted`。
- 公开投影保留 `speaker_id`、`target_id`、`message_kind`，足够前端渲染“谁在会议中发言”。

待实现：

- 还没有 `MeetingSpeakerSelector` 或等价组件；没有基于 topic / evidence / recent meeting messages / NPC 可见 memory 的候选排序。
- 还没有每轮 1-2 个 speaker 的强约束事件或 `selected_speaker_ids` 审计字段。
- 还没有会议 LLM 发言链路。后续只能让 selector 选中的 NPC 生成 `meeting.message.proposed`，再经 Director 与 RuleEngine 后落为 `meeting.message.posted`。
- 还没有会议 turn scheduler；当前 `meeting.turn.opened` 只在会议启动时写第一轮。

### Meeting memory

已实现：

- `meeting.*` 事件可 replay 到 `SessionState.meeting`，消息正文仍以 WorldEvent 为权威，不复制进 `SessionState.meeting`。
- 裁决通过后会写正式 `player.accused` / `accusation.evaluated`，因此可复用既有正式指控记忆派生链路。

待实现：

- `meeting.message.posted` 当前不会派生 `memory_candidate.created`；公开会议发言不会自动形成 `scene_shared` 或 NPC 私有长期记忆。
- 还没有 meeting-specific memory rule，也没有“会议中听到某人发言”的 authority / visibility / decay policy。
- 后续 meeting memory 必须从 `meeting.message.posted` 事件派生，权威建议为 `event_observed` 或明确的低权威 `npc_belief`，不能把投票结果当案件真相。

### 证据多选裁决反馈

已实现：

- `meeting_propose_verdict` 接受 `evidence_clue_ids` 多选列表，并复用 `DeductionEvaluator` 去重、校验 unknown / undiscovered / missing_player_knowledge / missing_required_evidence / missing_required_world_info。
- 裁决失败会写 `meeting.verdict.rejected` 与 `rule.rejected`；其中缺失证据会进入 `missing_required_evidence`。
- 公开事件投影已暴露 `meeting.verdict.rejected.reason` 与 `missing_required_evidence`，可支撑最小前端反馈。

待实现：

- 公开投影还不是完整的 verdict feedback DTO；缺少稳定 `reject_code`、`matched_required_evidence`、`unknown_evidence`、`undiscovered_evidence`、`missing_player_knowledge` 和 `missing_required_world_info` 的统一前端字段。
- `meeting.verdict.accepted` 的公开投影目前只暴露 `result`，没有把 `matched_required_evidence` 作为可解释反馈返回。
- 前端还需要把多选证据反馈映射为“已匹配 / 缺失 / 无效 / 未发现 / 玩家尚未理解”的结构化 UI 状态。

### 测试状态

已有 `tests/test_meeting_v1.py` 覆盖会议启动、点名回复、投票、空证据拒绝、完整证据通过。本次新增 `tests/test_meeting_v1_followup.py`，覆盖“玩家多选了部分证据但证据链不完整时，会议裁决返回缺失证据、公开投影保留反馈、replay 保持 rejected 状态，且不会写正式 `player.accused`”。
