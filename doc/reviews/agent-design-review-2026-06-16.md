# Agent 设计评审：记忆、Context、Skill 与安全边界

评审时间：2026-06-16

评审范围：`app/agents`、`app/director`、`app/rules`、`app/runtime`、相关测试与现有文档。

## 一句话结论

当前系统已经不是“给 NPC 套一层 prompt”的低级 Agent 方案，而是一个有明确后端边界的叙事 Agent Runtime：`AgentLoop` 组织上下文、记忆、skill、安全审计和 LLM 调用，`NarrativeDirector` 控制事实披露，`RuleEngine` 执行真实状态变化。

但从生产视角看，最危险的缺口也很清楚：NPC Skill 目前主要是“上下文投影和事实片段限流”，还没有全面成为 LLM 输出合同的硬约束；记忆系统已经有可见性和层级过滤，但还缺少针对“记忆污染、记忆自我强化、过期事实误用”的主动防御闭环。

## 熟悉 Agent 项目的影子

### Claude Code 的影子最重

相似点：

- `AgentLoop` 很像 coding agent 的运行时主干：构造 context、估算 budget、记录 trace、调用 agent backend、校验输出。对应代码：`app/agents/loop.py`。
- `PromptBuilder` 把系统 prompt、策略文件、skill discipline 和结构化 payload 拼成 LLM 输入，类似 Claude Code 的项目指令、skills、hooks 组合思路。对应代码：`app/agents/prompt_builder.py`。
- `RuntimeTracer`、`memory_projection`、`npc_skill_projection` 对应通用 agent 的 session trace / observability 思路。
- `AGENTS.md` 本身也像 Claude Code / Codex 生态的 repo-level manifest，用来约束项目级行为。

关键差异：

- Claude Code 的核心目标是读写代码、跑命令、提交变更；这里的 Agent 目标是生成 NPC 叙事意图。
- Claude Code 强在工具执行与文件系统操作；本项目正确地没有把工具自由度开放给 LLM。
- 本项目更强的部分是 `NarrativeDirector + FactGateway + RuleEngine`，它们把“能说什么”和“能改变什么状态”从 prompt 里拉回到后端规则。

判断：这是“Claude Code 式 runtime 骨架”，但不能照搬它的工具自治模型。叙事项目的核心不是让 Agent 更能干，而是让 Agent 在案件真相、角色认知和线索节奏内稳定工作。

### Goose 的影子在扩展和工具层

相似点：

- Goose 以 extensions / MCP 扩展工具能力；本项目有 `ToolRuntime._ALLOWED_TOOLS` 和 `NpcSkillSelector`，也在做能力注册与选择。
- Goose 有 memory、top-of-mind、extension enable/disable 的运行时概念；本项目对应的是 `MemoryRetriever`、`RetrievalPlanner`、`npc_skill_projections`。

关键差异：

- Goose 更偏通用本机/工作流自动化，扩展可以连接外部系统，风险来自工具调用权限。
- 本项目的 `ToolRuntime` 目前只返回安全摘要，不让 LLM 直接拿工具结果或执行状态变化，这一点是对的。
- 本项目的 skill 不应该演化成 Goose 那种“动态启用外部工具”的模式，除非先有身份传播、权限域、审计事件、幂等执行和回放语义。

判断：可以借 Goose 的扩展注册和权限模型，但不应借它的开放式扩展自由度。游戏后端的工具必须是规则系统 API，而不是 Agent 自由调用的外部能力。

### ReMe / ReMem 类记忆框架的影子在记忆生命周期

相似点：

- 本项目有记忆类型、scope、layer、source_event_ids、archival、retrieval plan、BM25/语义 scorer，这已经接近现代 Agent Memory 的工程形态。
- `MemoryRetriever.retrieve_for_director()` 与普通 NPC `retrieve()` 分权，体现了“同一记忆库，不同角色视角”的安全边界。
- 测试已经覆盖私有记忆、scene_shared 记忆、director_audit 记忆、archival 记忆的可见性。

缺口：

- 还没有真正的“经验反思/程序性记忆”。现在记忆多是事件派生出的事实、关系、策略快照，不是可复用的失败经验或行为改进规则。
- 还没有记忆质量治理：重复记忆合并、过期记忆降权、冲突记忆裁决、低置信记忆隔离。
- 还没有记忆污染防御：玩家可以通过多轮诱导制造看似合理的 NPC 记忆，之后在特定上下文触发错误披露或错误关系变化。

