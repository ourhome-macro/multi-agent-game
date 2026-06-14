# Narrative Director

当前 Narrative Director 是一个最小防剧透安全层。它会在 NPC 台词写入 `npc.replied` 事件之前校验文本。它不推进剧情阶段，也不完成 beats；这些仍由 `narrative_rules.yaml` 和 `RuleTriggerSystem` 负责。

## 玩家动作前置检查

`NarrativeDirector.precheck_player_action(case, session, action)` 是一个纯决策辅助方法，用于在自然语言 Router 产出 `PlayerAction` 后检查明显越界的玩家动作。

当前检查包括：

- `ask_about` 询问未发现线索时返回 `subject_not_discovered`
- `present_clue` 展示未发现线索时返回 `clue_not_discovered`
- `accuse` 使用当前阶段不可用的 claim 时返回 `claim_not_available`
- `accuse` 缺少证据或证据未发现时返回 `insufficient_evidence` / `evidence_not_discovered`

这个方法不写入 `WorldEvent`，也不替代 Rule Engine。正式状态权威仍然由 `RuleEngine.apply_*` 写入 `rule.rejected`、`player.asked_about`、`player.presented_clue`、`player.accused` 等事件。

这样做的目的是让 Router 集成层可以提前获得安全决策摘要，同时保持事件日志和状态变化只有一个权威来源。

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

`NarrativeDirector.validate(case, narrative, intent, context)` 会在 NPC 回复写入事件前执行三类检查：

1. 禁说词检查：如果台词在 `reveal_phase` 之前包含某个禁说事实的 `blocked_terms`，Director 会拒绝该回复。
2. 事实披露检查：如果 `AgentIntent.disclosure_claims` 声明了某个 `WorldInfo` 的披露行为，Director 会对照目标 NPC 当前的 `FactDisclosureStrategy` 校验。
3. 最终台词审计：Director 会独立检测 `speech` 是否命中 `WorldInfo.title`、`WorldInfo.aliases`、`WorldInfo.claim_patterns` 或禁说词映射的事实锚点。

事实披露检查会拒绝：

- `world_info_id` 没有对应策略约束。
- `mode` 不在 `allowed_modes`。
- `mode` 出现在 `forbidden_modes`。
- `mode=full`。
- `claim_refs` 命中 `must_not_claim`。
- 台词触碰某个 `WorldInfo`，但没有提交对应 `disclosure_claim`。
- claim 声明为 `hint`、`deny` 或 `deflect`，但台词实际命中直接事实表达。
- claim 只声明了事实 A，但台词实际触碰事实 B。

`disclosure_claims` 是 Agent 自报；`speech detection` 是 Director 自查。两者不一致时，以 Director block 为准。LLM 不能通过“claim 写 hint，但 speech 直接揭露事实”的方式绕过披露边界。

当前 `detect_world_info_mentions` 会返回：

- `world_info_id`
- `matched_by`：`title`、`alias`、`pattern` 或 `forbidden_term`
- `matched_text` 或 `pattern_id`
- `directness`：`hint_like` 或 `direct_claim`

v0 采用保守策略：命中 title、alias、claim pattern 或 forbidden term 都视为 `direct_claim`。如果无法确定是否只是暗示，先按更安全的直接触碰处理。

被阻止时：

- 不写入 `npc.replied`
- 写入 `director.blocked`
- 响应返回安全台词
- `ActionResponse.accepted=false`

`director.blocked` 可以包含 blocked fact id、`world_info_id`、`claimed_mode`、`detected_directness`、`matched_by`、`pattern_id` 和 `safe_fallback_used` 用于审计，但不得包含禁说事实原文、blocked terms 或 private 原文。公开 payload 中的 `matched_text` 必须脱敏。

## 角色 private 披露边界

角色 `private` 数据是目标 NPC 自己的非公开视角，不是对 NPC 自己隐藏。目标 NPC 永远知道自己的 private goals、secrets 和 knowledge。

运行时限制的是对外台词、公开投影、其他 NPC 可见性和权威状态写入。`private` 不是永久禁言，也不同于 `forbidden_facts`。

`CharacterInnerContext` v0 会把目标 NPC 专属的受控自我视图传入 `AgentContext.inner_context`。它不会传入其他 NPC 的 private 数据，也不会把 private 数据写入公开运行时输出。对外表达仍必须通过 Narrative Director 校验。

Director 当前已经消费 `CharacterInnerContext.fact_disclosure_strategies`，把生成前的策略约束变成生成后的执法规则。Agent 或 LLM 可以选择话术，但不能自己决定事实披露边界。

后续 Director 仍应进一步检查生成台词是否：

- 透露锁定的禁说事实
- 在只允许回避、暗示或部分披露时引用 private 原文
- 与案件锚点、玩家已解锁知识或剧情阶段冲突
- 未经允许把一个 NPC 的 private 数据暴露给另一个 NPC

## Rule Engine 边界

Narrative Director 只判断台词是否安全，不负责让状态变化生效。

Rule Engine 仍负责决定 `AgentIntent.proposed_actions` 是否变成真实 `WorldEvent`。知道 private 信息不代表 NPC 可以直接修改世界状态、线索状态、关系状态、记忆快照或剧情阶段。

## Shadow Eval 边界

LLM Shadow Eval v0 会调用同一个 `NarrativeDirector.validate(case, narrative, intent, context)`，但它不会写入 `director.blocked` 事件，也不会把安全降级台词提交给 runtime。影子评测只记录：

- `director_decision`
- `blocked_reason`
- `safe_fallback_used`
- `disclosure_claims`
- `speech_touched_world_info`
- `missing_disclosure_claim`
- `rejected_world_info_ids`
- `state_unchanged`

这意味着 Director 在影子评测中仍是唯一审计门，但不是状态写入者。任何 block 只进入 `doc/case/<case_id>/llm_shadow_report.json` 和 `.md`，不能影响当前 `SessionState`、玩家已知、NPC 认知或剧情阶段。

影子报告不得包含 forbidden fact 原文、blocked terms、private 原文或 solution claim 公开文本。候选 `speech` 不公开写入报告，只记录长度和脱敏标记；玩家 action 自由文本也只记录长度和脱敏标记。

## 当前限制

当前事实触碰检测仍是保守的文本匹配检查，不是完整语义理解。它能防止 LLM 明确命中受控 `WorldInfo` 的 title、alias、claim pattern 或 forbidden term 却不提交声明，也能防止低披露 claim 包装直接事实台词，但还不能识别所有隐喻、多跳推断或跨事实组合泄漏。

因此真实 LLM 接入后仍需要继续增强：

- 语义级事实触碰分类。
- 多个 `WorldInfo` 组合成核心真相的检查。
- private 原文和近似复述检测。
- 不同剧情阶段下的动态披露上限。

## 案件文本编写约束

`mist_clock_manor` 扩写后的可选线索同样会进入 `StateSummary` 和玩家旅程输出。案件作者不能把禁说事实挪到 clue title、clue description 或公开 `WorldInfo.description` 中规避 Director，因为这些字段本身就是公开投影内容。

新增 mock dialogue 要避免直接复用 `WorldInfo.title`、`aliases` 或 `claim_patterns` 中的完整表达；如果将来需要让 NPC 在允许范围内触碰这些事实，必须让 Agent 输出匹配的 `disclosure_claims`，并通过 Director 校验。
