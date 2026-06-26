# Evaluations 导读

本目录保存评测矩阵、质量门槛和阶段性评测报告。评测文档用于证明能力是否稳定，不替代架构契约。

当前项目状态先看 [../CURRENT.md](../CURRENT.md)。

## 核心评测入口

- [memory-retrieval-matrix-2026-06-15.md](memory-retrieval-matrix-2026-06-15.md)：记忆检索应召回 / 禁止召回矩阵。
- [scenario-runner-and-ci-acceptance-v0.md](scenario-runner-and-ci-acceptance-v0.md)：场景 runner 与 CI 接受标准。
- [scenario-level-regression-harness-v0.md](scenario-level-regression-harness-v0.md)：场景级回归框架。
- [p0-regression-matrix.md](p0-regression-matrix.md)：P0 硬链路回归矩阵。
- [llm-shadow-eval-v0.md](llm-shadow-eval-v0.md)：LLM Shadow Eval 方案。

## 案件质量与专项

- [full-case-quality-review-2026-06-16.md](full-case-quality-review-2026-06-16.md)
- [mist-clock-manor-case-authoring-linter-2026-06-17.md](mist-clock-manor-case-authoring-linter-2026-06-17.md)
- [mist-clock-manor-deviation-scenarios-phase1-2026-06-16.md](mist-clock-manor-deviation-scenarios-phase1-2026-06-16.md)
- [semantic-memory-retrieval-phase1-2026-06-16.md](semantic-memory-retrieval-phase1-2026-06-16.md)
- [postgres-benchmark-phase1-2026-06-16.md](postgres-benchmark-phase1-2026-06-16.md)

## 维护规则

- 新增检索策略、embedding、reranker、memory scope 规则时，必须更新或新增 memory retrieval matrix。
- 新增剧情关键路径时，必须有 scenario-level regression。
- 真实 LLM 评测只作为 shadow 或专项报告，不得替代 mock deterministic 回归。