判断：现在是“受控检索记忆”，不是“自进化记忆”。这对生产悬疑游戏是好事。下一步应该先做污染防御和冲突裁决，而不是急着让记忆自我进化。

### Superpower / Skills 类项目的影子在能力包

相似点：

- `app/agents/skills/*.md` 和 `app/agents/skills/memory_projection/*.md` 是典型 skill-as-markdown。
- `cases/<case_id>/npc_skills.yaml` 把角色能力从代码中配置化，类似可分发能力包。
- `NpcSkillProjection` 只暴露安全投影，不暴露正文和 private 内容，这个方向正确。

关键差异：

- 通用 skills 通常是“给模型更多做事方法”；这里的 NPC skill 应该是“限制模型怎么表达和披露”，本质更像安全策略和叙事风格门控。
- 目前 skill 的 `allowed_intents`、`allowed_tactics`、`allowed_proposed_actions` 已经投影出来，但对 LLM 输出的硬校验还不完整。

判断：本项目的 skill 不该变成泛用 prompt 技能市场，而应变成“角色行为有限状态机 + 披露合同 + 记忆检索计划”的组合。

## 当前系统强项

1. 状态边界基本正确

`ActionService._complete_agent_backed_action()` 中，LLM 只产出 `AgentIntent`，随后由 `NarrativeDirector.validate()` 检查，再由 `RuleEngine.apply_agent_intent()` 应用 proposed actions。LLM 没有直接写 session state。

2. Context 投影有安全意识

`build_agent_context()` 会按 target NPC 过滤 recent events、memory candidates、memory snapshots，并且 `_event_visible_to_target()` 会阻断 `CHARACTER_IMPRESSION_UPDATED`、`CHARACTER_FACT_AWARENESS_UPDATED` 等敏感事件进入 NPC 视角。

3. 记忆 scope/layer 设计是正确方向

`case/session/npc_private/scene_shared/director_audit` 与 `core/working/archival` 的组合，能表达叙事项目最关键的视角边界。测试已经覆盖私有记忆不串 NPC、director audit 不进 NPC context。

4. Narrative Director 已经不是纯 prompt

`FactGateway` 有 safe fragment、forbidden inference、claim graph、unlock condition。它能做前置 safe fragment 投影，也能做后置 speech / disclosure_claim 校验。

5. 观测性已经开始成形

Trace 中记录 memory projection、store filters、npc skill projection、security flags、director decision、rule rejections。这是后续做线上回放和红队评测的基础。

## 主要问题

### P0：Skill 还没有完全接入 LLM 输出硬约束

代码已经把 skill 投影为：

- `allowed_intents`
- `allowed_tactics`
- `allowed_proposed_actions`
- `safe_fragment_refs`
- `max_disclosure_mode_by_world_info`

但 `validate_llm_agent_output()` 目前主要校验 schema、禁止 phase change、禁止 raw private echo、校验 disclosure_claim。它还没有按 selected skill 严格拒绝：

- 顶层 `intent` 不在 selected skill 的 `allowed_intents` 内；
- `disclosure_claims[].tactic` 不在 skill `allowed_tactics` 内；
- `proposed_actions` 不在 skill `allowed_proposed_actions` 内；
- relationship delta 超过 skill policy；
- selected skill 为空时，LLM 仍提出强行为或强披露。

这会造成一个生产风险：skill 看起来被选中了，但实际上只是提示和 safe fragment 限流，不能完全约束模型行为。

最优解：把 `NpcSkillProjection` 合并进 `LLMAgentContractInput.output_contract`，并在 `validate_llm_agent_output()` 增加 skill-aware 校验。Director 是事实安全网，但 skill 行为边界应在 LLM contract 层先拒绝。

### P0：记忆污染防御还不够

当前记忆检索硬过滤做得不错：可见性、scope、layer、source_event_ids、phase、forbidden terms 都有。但是污染问题不只是不该看的记忆进来，还包括“可见但错误、可见但被诱导、可见但过期”的记忆影响行为。

高风险场景：

- 玩家连续诱导 NPC 形成错误 belief memory；
- relationship/strategy memory 因一次异常交互被强化；
- archival fallback 在无结果时把过期记忆拉回来；
- 同一事实存在多个冲突 memory，retriever 只按相关性排序，缺少一致性裁决。

最优解：

- 给 memory 增加 `authoritativeness` 或复用 `non_authoritative`，规则上禁止低权威记忆支持关键剧情判断；
- 对 belief/strategy memory 增加 source event 类型白名单；
- 增加 conflict set：同一 `world_info_id/clue_id/belief_subject` 下互斥记忆必须交给 Director 或 rule layer 裁决；
- 对会影响披露和关系变化的记忆，要求至少一个可回放来源事件和一个当前 phase 允许的证据锚点。

