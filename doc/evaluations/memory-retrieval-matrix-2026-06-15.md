# Memory Retrieval Matrix - 2026-06-15

## 目标

Memory Retrieval Matrix 用来锁定“某个剧情阶段、某个玩家问法，应召回/不应召回哪些 `memory_id`”。它不是 LLM 评测，也不验证台词质量；它只验证记忆检索和 AgentContext 记忆投影的确定性边界。

核心生产风险很明确：后续替换 BM25、embedding、reranker 或修改 projection skill 时，不能让 NPC 忘掉关键 typed memory，也不能把其他 NPC 私有记忆、`director_audit` 或未授权记忆塞进普通 NPC 上下文。

## 矩阵格式

每条矩阵 entry 至少包含：

- `case_id`
- `phase`
- `action`
- `target_id`
- `subject`
- `clue`
- `claim`
- `expected_memory_ids`
- `forbidden_memory_ids`
- `notes`

Python dataclass 对应 `MemoryRetrievalMatrixEntry`，也支持从 YAML / JSON 列表读取。示例：

```yaml
- entry_id: mist_clock_manor.opening.jiang.empty_capsules
  case_id: mist_clock_manor
  phase: opening
  target_id: jiang_yanhui
  action:
    type: talk
    text: Ask Jiang again about empty_capsules and medicine pressure.
  subject: player
  clue: empty_capsules
  claim: null
  expected_memory_ids:
    - memory.player.belief.jiang_yanhui.empty_capsules
    - memory.player.relationship.jiang_yanhui.empty_capsules
    - memory.player.strategy.jiang_yanhui.empty_capsules
  forbidden_memory_ids:
    - memory.player.presented_clue.shen_zhaoye.empty_capsules
    - memory.player.director_blocked.jiang_yanhui.jiang_yanhui_mechanism
  notes: Jiang can recall his own typed medicine-pressure memory only.
```

## 当前实现

新增模块：`app/evaluations/memory_retrieval_matrix.py`。

它提供：

- `MemoryRetrievalMatrixEntry`：强类型矩阵 entry。
- `MemoryRetrievalMatrixEvaluator`：确定性 evaluator。
- `evaluate_memory_retrieval_matrix(...)`：函数式入口。
- `load_memory_retrieval_matrix(path)`：从 YAML / JSON 读取矩阵。
- `MemoryRetrievalMatrixReport.assert_passed()`：输出缺失和误召回的具体 `memory_id`。

Evaluator 支持两种目标：

- `source="retriever"`：直接验证 `MemoryRetriever.retrieve(...)`。
- `source="agent_context"`：验证 `AgentContext.memory_snapshots`，可传入已构造 context，也可让 evaluator 调用 `build_agent_context(...)`。

这两个目标不能混为一谈。`MemoryRetriever` 验证底层召回质量和隔离边界；`AgentContext` 还会受到当前 `MemoryProjectionSkill`、剧情阶段和 `max_memory_items` 的投影影响。

## mist_clock_manor 基线

当前回归测试覆盖：

- `opening` 阶段。
- 目标 NPC：`jiang_yanhui`。
- 线索：`empty_capsules`。
- 江雁回应召回自己的 typed memory：
  - `memory.player.belief.jiang_yanhui.empty_capsules`
  - `memory.player.relationship.jiang_yanhui.empty_capsules`
  - `memory.player.strategy.jiang_yanhui.empty_capsules`
- 沈照夜的私有互动记忆不得进入江雁回普通 NPC 召回：
  - `memory.player.presented_clue.shen_zhaoye.empty_capsules`
- `director_audit` 不得进入普通 NPC：
  - `memory.player.director_blocked.jiang_yanhui.jiang_yanhui_mechanism`

测试文件：`tests/test_memory_retrieval_matrix.py`。

## 扩展规则

新增矩阵时优先覆盖这些风险点：

- 同一 clue 对不同 NPC 生成的 `npc_private` memory 不串线。
- `scene_shared` 只对场景在场 NPC 可见。
- `director_audit` 只允许 Director 审计入口读取，普通 NPC 禁止。
- opening / confrontation / reconstruction 等 phase 下，projection skill 是否按预期收窄或放宽 memory type。
- `archival` 冷召回只在常规 core / working 无相关命中时出现，且不放宽 NPC 可见性。

每条矩阵必须写清楚 `notes`，说明为什么 expected / forbidden 集合成立。禁止只写“应该通过”这种不可审计说明。

## 换检索方案前后的验收

替换 BM25、embedding、reranker 或修改 `MemoryRetriever` 排序前：

1. 先跑现有矩阵，确认基线全绿。
2. 改实现。
3. 再跑同一矩阵，expected / forbidden 集合必须一致。
4. 如果排序策略也作为产品承诺，需要新增单独排序断言；当前矩阵默认只锁定集合，不锁定顺序。

最低验收命令：

```powershell
py -3.12 -m pytest tests\test_memory_retrieval_matrix.py
```

如果变更影响 projection skill、AgentContext、记忆隔离或 scenario harness，还必须跑相关记忆测试和剧情级回归测试。
