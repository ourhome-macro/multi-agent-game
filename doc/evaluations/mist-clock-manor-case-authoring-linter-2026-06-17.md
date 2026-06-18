# Mist Clock Manor Case Authoring Linter

这是 `mist_clock_manor` 上生产前的最小静态 lint，不是通用作者平台、编辑器校验器或市场化 case schema。它的目标是阻断当前生产候选中最容易发生的 YAML 静态错配，并复用 `CaseLoader` 已有 schema 与引用校验。

## 入口

```powershell
py -3.12 -m app.scripts.case_linter --case mist_clock_manor
py -3.12 -m app.scripts.case_linter --case mist_clock_manor --format json
py -3.12 -m app.scripts.case_linter --case mist_clock_manor --format md --output doc/evaluations/case_lint_report.md
```

CLI 返回码为生产门禁语义：通过返回 `0`，存在 violation 返回 `1`。

## 当前规则

- 先读取 raw YAML，再运行 `CaseLoader`，覆盖 world_info、clue、hotspot、skill、memory rule、scenario 等基础 schema 和引用 ID 校验。
- 如果 `CaseLoader` 因 schema 或引用错误失败，linter 仍会继续运行 raw YAML 静态门禁，避免只输出一条泛化 loader 错误而遮住更关键的 authoring 问题。
- 玩家可经由线索或标准路径接触到的高敏 `world_info` 必须有 `claim_graph.safe_fragments`，且每个 safe fragment 必须带 unlock 条件。纯最终综合真相如果不通过线索直接披露，不能为了过 lint 伪造可说 fragment。
- `key: false` 的可选厚度线索不得进入核心 narrative beat，也不得进入标准路径最终强制期望或正确 claim 必需证据。
- `backtrack_unlocks` 必须能由已存在 hotspot、clue、beat 条件到达，且必须要求当前 hotspot 的 prior inspection，避免首查解锁。
- 允许 `relationship.change` 的 `npc_skill` 必须配置 `max_relationship_delta`。
- `memory_derivation_rules` 的每个 effect 必须有 `source_event_ids`。`belief`、`relationship`、`strategy` 这类高影响记忆，或缺失来源事件的 effect，必须明确 `authority_source` 或 `non_authoritative` 之一；普通事件型 `episodic` memory 可以依赖模型默认 `event_observed`。
- `forbidden_facts.blocked_terms` 不得与公开 clue/world_info 的 title 或 description 完整撞词。

## 边界

这个 linter 只接受 `mist_clock_manor`。如果未来要支持多案例，需要先把 case authoring 协议、可选线索标记、标准路径定义和 forbidden term 策略抽成稳定产品接口；当前实现故意不做这些泛化，避免在唯一生产案例上线前引入不必要平台复杂度。
