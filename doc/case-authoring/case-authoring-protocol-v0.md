# 案件编写协议 v0

## 证据与事实图校验门槛

案件包现在把 evidence / claim graph 一致性视为加载期硬门槛，而不是运行时兜底。

必要校验：

- 每个可到达 `Clue` 必须设置 `reveals_world_info`，并指向已声明的 `WorldInfo`。
- 每个 `WorldInfo` 必须至少被线索、角色 private 状态、forbidden fact、solution claim 或 claim graph 条件引用。完全孤立的事实会被拒绝，因为事件日志无法审计它如何进入剧情。
- `claim_graph.safe_fragments[*].unlock_conditions` 只能引用已声明 phase、completed beat、已声明 clue、玩家 world info id，以及能由线索发现实际产生的 player knowledge id。
- `sensitivity=high` 的 `WorldInfo` safe fragment 必须设置非空 `unlock_conditions`；否则视为早期泄密风险。
- `claim_graph.forbidden_inferences[*].trigger_fragment_ids` 必须引用同一 `WorldInfo` 下的 safe fragment，且 forbidden inference id 不能与 safe fragment id 冲突。
- 每个 `solution_claim` 必须定义非空 `required_evidence` 和 `required_world_info`。required evidence 必须可到达，required world info 必须能由这组 evidence 产生。

失败信息必须带 owning field 和 id，例如 `Solution claim 'shared_death_chain' required_world_info ...` 或 `WorldInfo 'killer_fact' safe fragment 'identity_hint' ...`。作者应该修案件图谱，不能靠 prompt 文案或运行时特殊分支补洞。

## 定位

这份文档不是代码协议，也不是 YAML 字段手册。字段级规则仍看 `doc/case-authoring/case-package-protocol.md`。

这里定义的是案件创作顺序、事实拆分方法、剧情闭环标准和验收口径。目标是让第一个真实案件能稳定落进当前后端运行时，而不是边写案件边发明新系统。

一句话：先把案件写成可运行、可审计、可回归的 Case Package，再考虑 LLM 表现力。

## 本阶段边界

当前阶段只做案件无关运行时上的第一个真实案件 v0。

不做：

- NPC-NPC 社交模拟。
- 结盟、背叛、串供系统。
- 真实 LLM 接入。
- 向量记忆。
- 数据库持久化。
- 开放世界多日程模拟。
- 复杂前端。

必须保持：

- LLM 或 MockAgent 只输出表达和意图。
- 世界状态只由 Rule Engine / DerivedEventSystem / RuleTriggerSystem 修改。
- 所有状态变化必须写 `WorldEvent`。
- 玩家已知必须锚定 `WorldInfo`。
- 角色 private 认知必须锚定 `WorldInfo`。
- Director 必须能阻止过早剧透。
- 完整案件路径必须有剧情级回归测试。

## 推荐编写顺序

不要先写对话。先写真相结构。

推荐顺序：

```text
1. 写案件核心谜题
2. 拆 WorldInfo
3. 写线索 Clue
4. 写场景与调查热点
5. 写角色公开卡
6. 写角色 private 认知
7. 写 forbidden facts
8. 写 solution claims
9. 写 narrative beats / phases
10. 写 mock dialogues
11. 写标准玩家路径
12. 写剧情级回归评测
```

如果顺序反过来，最常见的问题是：对话很好看，但系统不知道哪些信息该被记录、禁说、推进或回放。

## 第一步：案件核心谜题

先用短文写清楚案件真相，不进 YAML。

最少回答：

- 谁死了或发生了什么异常事件？
- 真正发生了什么？
- 玩家最终需要证明什么？
- 哪些角色知道真相、误解真相、试图隐瞒真相？
- 哪些证据能让玩家从怀疑走向指控？
- 哪些事实必须在后期才能说？

建议控制在 300 到 800 字。这个文本只供创作使用，不应直接进入 `StateSummary`、AgentContext 或玩家输出。

## 第二步：拆 WorldInfo

`WorldInfo` 是事实锚点，不是线索文本。

拆分原则：

- 每个 `WorldInfo` 表示一个可被知道、隐藏、误解、证明或禁说的事实。
- 一个事实只写一个稳定 ID。
- 不要把证据和解释混在一起。
- 不要把最终真相写成一个巨大 `WorldInfo`，要拆成可逐步发现的事实链。

推荐至少包含四类：

