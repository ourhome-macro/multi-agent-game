# 剧情级回归评测器 v0

## 目标

本轮新增的是 Scenario-Level Evaluation / Regression Harness v0。它不是新运行时系统，也不新增叙事概念，而是把完整玩家调查路径变成可重复执行、可断言、可审计的剧情级测试。

核心目的：

- 验证多个底层模块组合后不会互相打架。
- 验证完整剧情路径下 WorldInfo 暴露、NPC 认知变化、披露策略、Director 审计和 replay 保持一致。
- 在接真实 LLM 前，先证明 mock / fallback / Director / Rule Engine 的组合边界稳定。

## 覆盖范围

当前 harness 覆盖 `fake_case_001`、`fake_case_002` 和真实样例案件 `mist_clock_manor` 的完整路径：

```text
PlayerAction sequence
  -> ActionService
  -> AgentGateway / MockAgent
  -> NarrativeDirector
  -> RuleEngine
  -> DerivedEventSystem
  -> MemorySnapshotSystem
  -> RuleTriggerSystem
  -> StateSummary
  -> replay_events
```

每个案件都从 session 创建开始，逐步执行调查、询问、展示线索、Director block、收集关键证据和正式指控，最后到 resolved。

## 每步断言

每个 `ScenarioStep` 会断言：

- 本步 `ActionResponse.accepted` 是否符合预期。
- 本步是否触发 `director_blocked`。
- 本步产生的 `WorldEvent.type` 顺序是否符合预期。
- 当前 `narrative.phase` 是否符合预期。
- 当前玩家已知的 `world_info_id` 集合是否符合预期。
- 本步新增的 `character_fact_awareness.updated` 是否只发生在预期 NPC 和预期 WorldInfo 上。
- 如果发生 `director.blocked`，审计 payload 是否包含安全字段且 `matched_text` 已脱敏。

## 全局不变量

每一步执行后，harness 还会检查这些不变量：

- `PlayerKnowledge` 必须锚定真实存在的 `WorldInfo`。
- `PlayerKnowledge.knowledge_id` 必须是 `player_knowledge.<world_info_id>`。
- `PlayerKnowledge` 的 `confidence / acquisition / source_type` 必须保持确定性。
- `narrative.phase.changed` 只能由 `rule_trigger_system` 写入。
- `rule.rejected` 只能由 `rule_engine` 写入。
- `npc.replied` 或 `director.blocked` 中的 `disclosure_claims` 如果存在，必须能在当前目标 NPC 的 `FactDisclosureStrategy` 中找到对应策略。
- LLM 合同中的 `world_info` 约束必须与 `AgentContext.inner_context.fact_disclosure_strategies` 对齐。
- `full` 永远不能出现在允许披露模式里。
- `StateSummary` 和 action response 不得泄露 private 原文、forbidden terms、`forbidden_facts`、`solution_claims` 或 `inner_context`。

## Replay 断言

完整路径结束后，harness 会执行 `replay_events(case, session.events)`，并断言 replay 后关键状态一致：

- `StateSummary`
- `PlayerKnowledge`
- `CharacterFactAwareness`
- `CharacterImpression`
- `MemoryCandidate`
- `AgentMemorySnapshot`
- event count

记忆快照的 `created_at / updated_at` 不作为业务等价条件，因为 replay 使用原事件时间重建，评测重点是状态内容和来源链路一致。

## LLM fallback 断言

每个完整场景结束后，harness 会用 `OpenAILLMAgent(api_key="")` 执行一次 fallback 检查：

- fallback 不写 `WorldEvent`。
- fallback 不改变 `SessionState`。
- fallback 不产生 `proposed_actions`。
- fallback 不产生 `memory_refs`。
- fallback 不产生 `disclosure_claims`。
- fallback speech 不泄露 private 原文或 forbidden terms。

这不是接入真实 LLM，而是确保真实 LLM 不可用或合同失败时，安全降级不会污染世界状态。

## 当前测试文件

- `tests/utils/scenario_evaluation.py`：通用剧情级评测 harness。
- `tests/test_scenario_evaluation_harness.py`：`fake_case_001` / `fake_case_002` 的场景规格和断言。
- `tests/test_mist_clock_manor_scenario.py`：`mist_clock_manor` 的标准调查路径、Director 禁说拦截、正式指控和 replay 断言。

## 真实案件接入要求

真实案件不能只保证 `case validate` 通过，还必须提供至少一条“标准调查路径”回归测试。标准路径不是唯一玩法，而是案件作者承诺的一条最小可解路径，用来证明案件配置与运行时规则能组合稳定。

`mist_clock_manor` 当前标准路径覆盖：

- 检查酒桌，获得 `sedative_wine`。
- 询问并展示酒液线索，只更新 `lin_qichi` 对 `sedative_wine` 的认知。
- 检查书房锁和录音机，获得 `timed_lock_modified`、`recording_tape_swapped`、`jiang_ruolan_recording_exists`，剧情进入 `confrontation`。
- 在 `confrontation` 阶段强制触发 `jiang_yanhui_mechanism` 越界探针，Director 必须拦截，且 `matched_text` 保持脱敏。
- 检查烧毁供词、药盒和电闸，补齐死亡链证据，剧情进入 `reconstruction`。
- 对 `jiang_yanhui` 发起 `shared_death_chain` 正式指控，Rule Trigger System 推进到 `resolved`。

这条路径同时断言：

- 玩家已知只增加合法 `WorldInfo`。
- NPC 私有认知只在合法互动后通过事件更新。
- Director block 不泄露 private 原文、禁说词原文或 solution claim。
- `disclosure_claims` 如果存在，必须可被当前 `FactDisclosureStrategy` 审计。
- replay 后 `PlayerKnowledge`、`CharacterFactAwareness`、印象、记忆候选和快照保持一致。

## 边界

本轮没有新增：

- NPC-NPC 社交。
- 结盟、背叛、欺骗新系统。
- 新记忆系统。
- 新 WorldFact。
- 真实 LLM 调用。
- 数据库或向量检索。

本轮只把已有运行链路变成剧情级回归评测，让后续新增 Agent 能力前先有稳定的组合验收网。
