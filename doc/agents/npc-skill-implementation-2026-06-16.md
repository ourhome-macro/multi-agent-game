# NPC Skill Implementation Note

生成时间：2026-06-16

## 已落地范围

本次把 NPC Skill 从规划推进到运行时 P0 闭环：

- `CasePackage.npc_skills` 支持从 `cases/<case_id>/npc_skills.yaml` 读取。
- `NpcSkillConfig` 表达 owner、type、level、priority、signature、trigger、unlock condition、disclosure、memory policy、proposed action policy、cooldown 和 fallback。
- `CaseLoader` 校验 skill owner、phase、beat、clue、world_info、player knowledge、safe fragment ref、fallback skill 和 relationship delta metric。
- `NpcSkillSelector` 按结构化 `PlayerAction`、phase/beat、已发现线索、玩家知识、玩家 world_info、关系阈值和交互压力选择 skill。
- `AgentContext.npc_skill_projections` 只暴露安全投影，不暴露 skill 正文、private 原文、memory content 或事实 summary。
- `PromptBuilder` 把 `npc_skill_projections` 写入 agent prompt payload。
- `AgentLoop` 把 Director 生成前 safe fragment 与 skill 的 `safe_fragment_refs` 取交集，skill 只能收窄事实碎片，不能授予事实。
- Runtime trace schema 升级到 v5，新增 `npc_skill_projection` 安全摘要。
- `cases/fake_case_001` 增加 `butler_drawer_pressure_deflection` signature skill，用于验证管家面对抽屉线索时的渐进披露边界。

## 当前硬边界

- LLM 不能选择、升级或伪造 skill。
- Skill 不能直接修改世界状态、关系状态、线索状态或剧情阶段。
- Skill 不能绕过 `CharacterFactAwarenessState` 和 `FactDisclosureStrategy`。
- Skill 引用的 safe fragment 必须先由 `WorldInfo.claim_graph.safe_fragments` 声明，并满足 unlock condition。
- Trace 不记录 safe fragment summary、skill 正文、玩家原始文本、private 原文、memory content、forbidden fact 文本。

## 尚未落地

- `WorldEvent` 级 skill attempt / selected / rejected / cooldown 记录。
- Skill cooldown 的真实状态存储与回放。
- Skill 对 LLM 输出合同的硬约束，例如限制 `AgentIntent.intent`、`RhetoricTactic`、`proposed_actions`。
- Skill 与 MemoryRetrievalPlan 的深度合并，目前只是独立投影。
- Skill counter / weakness / public observation UI。
- Skill 评测矩阵：某 phase、某 action、某 player knowledge 下应选择/不选择哪些 skill。

## 下一步优先级

1. 增加 `npc_skill.selected` 和 `npc_skill.rejected` 事件，至少记录 skill id、rejection reason、安全 refs 和 caused_by_event_id。
2. 把 selected skill 的 `allowed_intents`、`allowed_tactics`、`allowed_proposed_actions` 接入 `LLMAgentOutputContract` 校验。
3. 把 skill memory policy 合并进 retrieval planner，形成“action skill + memory projection skill”的单一计划。
4. 建立 `tests/test_npc_skill_matrix.py`，用表格锁定不同剧情阶段和玩家问法下的 expected / forbidden skill ids。