- 物理事实：现场发生过什么。
- 行动事实：某角色做过什么。
- 认知事实：某角色知道或误解什么。
- 核心真相：最终谜题相关事实。

例子：

```text
不要写：
  killer_truth = 管家调换遗嘱并杀了死者

应该拆成：
  desk_forced_open
  will_swapped
  butler_entered_study
  victim_met_someone_at_ten
  killer_is_butler
```

## 第三步：写线索 Clue

`Clue` 是玩家能发现的证据。它通过 `reveals_world_info` 指向事实锚点。

规则：

- 每个关键 `WorldInfo` 至少要有一个可达线索、对话或指控路径支持。
- 线索描述只写玩家看见什么，不直接替系统下最终结论。
- `truth_status` 可以帮助内部校验，但不能作为玩家公开真相。
- `key=true` 用于提升交互压力，不代表自动结案。

好的线索写法：

```text
抽屉锁孔旁有新鲜划痕。
reveals_world_info:
  - desk_forced_open
```

坏的线索写法：

```text
抽屉划痕证明管家偷走了遗嘱。
```

后者把证据、推理和结论混在一起，会让 Director、Rule Engine 和玩家已知账本都变脏。

## 第四步：写场景与热点

场景和热点只负责让线索可发现。

每个关键线索必须回答：

- 玩家在哪里发现？
- 通过哪个 hotspot 发现？
- 是否一开始可发现？
- 是否需要前置剧情阶段？

当前 v0 还没有复杂条件探索系统，所以先保持简单可达。不要把关键线索藏在未来还不存在的系统里。

## 第五步：写角色公开卡

公开角色卡只写玩家一开始合理可见的信息：

- display_name
- public_role
- public_description
- speech style
- personality traits
- defensive style

不要在公开卡里写：

- 真凶。
- 私人秘密。
- 角色真正动机。
- 案件核心解释。
- 只有该角色自己知道的事实。

公开卡是玩家视野，不是作者笔记。

## 第六步：写角色 private 认知

角色 private 分三类：

- `goals`：角色想达成什么。
- `secrets`：角色有理由隐藏什么。
- `knowledge`：角色从自身视角知道什么。

每个 private item 必须优先绑定 `related_world_info_ids`。

规则：

- `related_clue_ids` 可保留，但只是证据触发兼容。
- `related_world_info_ids` 才是事实锚点。
- secret 默认会形成 `stance=conceals`。
- knowledge 默认会形成 `stance=knows`。
- 同一事实既是 secret 又是 knowledge 时，表达策略按更保守的 `conceals` 处理。

重点：private 不是永久禁言。它表示 NPC 自己知道或在意什么；是否能说、说到哪里，由 `FactDisclosureStrategy` 和 Director 决定。

## 第七步：写 forbidden facts

`forbidden_facts.yaml` 只放真正会破坏悬疑结构的禁说内容。

每条 forbidden fact 必须绑定：

- `id`
- `world_info_id`
- `text`
- `blocked_terms`
- `reveal_phase`

原则：

- `blocked_terms` 是后置兜底，不是事实本体。
- `text` 和 `blocked_terms` 不得进入 AgentContext 或公开输出。
- reveal_phase 之前，NPC 即使知道也不能直接说。
- Director block 时只允许返回安全降级台词。

不要把所有秘密都塞进 forbidden facts。普通隐瞒交给角色 private + disclosure strategy；真正剧透才放 forbidden facts。

## 第八步：写 solution claims

`solution_claims.yaml` 定义正式指控，不定义自然语言争辩。

每个 claim 至少包含：

- claim id
- target_id
- required_evidence
- required_world_info
- allowed_phases
- result

原则：

- 玩家正式指控是否成立，只由 Rule Engine 判断。
- LLM / MockAgent 不判断指控正确性。
- `required_evidence` 是玩家提交的线索。
- `required_world_info` 是玩家已知账本必须覆盖的事实锚点。
- allowed phase 用来防止玩家在结构上过早结案。

## 第九步：写 narrative phases / beats

剧情阶段用于控制悬疑节奏，不用于写复杂剧情小说。

建议四段以内：

```text
opening
investigation / pressure
reveal / expose
resolved
```

beat 只做确定性推进：

- 发现关键线索 -> 完成 beat。
- 发现一组线索 -> 推进 phase。
- 正确正式指控 -> resolved。

