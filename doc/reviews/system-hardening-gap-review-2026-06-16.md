# 系统固化差距评审：Skill、记忆、压缩、安全与多 Agent

评审时间：2026-06-16

评审范围：`app/agents`、`app/runtime`、`app/rules`、`app/domain`、`cases/mist_clock_manor`、相关测试。

## 一句话结论

当前工作区已经开始实现 `AgentTurnPlan`、skill-aware output contract、prompt injection 硬降级和返场线索，但这些能力还处在“工作区变更/局部验证”阶段，不应按生产完成口径看待。最值得继续做的是把 AgentTurnPlan 修到测试稳定，然后推进记忆污染防御和 narrative-safe context budget。

## 1. Skill 输出硬约束

状态：部分完成，但未稳定。

已看到的实现：

- 新增 `app/agents/turn_plan.py`，把 memory retrieval plan、selected skill、security review 和 output contract 合成 `AgentTurnPlan`。
- `build_llm_agent_input()` 已支持传入 `turn_plan`，并把 `turn_plan.output_contract` 放入 `LLMAgentContractInput`。
- `validate_llm_agent_output()` 已按 output contract 校验 intent、proposed action type、disclosure tactic、disclosure mode 和 relationship delta cap。
- 没选中 skill 时，默认禁止 active proposed actions。
- 高风险 prompt injection 可进一步收窄 allowed intents 和 disclosure modes。

当前问题：

- 定向测试 `tests/test_agent_turn_plan_skill_contract.py::test_runtime_degrades_skill_contract_violation_without_applying_side_effects` 失败：runtime 没有触发预期 fallback，说明测试、mock agent 输出或 contract 期望仍有不一致。
- `AgentTurnResult` 还没有暴露 `turn_plan` 本身，trace 里也没有完整计划快照。线上排障只看 `npc_skill_projection` 和 `security_flags` 还不够。
- 现在的 fallback speech 是固定安全话术，生产上应该进入可观测的 contract-repair/fallback 策略，而不是静态英文句子。

建议：

1. 先修复失败测试，确保越权输出必定进入 `llm_fallback_used=True` 且不产生副作用。
2. 把 `turn_plan_id`、contract 摘要、security hard restriction、selected skill ids 写入 trace。
3. 增加真实 LLM shadow eval 中的 contract violation 统计。

## 2. 记忆污染防御

状态：做了 provenance 基础，还没做污染治理闭环。

已看到的实现：

- `AgentMemorySnapshot`、`MemoryCandidateState`、memory derivation rule 都有 `source_event_ids`。
- `MemorySnapshotSystem` 要求 active memory 必须有 `source_event_ids`，除非是 archival 或显式 `metadata.non_authoritative=true`。
- 检索硬过滤里有 `has_source_event_ids`。
- 已有 `confidence`、`belief_subject`、`world_info_id`、`clue_id`、`source_memory_ids` 等元数据基础。
- `director_audit` 与 NPC 可见记忆分离，NPC 默认不能读 director audit。

当前问题：

- `non_authoritative` 目前只是元数据和 source 例外，不是检索降权/禁用策略。
- 没有 authority taxonomy：事实记忆、玩家诱导、NPC 主观看法、规则确认事实仍混在同一检索排序里。
- 没有 conflict detection：同一 `world_info_id`、`clue_id`、`belief_subject` 的互斥记忆不会被隔离。
- key plot memory 仍可能靠相似度进入上下文，缺少 Director/Rule 的关键剧情校验。

建议：

1. 给 memory 增加 authority level：`rule_verified`、`event_observed`、`npc_belief`、`player_claim`、`hypothesis`、`non_authoritative`。
2. 检索前做 conflict set 构建；冲突组默认不投给 NPC，改投 Director audit。
3. 关键剧情判断只允许 `rule_verified/event_observed` 支撑，不能由 `player_claim/hypothesis` 直接支撑。
4. trace 增加 `memory_rejected_by_authority` 和 `memory_conflict_groups`。

## 3. Context 压缩

状态：有压缩机制，但还不是悬疑叙事安全压缩。

已看到的实现：

- `ContextBudgetManager` 会在超过阈值后生成 `CompressedHistoryContext`。
- 压缩摘要会保留 `important_event_ids` 和 `important_memory_ids`。
- `AgentContext` 本身携带 phase、completed beats、player knowledge、blocked/revealable facts、safe fragments、skill projections。

当前问题：

