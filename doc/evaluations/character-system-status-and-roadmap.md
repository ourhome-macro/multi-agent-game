# 人物画像系统现状与推进路线

本文档评估当前人物画像系统、角色状态、世界事实、剧情推动、事件日志和 LLM 接入时机。

## 当前结论

人物画像系统已经进入 v0 可验证阶段，但还不是生产级画像系统。

当前已经具备：

- 角色卡与角色私有信息分层。
- 目标 NPC 专属的 `CharacterInnerContext`。
- NPC 对玩家的私有主观画像 `CharacterImpression`。
- 画像由运行时事件派生，而不是由 LLM 直接写状态。
- 画像会影响 mock Agent 的保守程度、暗示程度和拒答倾向。
- 事件日志和 replay 已覆盖画像、记忆、剧情阶段等派生状态。

当前仍缺：

- 世界事实模型还不够独立，事实、线索、角色认知之间的边界需要更明确。
- 人物画像目前主要支持 NPC -> player，不支持 NPC -> NPC。
- 画像更新规则仍偏启发式，缺少可配置的案件级画像规则。
- 剧情推动已经有 beat/phase，但还需要和世界事实、证据强度、玩家推理行为进一步绑定。
- LLM 接口已有雏形，但真实 LLM 不应现在作为默认后端接入生产链路。

## 人物画像系统状态

当前人物画像不是“角色真实设定”，而是“某个 NPC 如何主观看待玩家”。这是正确方向。

关键边界：

- `CharacterConfig.private` 是作者写入的角色内部事实和动机。
- `CharacterInnerContext` 是运行时为目标 NPC 构造的私有输入视图。
- `CharacterImpression` 是 NPC 对玩家的主观判断。
- `StateSummary` 不暴露私有画像。
- `WorldEvent` 可记录画像更新，但公开旅程文档不能打印画像原文。
- LLM 以后可以读取当前目标 NPC 自己的 inner context，但不能直接修改画像。

短板：

- 画像字段已经较完整，但画像更新逻辑仍集中在代码规则里。
- 画像强度、标签、触发条件还没有案件包级配置。
- 画像和“角色长期记忆”的边界需要继续收紧：记忆记录发生过什么，画像记录我如何解释你。

## 角色状态、世界事实与剧情推动

后续必须把状态拆成三层，不能混在一起：

1. 世界事实：客观发生的事实，例如谁进过书房、遗嘱是否被调换。
2. 角色认知：某个 NPC 知道、误解、隐瞒或猜测了什么。
3. 玩家已知：玩家已经发现、听说、推断或正式指控了什么。

推荐下一步增加 `WorldFact` / `FactRef` 概念：

- 每个核心真相、线索解释、角色认知都引用稳定 fact id。
- `Clue` 只说明证据本身，不直接等于真相。
- `CharacterPrivateConfig.knowledge/secrets` 应引用 fact id 或 clue id。
- `NarrativeDirector` 基于 fact id 判断当前阶段能否透露。
- `RuleEngine` 基于事件把 fact 暴露给玩家或角色认知，而不是让 Agent 自由生成事实。

剧情推动建议保持规则化：

- 玩家发现关键线索 -> 完成 narrative beat。
- 玩家向 NPC 展示相关证据 -> 增加 interaction pressure。
- 玩家提出指控 -> Rule Engine 评估 accusation claim。
- 满足 beat、线索、证据压力和阶段条件 -> 推进 narrative phase。
- phase 变化写入事件日志，并可 replay。

## 事件日志与派生状态

事件日志目前是正确的中枢。后续所有画像、记忆、剧情推动都应继续从事件派生。

必须坚持：

- 玩家行为写事件。
- NPC 回复写事件。
- Director 拦截写事件。
- Rule Engine 接受或拒绝写事件。
- 画像更新写事件。
- 记忆候选与快照写事件。
- 剧情 beat 和 phase 变化写事件。

关键原则：

- replay 不应重新跑 LLM。
- replay 不应重新推导不确定内容。
- replay 应直接应用已记录的派生事件。
- 如果某个状态不能从事件恢复，就不应进入核心运行时。

## LLM 接入时机

现在可以做 LLM 接口验证，但不建议立刻把真实 LLM 作为默认运行后端。

可以接入 LLM 的条件：

- `AgentContext` 和 `CharacterInnerContext` 已稳定。
- `AgentIntent` schema 已稳定。
- Narrative Director 能阻止禁说事实和私有原文泄漏。
- Rule Engine 能拒绝非法 proposed_actions。
- mock Agent 和 llm_stub 的测试全绿。
- 事件日志能记录 LLM 输入摘要、输出摘要、校验失败原因和降级结果。

当前更合理的接入节奏：

1. 保持 `mock` 为默认后端。
2. 使用 `llm_stub` 做 schema 合同测试。
3. 将 `real` LLM 后端放在显式环境变量开关后。
4. 先只允许真实 LLM 生成 `speech`、`intent`、`emotional_shift`。
5. 暂时禁止真实 LLM 提出剧情阶段变化。
6. 真实 LLM 的 proposed_actions 只允许有限白名单，例如关系微调。
7. 所有真实 LLM 输出必须经过 schema 校验、Director 校验、Rule Engine 校验。

## 推荐推进顺序

第一步：收紧世界事实层。

- 增加事实模型和案件包 fact 配置。
- 让线索、秘密、禁说事实、结案声明引用 fact id。
- 测试事实引用错误时启动失败。

第二步：完善角色认知层。

- 把 `private.knowledge/secrets/goals` 全部从自然语言字符串升级为带 id 的结构化对象。
- 增加 `known_fact_refs`、`misbelief_refs`、`conceal_fact_refs`。
- 保证 NPC 只能接收自己认知范围内的事实。

第三步：增强画像系统。

- 把画像派生规则从硬编码逐步迁移到案件包配置。
- 增加 NPC -> NPC 画像，但默认不进入 Agent 上下文，除非有事件传播。
- 明确画像衰减、叠加、冲突解决和来源事件。

第四步：稳定剧情推动。

- 把 narrative beat、phase transition、accusation evaluation 与 fact/clue/player knowledge 绑定。
- 增加完整案件路径测试和反路径测试。
- 确保玩家提前问真相时只产生压力、画像变化或拒答，不直接推进真相。

第五步：受控接入真实 LLM。

- 默认仍用 mock。
- real LLM 只在 `LLM_BACKEND=real` 时启用。
- 先做开发环境可用，不承诺生产稳定。
- LLM 失败、超时、schema 错误必须降级为安全拒答。

## 最优判断

人物画像系统现在完成度约为 60%。

它已经不是空概念：有模型、有事件、有派生、有上下文隔离、有测试。但它还不是成熟系统，因为缺少事实层锚点、案件级画像规则、NPC -> NPC 社交画像和真实 LLM 压测。

最正确的下一步不是马上接 LLM，而是先把“事实 -> 角色认知 -> 玩家已知 -> 画像解释 -> 叙事推进”这条链彻底打牢。LLM 应该在这条链稳定后作为表达层进入，而不是提前成为状态源。
