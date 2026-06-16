# NPC Skill System Plan

生成时间：2026-06-16

## 结论

项目需要 NPC Skill 系统，而且它应该是一等领域模型，不应该只是 prompt 文案。

Codex skill 是开发 Agent 的工作手册；NPC Skill 是游戏运行时里的角色能力、话术、调查手段、社交策略和剧情权限。两者不是同一种东西。

对这个悬疑叙事系统来说，NPC Skill 的核心价值不是“让 NPC 会更多招式”，而是做渐进式披露：

```text
NPC 会什么
  -> 当前剧情阶段能不能用
  -> 当前玩家证据/关系/压力是否满足条件
  -> 这项 skill 最多能暴露哪些 safe fragment
  -> LLM 只能表达 skill attempt
  -> Rule Engine / Director 决定是否生效和是否安全
  -> WorldEvent 记录 skill 使用、失败、升级、冷却和后果
```

## 当前系统缺口

当前项目已经有几块和 NPC Skill 相邻的能力：

- `CharacterPrivateConfig.goals/secrets/knowledge`
- `CharacterDisclosureStyleConfig`
- `CharacterFactAwarenessState`
- `FactDisclosureStrategy`
- `MemoryRetrievalPlan`
- `AgentMemorySnapshot(memory_type=strategy)`
- `NarrativeDirector.safe_fragment_constraints(...)`
- `AgentIntent.intent`
- `AgentIntent.proposed_actions`

但这些还不是 NPC Skill。现在缺的是：

- 没有结构化 `NpcSkillConfig`。
- 没有 skill unlock / level / cooldown / failure reason。
- 没有 skill attempt 事件。
- 没有 skill 与 safe fragment 的绑定。
- 没有 skill 与 memory retrieval plan 的绑定。
- 没有 skill 对 `AgentIntent` 输出合同的约束。
- 没有 skill 级回归评测。

直接把这些能力写进 prompt 会产生根本问题：模型会把“技能描述”误当成权限，提前说出事实、绕过阶段、跳过证据条件或凭空改变关系。

## 领域定位

NPC Skill 是角色行为能力，不是状态权威。

它应该表达：

- 这个 NPC 擅长什么。
- 当前是否允许尝试。
- 尝试时可以使用哪些记忆、事实片段和话术。
- 尝试成功或失败后，最多能提出哪些状态变化。

它不应该表达：

- 真相是否成立。
- 线索是否解锁。
- 玩家是否通关。
- 关系数值一定如何变化。
- 剧情阶段是否推进。

权威边界仍然是：

```text
LLM / MockAgent
  -> skill attempt / speech / proposed_actions
Narrative Director
  -> fact and spoiler safety
Rule Engine
  -> legality and state mutation
WorldEvent
  -> replayable truth
```

## Superpower 设计原则

NPC Skill 需要参考 superpower 设计原则，但不能照搬成“角色拥有超权限”。在这个项目里，superpower 的含义是：每个重要 NPC 有一个强辨识度、可反复触发、会改变互动策略的核心能力。

它解决的是可玩性问题：

- 玩家能感知“这个 NPC 和别人不一样”。
- 同一个 NPC 在不同阶段会呈现能力升级或崩坏。
- 玩家可以学习、利用、反制这个 NPC 的行为模式。
- 能力天然服务于线索释放、误导、关系变化和剧情节奏。

它不能解决状态权威问题：

- superpower 不能直接改世界事实。
- superpower 不能直接解锁隐藏证据。
- superpower 不能直接决定指控正确。
- superpower 不能绕过 Director 披露边界。
- superpower 不能让 NPC 访问自己视角之外的秘密。

正确公式是：

```text
Superpower = 高辨识度行为模式 + 可升级触发条件 + 可审计限制
```

不是：

```text
Superpower = LLM 可以随便做某类事
```

### 每个 NPC 至少一个 Signature Skill

主线 NPC 应该至少有一个 signature skill。它不是战斗技能，而是叙事交互能力。

示例：

- 擅长把问题引向无害细节。
- 擅长用情绪压迫玩家放弃追问。
- 擅长记住玩家前后矛盾。
- 擅长提供局部真话来隐藏完整因果。
- 擅长把一条证据解释成另一个嫌疑人的动机。
- 擅长在高压下沉默，让其他 NPC 暴露更多。

signature skill 应该满足：

- 能被玩家观察出来。
- 能被多次触发，但不会每次产生同样台词。
- 有明确弱点或反制条件。
- 有阶段升级。
- 有明确 disclosure 上限。

### Skill 必须有弱点

没有弱点的 NPC Skill 会变成万能 prompt。每个 skill 都应定义至少一个 counter。

counter 可以是：

