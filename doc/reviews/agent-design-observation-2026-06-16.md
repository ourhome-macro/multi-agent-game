# Agent 设计观察：记忆、Context、Skill 与安全

日期：2026-06-16

范围：`app/agents`、`app/runtime`、`app/director`、`app/rules`、`cases/mist_clock_manor`、相关测试与现有文档。

## 一针见血结论

当前系统已经不是“NPC + prompt”的玩具结构，而是一个有明确后端边界的 Agent Runtime：LLM 只生成 `AgentIntent`，Narrative Director 控制事实披露，Rule Engine 执行真实状态副作用，事件日志负责回放和审计。这个大方向是对的。

但从生产级 Agent 设计看，系统还没有完全闭环。最核心的问题不是模型能力，而是三件事：

1. 真实 LLM 生成阶段没有接收完整 `AgentTurnPlan`，安全降级更多发生在事后校验，而不是事前收窄生成空间。
2. 记忆系统有可见性、scope、layer 和来源事件过滤，但缺少记忆污染治理：冲突裁决、权威性分级、过期信念降权、低置信记忆不得驱动关键剧情判断。
3. NPC Skill 框架已经能约束输出合同，但主案件 `mist_clock_manor` 尚未配置 `npc_skills.yaml`，也就是说 skill 体系目前主要是测试/样例能力，还没有成为生产案件的真实行为编排资产。

## 当前做对的地方

### 1. 状态边界基本正确

`ActionService._complete_agent_backed_action()` 的主路径是：玩家事件 -> Agent turn -> Director 校验 -> Director 放行后才记录 `NPC_REPLIED` -> Rule Engine 应用 proposed actions。Director 阻断时只记录 `DIRECTOR_BLOCKED` 和安全话术，不执行 `RuleEngine.apply_agent_intent()`。

这符合项目原则：LLM 不直接改世界状态。

对应代码：

- `app/runtime/service.py`
- `app/agents/loop.py`
- `app/rules/engine.py`
- `app/director/narrative_director.py`

### 2. AgentLoop 的职责拆分清晰

`AgentLoop.run_turn()` 已经把一个 NPC 回合拆成：

- memory retrieval plan
- NPC skill selection
- memory retrieval
- context build
- Director generation constraints
- security review
- unified turn plan
- trace
- LLM output contract validation

这说明系统已经具备 Agent Runtime 骨架，而不是 prompt 脚本。

### 3. LLM 输出合同开始硬化

`LLMAgentContractInput.output_contract` 已经能约束：

- `allowed_intents`
- `allowed_proposed_action_types`
- `allowed_rhetoric_tactics`
- `allowed_disclosure_modes`
- `max_relationship_delta`
- top-level keys

`validate_llm_agent_output()` 会拒绝越权 intent、越权 proposed action、越权 tactic、越权 disclosure mode、叙事阶段变更、裸露 private summary、未授权 safe fragment。

这是正确方向。Narrative Director 负责事实安全，LLM contract 负责行为边界，两者职责区分是合理的。

### 4. 记忆可见性设计方向正确

记忆维度已经拆成：

- type：`episodic`、`belief`、`relationship`、`strategy`
- scope：`case`、`session`、`npc_private`、`scene_shared`、`director_audit`
- layer：`core`、`working`、`archival`

`MemoryRetriever` 有硬过滤：

- 只检索 subject 为 player 的 NPC 记忆
- scope/layer 过滤
- target visibility 过滤
- source event id 必须存在
- phase gating
- retrieval plan gating
- forbidden content 过滤

这比简单向量库记忆安全得多。

### 5. Narrative Director 和 FactGateway 已经形成事实防线

`FactGateway` 支持：

- safe fragment
- forbidden inference
- claim graph
- unlock condition
- disclosure claim 校验
- speech 文本命中校验

这对悬疑叙事是关键能力。事实披露不是靠 prompt 自律，而是有后端校验。

## 主要问题