### P1：Context budget 目前像通用压缩，不像叙事安全压缩

`ContextBudgetManager` 会压缩历史，但剧情系统不能只按 token 压缩。叙事上下文的压缩必须保留：

- 当前 phase；
- 已解锁和未解锁 world_info；
- 与目标 NPC 相关的 fact awareness；
- 最近被 Director block 的风险；
- 关键 clue 的发现和理解状态；
- selected skill 与 safe fragment refs。

否则压缩会制造“模型忘记限制”的问题。

最优解：把 context budget 分成硬保留区和可压缩区。硬保留区包含 Director constraints、skill projection、player knowledge ids、target profile、fact awareness ids、memory ids；可压缩区才处理 recent events 和历史摘要。

### P1：Skill 与 memory retrieval plan 是两套系统

现在有两类 skill：

- `memory_projection/*.md` 决定记忆检索计划；
- `npc_skills.yaml` 决定 NPC 行为/披露能力。

两者独立选择，容易出现“行为 skill 要求某种记忆，但 retrieval plan 没取到”或“retrieval plan 取到了某类记忆，但当前 NPC skill 不允许用”的错位。

最优解：做一个统一的 `AgentTurnPlan`：

- selected memory projection skill；
- selected NPC behavior skill；
- final memory include/forbid；
- final disclosure constraints；
- final output contract；
- trace summary。

这样后续排查会更直接，也能把 skill 从“提示材料”升级成“运行时计划”。

### P1：安全层还是偏 pattern-based

`PromptInjectionGuard` 目前是关键词匹配，只能用于 trace flag，不能真正决定降级策略。它能抓常见英文注入，但对中文、混合语言、叙事伪装、角色扮演越权都弱。

最优解：

- 安全审查结果进入 `AgentTurnPlan`，影响允许的 `intent` 和 disclosure mode；
- 高风险注入时强制 selected skill 降级为 refuse/deflect；
- 增加中文和剧情语义测试集；
- 把 prompt injection 视为玩家动作风险，而不是普通文本风险。

### P2：当前 Agent 不是多 Agent 社交系统

项目定位是多智能体悬疑叙事，但当前 runtime 更像“玩家点名一个 NPC，单 NPC 回合处理”。多 Agent 传播主要靠事件和记忆派生，还没看到真正的 NPC-NPC 社交编排、异步目标推进、场景内旁听与反应队列。

这不是 bug，但要正名：当前是 production-oriented single-target NPC agent runtime，不是完整 multi-agent society。

下一步应该先把 scene_shared、旁听、二级反应、关系网络传播做成规则事件，再考虑多 Agent 自主调度。

## 建议路线

1. 先做 skill-aware output contract

把 selected skill 的 `allowed_intents/allowed_tactics/allowed_proposed_actions/max delta` 变成 `LLMAgentContractInput` 的硬约束，并补测试覆盖越权 intent、越权 tactic、越权 proposed action。

2. 再做统一 AgentTurnPlan

合并 `RetrievalPlanner` 和 `NpcSkillSelector` 的结果，避免 memory plan 与 behavior skill 分裂。

3. 然后做记忆污染防御

优先补 conflict detection、authoritative source、belief/strategy memory source whitelist、archival fallback gating。

4. 最后再扩大 Agent 自由度

在以上三项完成前，不建议引入开放式工具、动态外部 extension、自主 NPC 行动队列或自我改写 skill。

## 外部参照口径

- Claude Code 类项目强调 agentic coding tool、项目指令、skills、hooks、并行 agent 与 trace。本项目只适合借 runtime、observability、contract 思路，不适合借开放工具自由度。
- Goose 类项目强调 extension、MCP、动态启用工具、访问控制和 session memory。本项目可借扩展注册和权限概念，但工具必须继续收束在 Rule Engine。
- ReMe / ReMem 类记忆项目强调经验驱动的记忆复用和自我细化。本项目当前更应优先保证记忆可信、可见、可回放，而不是追求自进化。
- Superpower / Skills 类项目强调可复用能力包。本项目的 skill 应继续服务于角色行为边界和披露约束，而不是变成泛用 prompt 技能市场。

这里的类比只用于定位架构气质，不作为依赖选型依据。后续如果要正式引入 MCP、外部工具、经验记忆或 skill marketplace，需要另开设计文档和安全评审。