- 没有显式 `hard_context/soft_context` 分层。
- 压缩触发后只是附加 `compressed_history`，没有证明 soft 部分被安全替换或裁剪。
- 最近 Director block、fact awareness、selected skill、safe fragments、source_event_ids 没有被形式化为不可压缩清单。

建议：

1. 定义 `AgentHardContext`：phase、completed beats、player knowledge ids、target awareness ids、blocked/revealable facts、selected skill ids、safe fragment refs、recent director block ids、memory source refs。
2. `PromptBuilder` 明确先渲染 hard context，再渲染 soft context。
3. 加测试：在极低 token budget 下，上述 hard context 字段仍然出现在 LLM contract input 和 prompt payload 中。

## 4. 安全层

状态：从报警器升级到局部控制器，但规则还粗。

已看到的实现：

- `PromptInjectionReview` 有 `risk_level`、matched patterns、recommended response mode。
- high risk 会生成 hard restriction：allowed intents 限制到 `REFUSE/CONCEAL`，max disclosure mode 限到 `DEFLECT`。
- `AgentTurnPlan` 会把安全审查合入 output contract。
- 有高低风险测试和 runtime side-effect 测试。

当前问题：

- 风险判断仍是 pattern-based，中文、混合语言、剧情伪装覆盖不足。
- low risk 只打 flag，不影响策略；这可能放过“慢性诱导”。
- 没有把安全风险写成玩家动作风险事件，后续 session 不能形成长期防护。

建议：

1. 增加中文/中英混合/角色扮演伪装注入测试集。
2. low risk 连续出现时升级为 medium/high，进入本轮或后续 turn restriction。
3. 引入 `player_action.risk_assessed` 或在现有事件 payload 中写入可 replay 的风险摘要。

## 5. 多 Agent 社会

状态：尚未真正实现。

已有基础：

- 有 `WorldEvent`、memory stream、relationship state、scene_shared memory、character_fact_awareness。
- NPC 间信息传播可以通过事件和记忆派生扩展。

当前缺口：

- 没有 `Observation`/Perception Filter。
- 没有 `ProposedNpcAction`。
- 没有 NPC-NPC 事件类型，如 `npc.talked_to_npc`、`npc.heard_rumor`、`npc.shared_clue_hint`。
- 没有异步 planner 或 social tick。

建议：

先不要做开放式 AI Town。生产路线应该是：

`WorldEvent -> Perception Filter -> Observation -> Memory Stream -> Reflection/Portrait -> ProposedNpcAction -> RuleEngine -> NarrativeDirector -> WorldEvent`

每一步都必须可审计、可 replay、可被规则拒绝。

## 新建议

### A. Contract Violation Taxonomy

现在 `policy_violation` 太粗。建议细分：

- `skill.intent_violation`
- `skill.tactic_violation`
- `skill.proposed_action_violation`
- `skill.relationship_delta_violation`
- `security.disclosure_mode_violation`
- `director.fact_violation`

这样 shadow eval、trace、线上告警才知道模型到底坏在哪里。

### B. Turn Plan Replay

`AgentTurnPlan` 应可由当时的 `WorldEvent`、session state、case package 和 player action 重建，或至少把摘要写入 trace。否则线上 LLM 输出违规后，无法确认是模型越权、skill 选择错、security 降级错，还是上下文构造错。

### C. Case Authoring Linter

给案件包加 lint：

- 每个 high sensitivity world_info 必须有 safe fragment。
- 每个 npc skill 的 allowed proposed actions 必须有 max delta。
- 每个返场线索必须不进入 standard path。
- 每个 memory rule 必须标注 authority 和 source_event_ids。
- 每个关键 claim 的 required evidence 不得引用可选厚度线索。

### D. Shadow Eval Failure Gates

真实 LLM shadow eval 不只看是否跑完，应形成上线门槛：

- contract violation rate
- director block rate
- unsupported proposed action rate
- drift in phase/knowledge/event count
- forbidden term near miss
- memory conflict usage rate

### E. Memory Quarantine

对低权威或冲突记忆不要直接删除，放入 quarantine/director_audit，由 Director 决定是否转成安全摘要或规则确认事实。这样既防污染，也保留调试证据。

## 验证记录

已运行：

`py -3.12 -m pytest tests/test_agent_turn_plan_skill_contract.py tests/test_agent_turn_plan_security.py tests/test_typed_memory.py tests/test_agent_runtime_remaining_phases.py -q`

结果：40 passed，1 failed。

失败项说明：`test_runtime_degrades_skill_contract_violation_without_applying_side_effects` 未触发预期 LLM fallback，AgentTurnPlan/skill contract 不能视为完成。