- 玩家已发现某个 clue。
- 玩家已建立某条 player knowledge。
- 关系压力超过阈值。
- NPC 恐惧值过高。
- 某个 beat 已完成。
- 另一个 NPC 的证词已公开。
- 玩家连续追问同一矛盾。

示例：

```yaml
counters:
  required_player_knowledge:
    - player_knowledge.timeline_contradiction
  min_interaction_pressure: 0.7
  effect:
    max_mode_override: partial
    disable_tactics:
      - shift_focus
```

### Skill 要分等级

superpower 不是静态标签。它应该随剧情推进分层：

```text
level 0: 玩家不可见，LLM 不知道
level 1: 基础行为模式，只能 deny / deflect
level 2: 玩家掌握证据后，可 hint
level 3: 对质阶段，可 partial
level 4: 结局后，可 full reconstruction
```

注意：`level 4` 的 full reconstruction 只能发生在结局/复盘专用链路，不能进入普通 NPC turn。

### Skill 要能被玩家学习

前端不应该直接显示隐藏 skill 名称，但应该能逐步暴露玩家观察到的行为倾向。

公开投影可以是：

```text
你注意到：林栖迟在被问到药物时，会先承认无害事实，再把话题转向陆澜生。
```

这种公开观察应该来自事件和玩家经历，不来自角色卡隐藏字段。

### Skill 要服务悬疑节奏

每个 signature skill 都要绑定叙事目的：

- 延迟核心真相。
- 暴露一条安全事实片段。
- 制造可验证矛盾。
- 让玩家形成错误假设。
- 给玩家反制 NPC 的机会。
- 把玩家引向下一个调查目标。

如果一个 skill 只让 NPC “更会说话”，但不影响线索节奏、关系策略或玩家推理，它不值得进入系统。

### Skill 不等于工具调用

NPC Skill 可以提出工具式意图，但不能直接执行工具。比如：

```text
NPC 使用 point_to_safe_clue
  -> LLM 表达“你不如看看那只药盒”
  -> proposed_actions: clue.discover(...)
  -> Rule Engine 检查地点、阶段、触发条件、重复性
  -> 允许后写 clue.discovered
```

这和“LLM 调用 reveal_clue 工具直接解锁”是两回事。

## Skill 类型

建议第一版支持五类 NPC Skill。

### 1. Dialogue Skill

用于控制 NPC 话术策略。

例子：

- `deflect_with_adjacent_truth`
- `pressure_counter_question`
- `controlled_partial_confession`
- `panic_silence`
- `emotional_screen`

影响：

- 允许的 `AgentIntent.intent`
- 允许的 `RhetoricTactic`
- 允许的 `DisclosureMode`
- 输出是否必须带 `disclosure_claims`

不直接产生状态变化。

### 2. Social Skill

用于 NPC 对玩家或其他角色的社交行动。

例子：

- `probe_player_theory`
- `build_trust`
- `intimidate_player`
- `misdirect_suspicion`
- `test_player_evidence`

影响：

- 可提出 `relationship.change`
- 可生成 `memory_candidate.created(strategy/belief)`
- 可更新 NPC 对玩家画像

必须由 Rule Engine 裁决。

### 3. Investigation Skill

用于 NPC 协助、误导或阻碍调查。

例子：

- `offer_minor_observation`
- `hide_access_route`
- `reframe_evidence`
- `point_to_safe_clue`
- `withhold_key_context`

影响：

- 可能提出 `clue.discover`
- 可能触发 safe fragment 披露
- 可能要求玩家已有某个 clue / world_info / beat

不能直接解锁隐藏证据，必须走 Rule Engine。

### 4. Memory Skill

用于决定本轮该角色如何检索和使用记忆。

例子：

- `recall_player_pressure_pattern`
- `recall_prior_contradiction`
- `track_presented_evidence`
- `remember_betrayal`

影响：

- `MemoryRetrievalPlan.included_memory_types`
- `included_scopes`
- `topic_tags`
- `required_source_event_ids`
- `max_memory_items`

不能无相关命中时按 salience fallback。

### 5. Plot-Gated Skill

用于剧情阶段推进后的高阶能力。

例子：

- `partial_confession_after_confrontation`
- `negotiate_after_key_evidence`
- `collapse_under_complete_chain`
- `reveal_motive_fragment`

影响：

- 绑定 `phase_ids`
- 绑定 `completed_beats`
- 绑定 `required_player_knowledge`
- 绑定 `safe_fragment_refs`

必须由 Narrative Director 控制事实上限。

## 数据模型草案

建议在案件包新增：

```text
cases/<case_id>/npc_skills.yaml
```

草案：

