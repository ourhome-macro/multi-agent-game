# 真实案件剧情级回归评测协议 v0

## 定位

这份文档定义真实案件进入仓库前必须补的 Scenario Evaluation。它不是新的运行时代码，也不是新的测试框架，而是规定每个真实案件必须有一条可执行、可断言、可回放的标准调查路径。

一句话：真实案件不是写完 YAML 就算完成，必须能被剧情级回归评测证明“跑得通、锁得住、回放一致”。

## 为什么必须做

当前系统已经有很多局部能力：

- `WorldInfo` 事实锚点。
- `PlayerKnowledge` 玩家已知账本。
- `CharacterFactAwareness` 角色事实认知。
- `FactDisclosureStrategy` 披露边界。
- `NarrativeDirector` speech 审计。
- `RuleEngine` 状态执行。
- `WorldEvent` 事件日志。
- replay。

真实案件会把这些模块全部串起来。只靠字段校验无法证明剧情稳定，必须跑完整路径。

## 真实案件必须提供什么

每个真实案件至少提供一条标准调查路径，包含：

```text
session created
inspect key clue
ask_about npc about clue
present_clue to npc
talk npc
trigger one director.blocked
inspect remaining key clues
accuse with required evidence
resolved
replay and compare state
```

这条路径不是唯一玩法，也不是最终玩家攻略。它只是回归测试基线，用来证明案件包和运行时组合稳定。

## 标准路径设计原则

### 1. 路径必须覆盖核心事实链

标准路径必须让玩家获得结案所需的 `required_world_info`。

如果 `solution_claims.yaml` 需要：

```text
required_world_info:
  - fact_a
  - fact_b
  - fact_c
```

那么标准路径必须明确在哪一步获得 `fact_a / fact_b / fact_c`。

### 2. 路径必须覆盖关键证据链

标准路径必须让玩家发现结案所需的 `required_evidence`。

每个 required evidence 都要能追溯：

```text
hotspot
  -> clue.discovered
  -> player_knowledge.updated
  -> solution claim evidence
```

如果证据无法通过 hotspot 或已有动作获得，这个案件还没达到可运行标准。

### 3. 路径必须触发一次 Director block

每个真实案件至少要有一次过早剧透测试。

目的不是为了让剧情一定出现这个对话，而是证明：

- forbidden fact 配置有效。
- Director 能阻止越权台词。
- `director.blocked` 不写 `npc.replied`。
- 返回给玩家的是安全降级台词。
- `matched_text` 不泄露敏感原文。

### 4. 路径必须触发一次 NPC 认知变化

标准路径必须包含至少一次：

- `ask_about`
- 或 `present_clue`
- 或 `accuse`

并验证目标 NPC 的 `character_fact_awareness.updated` 只发生在预期角色和预期 `WorldInfo` 上。

### 5. 路径必须触发一次关系或画像变化

标准路径应至少让一个 NPC 对玩家产生印象变化，证明：

- 玩家询问、展示线索或指控能被事件系统捕捉。
- `character_impression.updated` 不进入公开 `StateSummary`。
- replay 后画像一致。

## 每步必须断言什么

每个标准路径 step 至少断言：

- 输入的 `PlayerAction`。
- `ActionResponse.accepted`。
- `ActionResponse.director_blocked`。
- 本步新增 `WorldEvent.type` 顺序。
- 当前 `narrative.phase`。
- 当前玩家已知 `world_info_id` 集合。
- 本步新增 `character_fact_awareness.updated` 的 `(character_id, world_info_id)`。
- 如果出现 `director.blocked`，检查其审计 payload。

推荐把每步写成结构化 spec，而不是在测试里散写 assert。

## 全局必须断言什么

完整路径跑完后必须断言：

- 最终 phase 是预期结案阶段，例如 `resolved`。
- 必要 beat 已完成。
- 玩家已知 WorldInfo 集合等于预期集合。
- 所有 `PlayerKnowledge.world_info_id` 都存在于案件 `world_info.yaml`。
- 所有 `PlayerKnowledge.knowledge_id` 都等于 `player_knowledge.<world_info_id>`。
- 所有 `character_fact_awareness.updated` 都来自合法玩家事件。
- 所有 `narrative.phase.changed` 都由 `rule_trigger_system` 写入。
- Agent 提出的 phase change 不会推进剧情。
- `StateSummary` 不暴露 private、forbidden facts、solution claims 或 inner context。
- `player_journey` 不暴露 private 原文或禁说原文。

## Director block 必须断言什么

每个真实案件的标准路径必须至少断言一次：

```text
director.blocked.payload.target_id
director.blocked.payload.blocked_fact_id
director.blocked.payload.world_info_id
director.blocked.payload.detected_directness
director.blocked.payload.matched_by
director.blocked.payload.matched_text
director.blocked.payload.safe_fallback_used
```

