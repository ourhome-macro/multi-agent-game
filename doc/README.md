# 文档入口

本目录分成两类文档：

- 当前有效契约：根目录下的核心文档，描述现在代码应该遵守的架构、状态、Agent、Director 和 API 边界。
- 历史与专题记录：子目录下的 dated 文档，保留决策过程、评审、评测、实现记录和规划，不作为最新事实的唯一来源。

读文档时优先按下面顺序看，不要从 `reviews/` 或 `planning/` 里随机翻旧结论。

## 当前必读

- [CURRENT.md](CURRENT.md)：当前项目状态、主要风险、下一步顺序。
- [architecture.md](architecture.md)：运行时架构、状态权威链路、模块边界。
- [world-state.md](world-state.md)：`SessionState`、`WorldEvent`、记忆、玩家已知、replay。
- [agent-design.md](agent-design.md)：Agent 输入输出、LLM 合同、记忆检索、NPC Skill。
- [narrative-director.md](narrative-director.md)：剧透防护、safe fragment、Director 审计。
- [api-contract.md](api-contract.md)：HTTP API 契约和公开状态投影。

## 当前专题

- [frontend/threejs-frontend-plan.md](frontend/threejs-frontend-plan.md)：Three.js 前端架构和接入顺序。
- [runtime/token-cost-optimization.md](runtime/token-cost-optimization.md)：真实 LLM token 成本根因和瘦身计划。
- [architecture/p0-hard-chain-2026-06-16.md](architecture/p0-hard-chain-2026-06-16.md)：P0 状态权威硬链路。
- [agents/llm-agent-contract.md](agents/llm-agent-contract.md)：LLM 输入/输出合同细节。
- [evaluations/memory-retrieval-matrix-2026-06-15.md](evaluations/memory-retrieval-matrix-2026-06-15.md)：记忆召回矩阵评测。

## 子目录说明

- [agents/](agents/)：Agent 合同、NPC Skill、角色内心上下文、画像等专题。
- [architecture/](architecture/)：持久化、P0 链路、PostgreSQL、结构草案。
- [case/](case/)：具体案件文档和评测产物。
- [case-authoring/](case-authoring/)：案件包、场景脚本、作者协议。
- [evaluations/](evaluations/)：评测方案、CI 接受标准、shadow eval 结果。
- [frontend/](frontend/)：前端规划、交互参考、Three.js 方案。
- [narrative/](narrative/)：叙事披露策略和测试矩阵。
- [planning/](planning/)：路线图和阶段计划，优先看 [planning/README.md](planning/README.md)。
- [reviews/](reviews/)：历史评审与复盘，优先看 [reviews/README.md](reviews/README.md)。
- [runtime/](runtime/)：运行时专项说明，例如 token budget。

## 维护规则

- 架构、状态模型、Agent、Director、API 的当前事实必须同步更新根目录核心文档。
- 新评审放入 `reviews/`，但如果结论仍然有效，必须把结论合并进 `CURRENT.md` 或对应核心文档。
- 新规划放入 `planning/`，但落地后的长期规则必须迁移进核心文档。
- 案件专属产物放入 `case/<case_id>/`。
- 不再新增乱码或重复入口文档；发现乱码文档时优先重写为 UTF-8。