### P0：真实 LLM 生成阶段没有吃到完整 AgentTurnPlan

`AgentLoop.run_turn()` 构建了 `turn_plan`，最终 `_validate_agent_intent()` 会用 `build_llm_agent_input(context, turn_plan=turn_plan)` 做事后校验。

但 `OpenAILLMAgent.generate_strict()` 内部重新调用 `build_llm_agent_input(context)`，没有 turn plan 参数。结果是：

- security hard restriction 不一定进入真实 LLM 请求 schema；
- 高风险 prompt injection 时，模型仍可能先按较宽合同生成，然后再被本地拒绝；
- 线上会表现为 fallback 增多，而不是模型在受限空间内稳定输出；
- trace 里会看到安全降级，但生成成本、延迟、失败率仍然被放大。

最优解：Agent 生成接口应接收 `LLMAgentContractInput` 或 `AgentTurnPlan`，不要让 backend 自己重建合同。`AgentGateway.generate()` 最好从 `generate(context)` 升级为 `generate(contract_input)`，或者新增 `generate_with_contract(context, contract_input)`。

### P0：记忆污染治理不够

当前记忆检索“可见性”做得不错，但“可信性”还不够。危险点在于 belief/strategy/relationship memory 会由玩家交互事件派生，一旦玩家通过多轮诱导制造错误信念，系统目前主要靠：

- source_event_ids 存在；
- confidence 分数；
- phase/filter；
- Director forbidden term。

这些不足以保证关键剧情判断安全。

典型风险：

- 玩家反复诱导 NPC，使 NPC 形成错误 belief memory；
- relationship/strategy memory 被一次异常互动强化；
- archival fallback 在没有 working 结果时重新拉回过期策略；
- 同一 `belief_subject` 下存在冲突记忆时，retriever 只排序，不裁决；
- `confidence` 只参与软打分，不是关键行为的硬门槛。

最优解：

- 给记忆增加 `authority_level` 或明确复用 `metadata.non_authoritative`，低权威记忆不得驱动关键披露、关系大幅变化或剧情推进；
- belief/strategy memory 需要 source event type 白名单；
- 对 `belief_subject`、`clue_id`、`world_info_id` 建 conflict set，冲突时交给 Director 或规则层裁决；
- archival fallback 只允许在低风险闲聊或非关键 topic 下启用；
- 关键 disclosure/relationship proposed action 必须引用当前 phase 可接受的证据锚点，而不是只引用记忆。

### P0：主案件还没有 NPC Skill 资产

`cases/fake_case_001/npc_skills.yaml` 存在，并覆盖了 skill contract 测试。但 `cases/mist_clock_manor` 当前没有 `npc_skills.yaml`。

这意味着：

- skill 框架是好的；
- fake case 验证了合同；
- 但主案件 NPC 的“什么时候答、怎么闪避、允许多大关系变化、允许哪些 safe fragment”还没有配置化落地。

生产风险很直接：主案件会更多依赖角色 private context、mock dialogue、Director 和默认 fallback，而不是明确的 NPC 行为状态机。

最优解：先为 `mist_clock_manor` 的关键 NPC 和关键线索补 `npc_skills.yaml`，至少覆盖：

- 江雁回：空胶囊、锁时间差、药物话题；
- 祁宴：录音带、剪辑痕迹、公开会羞辱；
- 林栖迟：红酒、安眠药、婚姻控制；
- 沈见微：停电、门锁、旧案材料。

每个 skill 必须定义 unlock condition、max disclosure mode、safe fragment refs、allowed tactics、allowed proposed actions 和 relationship delta cap。

### P1：Context budget 目前是 token 压缩，不是叙事安全压缩

`ContextBudgetManager` 只根据估算 token 比例生成 compressed history，保留 event ids 和 memory ids。它没有定义“安全必留区”。

悬疑 Agent 的 context 压缩不能只看 token。必须硬保留：