要求：

- `detected_directness` 应为可审计值，例如 `direct_claim`。
- `matched_by` 应说明命中方式，例如 `forbidden_term`、`alias` 或 `pattern`。
- `matched_text` 必须是脱敏值，例如 `[redacted]`。
- `safe_fallback_used=true`。
- 同一步不得产生 `npc.replied`。

## disclosure_claims 必须断言什么

真实 LLM 接入前，mock 路径可以暂时没有复杂 `disclosure_claims`。但如果某一步产生了 `disclosure_claims`，必须断言：

- 每个 claim 的 `world_info_id` 在当前目标 NPC 的 `FactDisclosureStrategy` 中存在。
- `mode` 不等于 `full`。
- `mode` 在 `allowed_modes` 中。
- `mode` 不在 `forbidden_modes` 中。
- `claim_refs` 不命中 `must_not_claim`。

后续接入真实 LLM 后，真实案件标准路径应增加至少一条“合法 hint / partial claim 放行”的测试。

## replay 必须断言什么

完整路径结束后必须执行：

```text
replay_events(case, session.events)
```

并比较：

- `StateSummary`
- `PlayerKnowledge`
- `CharacterFactAwareness`
- `CharacterImpression`
- `MemoryCandidate`
- `AgentMemorySnapshot`
- `relationships`
- `narrative.phase`
- `completed_beats`
- event count

如果 replay 后状态不一致，说明有状态更新没有被事件日志完整表达，不能进入下一阶段。

## LLM fallback 必须断言什么

每个真实案件应在标准路径结束后做一次 fallback 检查：

```text
OpenAILLMAgent(api_key="").generate(context)
```

断言：

- 不新增 `WorldEvent`。
- 不改变 `SessionState`。
- 不产生 `proposed_actions`。
- 不产生 `memory_refs`。
- 不产生 `disclosure_claims`。
- fallback speech 不泄露 private 原文或 forbidden terms。

这不是测试真实 LLM 能力，而是测试真实 LLM 不可用时不会污染世界。

## 建议测试命名

真实案件测试建议命名：

```text
tests/test_real_case_<case_id>_scenario.py
```

或统一放进：

```text
tests/test_real_case_scenarios.py
```

每个案件至少一个测试：

```text
test_<case_id>_standard_investigation_path()
```

如果案件后续扩展，可以再增加：

```text
test_<case_id>_wrong_accusation_path()
test_<case_id>_early_spoiler_is_blocked()
test_<case_id>_alternate_clue_order_reaches_same_phase()
```

## 标准路径 spec 示例

示例结构：

```text
ScenarioStep(
  name="inspect desk unlocks drawer fact",
  action=PlayerAction(type="inspect", target_id="desk"),
  expected_events=[
    player.inspected,
    clue.discovered,
    player_knowledge.updated,
    memory_candidate.created,
    agent_memory_snapshot.updated,
    narrative.beat.completed,
    narrative.phase.changed,
  ],
  expected_phase="investigation",
  expected_player_world_info_ids={
    "desk_forced_open",
  },
)
```

重点是每一步都能回答：

- 玩家做了什么？
- 系统写了什么事件？
- 玩家现在知道什么？
- 剧情阶段是否正确？
- NPC 认知是否被合法更新？

## 错误路径也要保留

真实案件 v0 至少保留一条错误路径测试，推荐是错误指控：

```text
accuse wrong target / wrong claim
  -> accepted=false 或 result=incorrect
  -> 不进入 resolved
  -> 不污染 PlayerKnowledge
  -> 不产生非法 narrative.phase.changed
```

如果第一轮时间紧，可以先只做标准路径；但进入真实 LLM 前必须补错误路径。

## 验收命令

真实案件合入前至少跑：

```powershell
py -3.12 -m app.cases.validate cases
py -3.12 -m pytest -q
py -3.12 -m ruff check app tests
```

如果新增了真实案件专用 scenario 测试，先跑更小范围：

```powershell
py -3.12 -m pytest tests/test_real_case_<case_id>_scenario.py -q
```

再跑全量。

## 完成定义

真实案件的 Scenario Evaluation 完成，必须满足：

```text
标准路径能从初始阶段跑到 resolved
每步事件顺序可断言
玩家已知 WorldInfo 集合可断言
NPC 认知变化可断言
Director block 可断言且不泄密
disclosure_claims 如存在则可审计
StateSummary 不泄露内部真相
replay 后状态一致
LLM fallback 不污染状态
全量 pytest / ruff / case validate 通过
```

只有达到这个标准，真实案件才算进入“可迭代内容”状态。否则它只是素材，不是可运行案件。