```yaml
- id: deflect_with_adjacent_truth
  owner_character_ids:
    - lin_qichi
  type: dialogue
  level: 1
  priority: medium
  triggers:
    action_types:
      - ask_about
      - present_clue
    subject_types:
      - clue
    topic_tags:
      - medicine
      - relationship_pressure
  unlock_conditions:
    phases:
      - investigation
      - confrontation
    required_player_knowledge:
      - player_knowledge.bitter_wine
    required_relationship:
      suspicion_min: 0.2
    required_pressure_min: 0.4
  disclosure:
    world_info_ids:
      - sedative_wine_chain
    max_mode: hint
    allowed_tactics:
      - answer_adjacent_truth
      - shift_focus
    safe_fragment_refs:
      - sedative_wine_chain.safe_fragment:wine_was_bitter
    forbidden_claim_refs:
      - murderer_identity
      - complete_death_chain
  memory:
    include_types:
      - belief
      - relationship
      - strategy
    include_scopes:
      - npc_private
      - scene_shared
    topic_tags:
      - medicine
      - pressure
    max_items: 3
  proposed_action_policy:
    allowed:
      - relationship.change
    max_relationship_delta:
      suspicion: 0.2
      trust: 0.1
  cooldown:
    turns: 2
  failure:
    fallback_skill_id: cautious_refusal
```

注意：`safe_fragment_refs` 是授权片段引用，不是事实原文。skill 文件不得包含 forbidden fact 原文、solution claim 原文或完整真相推断。

## 运行时投影

`AgentContext` 不应直接塞完整 skill 配置。应该投影成安全 `NpcSkillProjection`：

```python
class NpcSkillProjection(APIModel):
    skill_id: str
    type: str
    level: int
    allowed_intents: list[AgentIntentType]
    allowed_tactics: list[RhetoricTactic]
    max_disclosure_mode_by_world_info: dict[str, DisclosureMode]
    safe_fragment_refs: list[str]
    memory_plan_id: str | None
    allowed_proposed_actions: list[ProposedActionType]
```

投影里只能出现：

- id
- 类型
- 当前可用等级
- 允许 intent / tactic / disclosure mode
- safe fragment ref
- memory plan 摘要
- allowed proposed action 类型

不能出现：

- skill 的完整剧情解释
- locked condition 的未满足原因全文
- forbidden inference 原文
- solution claim 原文
- 其他 NPC private

## 渐进式披露模型

NPC Skill 应该采用四层渐进式披露：

### Layer 0: Skill Exists

角色拥有这项能力，但当前不可用。LLM 不应看到它。

用途：

- 角色卡/案件包定义能力。
- 运行时只用于判断是否未来可解锁。

### Layer 1: Skill Available

条件满足，skill 可被选择。LLM 可看到 skill id、类型和允许策略。

不能看到：

- 为什么这个 skill 在案件真相中重要。
- 它最终能通向什么完整秘密。

### Layer 2: Skill Activated

本轮动作触发该 skill。LLM 可获得：

- 允许的话术策略。
- 允许的 disclosure mode。
- 当前 safe fragment refs。
- 本轮 memory plan。

此时仍不能看到 locked fragment 或 forbidden inference。

### Layer 3: Skill Consequence

LLM 输出后，Director 和 Rule Engine 判定：

- 台词是否安全。
- proposed action 是否允许。
- 是否写入 `npc_skill.used`
- 是否写入 `relationship.change`
- 是否派生 memory
- 是否进入 cooldown

真实状态只由 WorldEvent 表示。

## 事件模型

建议新增事件类型：

```text
npc_skill.selected
npc_skill.used
npc_skill.failed
npc_skill.cooldown_started
npc_skill.unlocked
npc_skill.level_changed
```

最小 P0 可以只做两个：

```text
npc_skill.used
npc_skill.failed
```

事件 payload 示例：

```json
{
  "skill_id": "deflect_with_adjacent_truth",
  "character_id": "lin_qichi",
  "trigger_action_event_id": "evt_...",
  "phase_id": "investigation",
  "selected_safe_fragment_refs": [
    "sedative_wine_chain.safe_fragment:wine_was_bitter"
  ],
  "selected_memory_ids": [
    "mem_lin_qichi_pressure_pattern"
  ],
  "result": "director_blocked",
  "reason_category": "forbidden_inference_risk"
}
```

事件 payload 不得包含安全片段正文、禁说词或 private 原文。

## 与 Director 的关系

NPC Skill 不能绕过 Director。正确链路是：

```text
SkillSelector
  -> selects candidate skills
SkillProjector
  -> emits safe NpcSkillProjection
NarrativeDirector.safe_fragment_constraints
  -> intersects skill safe_fragment_refs with current unlock state
LLMAgentContractInput
  -> includes only allowed skill projections and safe refs
NarrativeDirector.validate
  -> audits final speech
```

Skill 的 `disclosure.max_mode` 只是上限之一。最终上限必须取交集：

