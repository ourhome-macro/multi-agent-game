# 证据与事实图校验门槛

日期：2026-06-15

案件包现在把 evidence / claim graph 一致性视为加载期硬门槛，而不是运行时兜底。

必要校验：

- 每个可到达 `Clue` 必须设置 `reveals_world_info`，并指向已声明的 `WorldInfo`。
- 每个 `WorldInfo` 必须至少被线索、角色 private 状态、forbidden fact、solution claim 或 claim graph 条件引用。
- 完全孤立的事实会被拒绝，因为事件日志无法审计它如何进入剧情。
- `claim_graph.safe_fragments[*].unlock_conditions` 只能引用已声明 phase、completed beat、已声明 clue、玩家 world info id，以及能由线索发现实际产生的 player knowledge id。
- `sensitivity=high` 的 `WorldInfo` safe fragment 必须设置非空 `unlock_conditions`；否则视为早期泄密风险。
- `claim_graph.forbidden_inferences[*].trigger_fragment_ids` 必须引用同一 `WorldInfo` 下的 safe fragment，且 forbidden inference id 不能与 safe fragment id 冲突。
- 每个 `solution_claim` 必须定义非空 `required_evidence` 和 `required_world_info`。required evidence 必须可到达，required world info 必须能由这组 evidence 产生。

失败信息必须带 owning field 和 id，例如：

```text
Solution claim 'shared_death_chain' required_world_info ...
WorldInfo 'killer_fact' safe fragment 'identity_hint' ...
```

作者应该修案件图谱，不能靠 prompt 文案或运行时特殊分支补洞。