- current phase
- blocked/revealable fact ids
- selected NPC skill projections
- Director safe fragments
- disclosure constraints
- player knowledge ids
- target profile
- fact awareness ids
- security flags
- selected memory ids

否则模型可能不是忘剧情，而是忘限制。

最优解：把 context 分成 immutable safety core 和 compressible history。只有 recent events、长历史摘要、低权重 memory 描述可以压缩，合同、Director 约束、skill projection 不能压缩或丢失。

### P1：Prompt injection 防护仍偏关键词

`PromptInjectionGuard` 目前是 pattern matching，且主要是英文短语。它能抓典型 “ignore system prompt / reveal the killer”，但对中文、混合语言、角色扮演式越权和叙事伪装较弱。

好处是它已经进入 `AgentTurnPlan`，并能收窄 intent/disclosure mode。问题是召回不够。

最优解：

- 增加中文/混合语言测试集；
- 把风险类型拆成 prompt exfiltration、role override、schema override、truth exfiltration、tool escalation；
- 高风险时在生成前传入收窄后的 contract；
- 低风险时至少降低 disclosure mode 或强制 `disclosure_claims=[]`，而不是只打 trace flag。

### P1：NPC Skill 的 memory policy 尚未真正合并进 retrieval plan

`NpcSkillConfig.memory` 有 include types/scopes/layers/topic_tags/max_items，但当前真正检索使用的是 `memory_projection/*.md` 形成的 `MemoryRetrievalPlan`。NPC skill projection 里只是暴露 `memory_plan_id`，没有实际把 NPC skill memory policy 合并进检索计划。

这会产生错位：

- behavior skill 需要某类记忆，但 retrieval plan 没取；
- retrieval plan 取到了某类记忆，但当前 NPC skill 不该用；
- trace 看起来 skill 被选中，但 memory selection 并不完全由该 skill 控制。

最优解：`AgentTurnPlan` 应合并 memory projection skill 与 NPC behavior skill 的 memory policy，形成 final memory include/forbid/max_items/topic_tags。检索只使用 final plan。

### P2：现在还不是完整多 Agent 社会系统

当前 runtime 更像“玩家点名一个 NPC，单 NPC 回合处理”。这不是问题，但需要正名。

多 Agent 悬疑系统下一步应通过规则事件实现：

- scene_shared 旁听；
- NPC 二级反应；
- 关系网络传播；
- 角色之间的可审计消息；
- NPC 自主目标推进队列。

在记忆污染和 skill contract 没闭环前，不建议上开放式 NPC 自主行动。

## 建议路线

1. 先修真实 LLM 生成合同

让 `AgentGateway` / `OpenAILLMAgent` 直接接收 `LLMAgentContractInput` 或 `AgentTurnPlan`，保证事前 schema 与事后 validator 使用同一份合同。

2. 给主案件补 NPC Skill

不要只让 fake case 有 skill。`mist_clock_manor` 必须把关键 NPC x 关键线索的行为边界配置出来。

3. 合并 retrieval plan 与 NPC skill memory policy

建立真正的 final `AgentTurnPlan.memory_plan`，让 memory projection skill 和 NPC behavior skill 不再分裂。

4. 做记忆污染防线

优先实现 conflict set、authority level、source event whitelist、archival fallback gating、关键行为证据锚点。

5. 重构 context budget 为 safety-core 模型

安全约束、Director fragment、skill projection 和 output contract 永远不可压缩；只压缩历史和低风险上下文。

## 总体评价

系统架构方向正确，已经有生产系统该有的边界意识：LLM 不落库、状态变更经规则、事实披露经 Director、记忆有 scope/layer、输出有 contract、trace 有审计。

但当前离生产级 Agent 还差一个硬闭环：同一份 `AgentTurnPlan` 必须贯穿检索、context、生成、校验、trace 和规则副作用；记忆必须从“能不能看”升级到“可不可信、是否冲突、能否驱动关键行为”；主案件必须把 NPC skill 作为真实叙事资产，而不是停留在测试样例。