```text
character self-knowledge policy
fact_disclosure_strategy
director safe_fragment unlock
npc_skill disclosure policy
current player action pressure
current narrative phase
```

任何一个边界更窄，就采用更窄边界。

## 与 Memory 的关系

Memory Skill 应该控制检索计划，但不能直接返回记忆内容。

正确链路：

```text
PlayerAction
  -> SkillSelector
  -> selected memory skill
  -> MemoryRetrievalPlan constraints
  -> MemoryRetriever hard filter
  -> selected AgentMemorySnapshot
  -> AgentContext
```

Skill 可以要求：

- 只检索 `strategy` 记忆。
- 只检索当前 NPC private 记忆。
- 只检索带 `topic_tags` 的记忆。
- 限制 `max_items`。

Skill 不能要求：

- 忽略 visibility。
- 忽略 source_event_ids。
- 忽略 phase。
- 无相关命中时按 salience fallback。

## 与 Rule Engine 的关系

LLM 可以表达 skill attempt，但不能让 skill 自动成功。

Rule Engine 要检查：

- skill 是否属于当前 NPC。
- skill 是否当前解锁。
- skill 是否在 cooldown。
- trigger action 是否匹配。
- proposed action 类型是否在 skill 白名单内。
- proposed delta 是否超过 skill 上限。
- skill 使用是否会重复写入同类事件。

示例：

```text
AgentIntent.proposed_actions contains relationship.change
  -> RuleEngine checks selected_skill.allowed_proposed_actions
  -> clamps or rejects relationship delta
  -> writes relationship.changed or rule.rejected
```

## 与 LLM 输出合同的关系

长期应该把 skill 进入输出合同，而不是只藏在 prompt：

```json
{
  "speech": "...",
  "intent": "conceal",
  "used_skill_ids": ["deflect_with_adjacent_truth"],
  "emotional_shift": {},
  "proposed_actions": [],
  "memory_refs": ["mem_..."],
  "disclosure_claims": [...]
}
```

P0 可以暂时不改 `AgentIntent`，在 trace 中记录 selected skill；P1 再把 `used_skill_ids` 加入合同并由 schema 和 Python 校验。

## Authoring 规则

案件作者编写 NPC Skill 时必须遵守：

- skill 不写完整案件真相。
- skill 不写 forbidden fact 原文。
- skill 不写 solution claim 原文。
- skill 只能引用 `world_info_id`、`claim_id`、`safe_fragment_ref`、`clue_id`。
- skill 的 unlock condition 必须结构化。
- skill 的效果必须是候选动作或披露上限，不能是最终状态。
- 每个 plot-gated skill 必须有至少一个回归测试。

## P0 实现顺序

### P0.1 数据模型

新增：

- `NpcSkillConfig`
- `NpcSkillTriggerConfig`
- `NpcSkillUnlockCondition`
- `NpcSkillDisclosurePolicy`
- `NpcSkillMemoryPolicy`
- `NpcSkillProposedActionPolicy`
- `NpcSkillProjection`

案件包加载 `npc_skills.yaml`。

### P0.2 SkillSelector

输入：

- case
- session
- PlayerAction
- target_character_id

输出：

- selected skill ids
- rejected skill ids with reason category
- safe projection

不能把 rejected reason 原文交给 LLM，只能进 trace。

### P0.3 Director 交集

把 selected skill 的 safe fragment refs 与 `NarrativeDirector.safe_fragment_constraints(...)` 求交集。

只有交集结果进入 `LLMAgentContractInput`。

### P0.4 Trace

Runtime trace 增加：

- `selected_skill_ids`
- `available_skill_ids`
- `rejected_skill_reasons`
- `skill_safe_fragment_refs`
- `skill_memory_plan_id`

不记录正文。

### P0.5 Tests

必须覆盖：

- 未解锁 skill 不进入 AgentContext。
- 已解锁 skill 只投影 safe refs，不投影事实正文。
- skill safe refs 与 Director refs 求交集。
- cooldown skill 不可选。
- proposed action 超出 skill policy 被 Rule Engine 拒绝。
- phase 变化后 plot-gated skill 可用。

## P1 演进

P1 再做：

- `used_skill_ids` 进入 `AgentIntent`。
- `npc_skill.used/failed` 事件落库。
- skill cooldown / level progression。
- skill 级 memory retrieval plan。
- skill 级回归评测矩阵。
- 前端人物面板展示玩家已观察到的 NPC 行为倾向，但不展示隐藏 skill。

## 不建议做的方案

不要把 NPC Skill 做成：

- 角色卡里的一段自然语言。
- prompt 里的“你可以使用以下技能”。
- LLM 自行决定 cooldown 和解锁。
- 直接修改关系或线索的工具。
- 可以读取完整 world truth 的技能。

这些都会破坏当前项目最重要的边界：AI 负责表达，系统负责真相。
