# 前后端剧情节点推进对齐审计（2026-06-27）

## 结论

本项目当前没有单独的“剧情节点运行时表”。剧情推进由后端规则系统围绕 `NarrativeState.phase`、`completed_beats`、`discovered_clues`、`WorldEvent` 执行，前端只消费公开投影和可行动作列表。

核心链路是：

1. 玩家动作进入 `ActionService.handle`。
2. 后端先写玩家事件，例如 `player.inspected`、`player.presented_clue`、`player.accused`。
3. `RuleEngine` 根据动作产生真实状态变化，例如 `clue.discovered`、`accusation.evaluated`。
4. `DerivedEventSystem` 从线索事件派生 `player_knowledge.updated`。
5. `RuleTriggerSystem` 评估 `case.narrative_rules.beats`，满足条件后写 `narrative.beat.completed`，如配置了 `next_phase` 再写 `narrative.phase.changed`。
6. API 把内部状态投影为 `PublicStateSummary`、`PublicEventStreamItem`、`SessionAffordances`。
7. 前端通过 action response 立即更新 `state`，再 invalidates `affordances/events`。

LLM 不能直接推进剧情阶段。`RuleEngine.apply_agent_intent` 会拒绝 `narrative.phase.change` 类型的 LLM proposed action，阶段只能由 `RuleTriggerSystem` 推进。

## 雾钟山庄推进规则

当前标准路径来自 `cases/mist_clock_manor/narrative_rules.yaml`：

| Beat | 所属阶段 | 条件 | 下一阶段 |
| --- | --- | --- | --- |
| `sedative_found` | `opening` | 发现 `bitter_wine` | `investigation` |
| `mechanism_exposed` | `investigation` | 完成 `sedative_found` 且发现 `delayed_lock_marks`、`echo_tape` | `confrontation` |
| `motive_chain_exposed` | `confrontation` | 完成 `mechanism_exposed` 且发现 `burned_confession`、`empty_capsules`、`cut_power_trace` | `reconstruction` |
| `case_solved` | `reconstruction` | 触发 `accusation.evaluated`，payload 为 `target_id=jiang_yanhui`、`claim_id=shared_death_chain`、`result=correct` | `resolved` |

对应前端可操作热点来自 `cases/mist_clock_manor/scenes.yaml`：

- `wine_table` -> `bitter_wine`
- `study_lock` -> `delayed_lock_marks`
- `tape_recorder` -> `echo_tape`
- `burned_letter` -> `burned_confession`
- `medicine_box` -> `empty_capsules`
- `breaker_box` -> `cut_power_trace`

最终裁决门槛来自 `cases/mist_clock_manor/solution_claims.yaml` 的 `shared_death_chain`。它要求阶段为 `reconstruction`，目标为 `jiang_yanhui`，并提交六条核心证据。

## 前后端对齐现状

已对齐的部分：

- 后端公开 `PublicStateSummary.narrative_phase`、`completed_beats`、`discovered_clues`、`player_knowledge`、`evidence_assets`、`meeting`、`event_count`。
- 后端公开 `SessionAffordances.narrative_phase`、`available_hotspot_ids`、`discovered_clue_ids`、`present_clue`、`accuse`、`can_accuse`。
- 前端 `App.tsx` 在 action response 成功后用 `response.state` 更新缓存，并刷新 `affordances/events`。
- 前端 `ActionMenu` 使用 `affordances.ask_about`、`present_clue`、`accuse` 控制角色交互。
- 前端 `SceneRenderer` 使用 `available_hotspot_ids`、`available_character_ids` 控制热点和 NPC 是否可交互。

## 发现的问题

1. 前端构建当前失败。

`web/src/App.tsx` 仍 import `./ui/MeetingPanel`，但当前文件树没有 `web/src/ui/MeetingPanel.tsx`。`npm run build` 报：

```text
src/App.tsx(20,30): error TS2307: Cannot find module './ui/MeetingPanel'
src/App.tsx(262,20): error TS7006: Parameter 'action' implicitly has an 'any' type.
```

这会直接切断会议/裁决 UI；如果依赖会议裁决推进 `case_solved`，前端不可用。

2. 热点“已发现”状态 ID 对不上。

`SceneRenderer` 用 `state.discovered_clues.map(clue => clue.id)` 构建 `discoveredIds`，但渲染热点时判断 `discoveredIds.has(hotspot.id)`。实际配置里 hotspot ID 是 `wine_table`，clue ID 是 `bitter_wine`，两者不是同一命名空间。因此热点已发现视觉状态会长期不准确。

3. `available_hotspot_ids` 当前等同所有 hotspot。

`build_session_affordances` 把所有 hotspot 都返回给前端，没有按阶段、已发现或空间约束过滤。规则层能保证重复检查不会重复写 `clue.discovered`，但前端无法区分“未检查、已检查、阶段锁定、可回溯再查”。

4. `claim_id` 没有暴露给普通指控 affordance。

后端 `AccuseAffordance` 只给 `target_id` 和 `evidence_clue_ids`，不暴露 `claim_id`。前端 `ActionMenu` 提交普通 `accuse` 时不带 `claim_id`。这依赖后端默认按 target 找第一条 claim。对 `jiang_yanhui` 目前能工作，但如果一个目标未来有多个可判定 claim，前端无法明确选择剧情节点。

5. 前端没有展示 `narrative_phase` 和 `completed_beats` 的明确进度。

状态已有字段，但 UI 主要展示固定文案和玩家知识列表。玩家能感到“线索增加”，但看不到当前阶段、已完成 beat、下一步调查目标。生产上这会让规则推进是正确的，但体验层不透明。

6. 前端中文文案存在明显乱码。

多个 TSX 文件中中文已显示为 mojibake。即使业务链路正确，生产体验和测试可读性都会受影响。

## 建议

优先级最高的是恢复前端构建：补回或移除 `MeetingPanel`，并为 `onAction` 参数补类型。

第二优先级是修正热点发现状态：后端可以在 public case detail 中给 hotspot 增加公开的 `discover_clue_ids`，或在前端建立 `hotspot_id -> clue_ids` 映射。不要用 clue ID 直接匹配 hotspot ID。

第三优先级是把剧情进度显式化：前端顶部或日志面板展示 `narrative_phase`、`completed_beats` 和最近的 `narrative.phase.changed`。这些都应来自后端投影，不要在前端复制剧情规则。

第四优先级是指控契约升级：如果未来一个目标存在多个 claim，应让 `AccuseAffordance` 暴露稳定的公开 claim 选择字段，或者后端按当前 phase 返回唯一可用 claim 并在不可唯一时拒绝生成 affordance。

第五优先级是补一个前端契约测试或构建门禁：至少覆盖 `PublicStateSummary`、`SessionAffordances` 与 `public-api.ts` 的字段一致性，以及 `npm run build`。
