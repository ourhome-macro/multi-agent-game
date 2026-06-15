# Director 结构化事实网关

日期：2026-06-15

## 目标

Director 不能只依赖 forbidden terms 字符串拦截。结构化事实网关把 `WorldInfo` 拆成可审计的 claim graph：

- safe fragments：当前阶段可以安全暗示或部分披露的事实片段。
- unlock conditions：片段披露前必须满足的阶段、beat、玩家已知或线索条件。
- forbidden inferences：多个片段或事实组合后会推出核心真相时必须阻止。

## 当前实现

- `WorldInfoConfig.claim_graph`
- `SafeFactFragmentConfig`
- `ForbiddenInferenceConfig`
- `FactUnlockConditionConfig`
- `app/director/fact_gateway.py`

`NarrativeDirector.validate(...)` 已接入后置校验：

- `disclosure_claims.claim_refs` 引用未解锁 safe fragment 会被拦。
- `speech` 命中未解锁 safe fragment alias/pattern 会被拦。
- `speech` 命中 locked forbidden inference alias/pattern 会被拦。
- claim graph 为空时兼容旧案件。

## 未完成

前置摘要已有 `NarrativeDirector.fact_gateway_summary(...)`，但尚未注入 `AgentContext`。下一步应把 revealable fragments 的安全摘要投影给 LLM，同时只给 locked fragments 的 id 和原因，不给敏感文本。

复杂 paraphrase 仍需后续语义分类或专门的 Director eval 覆盖；当前实现是结构化规则图加 literal/regex 检测。
