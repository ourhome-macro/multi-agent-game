# 文档索引

根目录只保留长期稳定的核心契约文档。专题文档、历史实施记录、评测产物和 code review 记录按主题下沉到子目录。

## 核心文档

- [architecture.md](architecture.md)：总体架构和运行边界。
- [world-state.md](world-state.md)：世界状态、事件、记忆和回放模型。
- [agent-design.md](agent-design.md)：Agent 行为、上下文、记忆投影和 LLM 约束。
- [narrative-director.md](narrative-director.md)：剧透防护、事实披露和导演校验。
- [api-contract.md](api-contract.md)：HTTP API 契约。

## 专题目录

- [agents/](agents/)：Agent 合同、角色内心上下文、角色画像等专题。
- [architecture/](architecture/)：结构草案、持久化方案和历史架构材料。
- [case-authoring/](case-authoring/)：案件包、场景脚本、作者协议。
- [case/](case/)：具体案件的重建、运行产物和评测报告。
- [narrative/](narrative/)：叙事披露策略、测试矩阵。
- [evaluations/](evaluations/)：评测框架、shadow eval、CI 验收。
- [planning/](planning/)：历史路线图和 MVP 规划。
- [agent-runtime-mvp/](agent-runtime-mvp/)：Agent runtime MVP 阶段实施记录。
- [reviews/](reviews/)：code review 和阶段性审查记录。

## 维护规则

- 架构、Agent、Narrative Director、世界状态、API 的当前事实必须更新根目录核心文档。
- 历史实施记录不要继续堆在根目录，放入对应专题目录。
- 新的审查或复盘放入 `reviews/`，文件名带日期。
- 案件专属产物放入 `case/<case_id>/`。