不要让 Agent 提议阶段变化。即使 Agent 输出 `narrative.phase.change`，Rule Engine 也必须拒绝。

## 第十步：写 mock dialogues

Mock dialogue 的职责不是写最终文学表现，而是让最小闭环可测试。

每个关键节点至少写：

- 默认回复。
- 玩家发现关键线索前的回复。
- 玩家发现关键线索后的回复。
- 玩家展示证据时的回复。
- reveal 阶段的更高压力回复。
- 一个 Director block 测试用 forbidden speech。

注意：

- mock 台词不应该直接泄露 forbidden fact。
- 如果台词触碰某个 WorldInfo，未来接 LLM 时必须有对应 `disclosure_claims`。
- 当前 mock 可先保持确定性，优先服务测试，不追求戏剧效果。

## 第十一步：写标准玩家路径

每个案件必须设计一条标准路径：

```text
inspect clue A
ask_about NPC about clue A
present_clue A
inspect clue B
talk NPC
trigger Director block once
inspect final clue
accuse with required evidence
resolved
```

这条路径不是唯一玩法，而是回归测试路径。它必须能证明：

- 线索可达。
- 玩家已知正确增长。
- NPC 认知正确变化。
- Director 能 block。
- 正式指控能结案。
- replay 后状态一致。

## 第十二步：写剧情级回归评测

真实案件进入仓库前，必须有一条 Scenario-Level Evaluation。

至少断言：

- 每步事件类型顺序。
- 每步 narrative phase。
- 每步玩家已知 WorldInfo 集合。
- 哪些 NPC 的 CharacterFactAwareness 发生变化。
- Director block 的字段是否安全。
- `matched_text` 是否脱敏。
- `StateSummary` 不泄露 private / forbidden / solution claims。
- replay 后状态一致。
- LLM fallback 不污染状态。

## 案件质量检查清单

写完案件后，逐项检查：

- 所有关键事实都有 `WorldInfo`。
- 所有关键线索都通过 `reveals_world_info` 指向事实。
- 所有角色 private 都优先绑定 `related_world_info_ids`。
- 所有 forbidden facts 都绑定 `world_info_id`。
- 所有 solution claims 都有 `required_world_info`。
- 每个 required evidence 都可通过 hotspot 发现。
- 每个 narrative beat 都有可达触发条件。
- 标准玩家路径能从 opening 到 resolved。
- Director 至少能 block 一次过早剧透。
- replay 后状态一致。

## 常见错误

### 错误 1：先写对话，后补事实

结果通常是台词漂亮，但系统无法判断哪些内容是已知、禁说或可指控。

正确做法：先写 WorldInfo 和线索，再写对话。

### 错误 2：Clue 直接等于真相

线索应该描述证据，不应该直接给最终解释。

正确做法：Clue 指向 WorldInfo，真相由多个 WorldInfo 和 solution claim 组合成立。

### 错误 3：private 当成 forbidden

角色秘密不是永久不能说。它只是角色有动机隐藏。

正确做法：普通秘密放 private；会破坏悬疑结构的核心剧透才放 forbidden facts。

### 错误 4：让 mock dialogue 推剧情

NPC 说了某句话不等于世界状态改变。

正确做法：状态变化必须来自 Rule Engine、DerivedEventSystem 或 RuleTriggerSystem。

### 错误 5：最终指控只看证据，不看 WorldInfo

这样会让玩家“拿到了线索但系统不知道玩家理解了什么”。

正确做法：solution claim 同时要求 `required_evidence` 和 `required_world_info`。

## 第一真实案件建议规模

第一个真实案件不要太大。

建议：

- 1 个核心地点。
- 3 个 NPC。
- 6 到 10 个 WorldInfo。
- 5 到 8 条关键 Clue。
- 2 到 3 个 forbidden facts。
- 2 个 solution claims：一个正确，一个错误。
- 3 到 4 个 narrative phases。
- 1 条标准玩家回归路径。

这个规模足够测试系统能力，但不会被内容复杂度拖死。

## 完成定义

一个案件 v0 完成，不是“故事写完了”，而是满足：

```text
case validate 通过
服务能启动
标准路径能 resolved
Director 能阻止过早剧透
StateSummary 不泄露内部配置
player_journey 不泄露 private 原文
replay 后状态一致
剧情级回归测试通过
```

只有满足这些，才进入下一阶段：优化台词、引入真实 LLM、增加复杂 NPC 行为。
