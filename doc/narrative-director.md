# Narrative Director

当前 Director 是最小剧透防护器，负责在 NPC 回复落入事件日志前检查禁说事实。它不负责推进剧情阶段；phase 和 beat 由 `narrative_rules.yaml` 和 Rule Trigger System 控制。

## 配置来源

禁说事实定义在每个案件包的 `forbidden_facts.yaml`，当前示例案件位于：

- `cases/fake_case_001/forbidden_facts.yaml`
- `cases/fake_case_002/forbidden_facts.yaml`

- `id`：禁说事实标识。
- `text`：事实说明。
- `blocked_terms`：触发拦截的文本片段。
- `reveal_phase`：允许透露的剧情阶段。

## 检查规则

`NarrativeDirector.validate(case, narrative, intent)` 会扫描 `intent.speech`。如果文本包含某个禁说事实的 `blocked_terms`，且当前 `narrative.phase` 不是该事实的 `reveal_phase`，则返回拒绝决策。这里的 `phase` 来自 `narrative_rules.yaml` 中声明的 phases。

被拒绝时：

- 不写入 `npc.replied`。
- 写入 `director.blocked`。
- 返回安全回复 `我现在还不能谈这个。`
- `ActionResponse.accepted=false`。

## 当前局限

- 只做关键词阻止，不做语义级剧透检测。
- 当前只检查 `AgentIntent.speech`，不检查复杂推理链、`memory_refs` 或 proposed action 语义。
- 不负责线索释放或 phase 推进；这些由 Rule Engine 和 Rule Trigger System 执行。

这些局限是有意保留的。当前目标是先建立可测试的叙事边界，而不是过早引入真实 LLM 审查。
