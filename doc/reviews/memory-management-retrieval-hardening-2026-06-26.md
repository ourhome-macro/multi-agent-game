# Memory 管理与检索召回风险治理

日期：2026-06-26

## 本轮目标

按 memory 管理和检索召回的同一条链路处理风险点，避免只优化召回排序却破坏 NPC 视角、DB 后端候选集或长期维护边界。

## 已解决问题

1. 记忆派生 ID 和 metadata 收敛
   - clue、scene_shared、accusation、interaction 派生统一使用 helper 生成稳定 `memory_id`。
   - clue memory metadata 统一包含 `topic_tags`、`world_info_id`、case thread 字段和来源字段。
   - `derivations.py` 恢复旧常量 re-export，避免 P2 拆文件破坏既有导入。

2. Skill plan 的 topic tag 真正进入检索边界
   - `RetrievalPlanner` 读取 base skill 和 progressive rule 的 `include.topic_tags`。
   - `MemoryRetriever.memory_allowed_by_plan(...)` 继续把 topic tag 当 hard filter，不靠 scorer 排序兜底。

3. Postgres 候选预筛不再和 semantic recall 脱节
   - `MemoryStoreQuery` 携带 query anchors 和 query tokens。
   - `PostgresMemoryStore` 在 scope/layer/type/visibility/phase 后做轻量 SQL 预筛。
   - `query_tokens` 使用 semantic tokens，而不是只用玩家原文 tokens，避免中文改写或 world_info alias 在 DB 层提前漏召回。
   - trace 只记录 term 数量和是否启用预筛，不记录具体 term 或 memory content。

4. 默认 deterministic semantic recall 收紧
   - 从 `CasePackage` 的 clue/world_info 构造 alias graph。
   - semantic scorer 只给 query 已锚定的 concept 打分，不扫描全案 concept。
   - clue alias 不再把 `related_characters` / `related_events` 当同义词。
   - 单个普通英文 token 不能扩展整条案件链；需要短语命中、多个有效 token，或强 CJK / 长英文 token。
   - 补了 CJK、snake_case、camelCase、hyphen 和常见英文词形处理。

5. target relevance 和内容 anchor 分离
   - `target_id` 不再作为内容 anchor，也不参与 metadata 匹配。
   - 没有内容 anchor 时，才使用低权重 target relevance 召回当前 NPC owner/visible 的私有或场景共享记忆。
   - 这保留“刚私下展示证据后普通 talk 能取回目标 NPC 私有记忆”，同时避免“问管家”把所有 metadata 里带 butler 的 case/core 线索拉进上下文。

## 关键回归

- `cut_power_trace` 在 investigation 阶段不会因为 `trace/power` 单词把 reconstruction 案件链兄弟节点提前扩出来。
- `drawer scratches` 会命中 `scratched_drawer`，不会额外带出 `dustless_frame`。
- 中文“药壳子/药盒空壳”和英文 “empty medicine shells / pill bottle” 能召回医药线索记忆。
- world_info 命中能反向补到 linked clue anchor。
- semantic scorer 仍在 hard filters、forbidden fact、phase、visibility 和 plan 之后运行。

## 验证

```powershell
py -3.12 -m ruff check app\agents\memory.py app\agents\memory_retrieval.py app\agents\retrieval_planner.py app\runtime\derivations.py app\runtime\derivation_utils.py app\runtime\derivation_clue_memory.py app\runtime\derivation_scene_shared_memory.py app\runtime\derivation_accusation_memory.py app\runtime\derivation_interaction_memory.py app\runtime\tracing.py app\storage\postgres.py tests\test_memory_db_retrieval.py tests\test_memory_projection_skills.py tests\test_memory_retrieval_quality.py tests\test_memory_derivation_helpers.py tests\test_typed_memory.py

py -3.12 -m pytest tests\test_memory_derivation_helpers.py tests\test_memory_projection_skills.py tests\test_npc_skill_memory_policy.py tests\test_memory_v2.py tests\test_memory_archival_p2.py tests\test_memory_db_retrieval.py tests\test_agent_runtime_remaining_phases.py tests\test_memory_scope.py tests\test_npc_memory_isolation.py tests\test_mist_clock_manor_memory_boundaries.py tests\test_present_clue_structured_contract.py tests\test_postgres_trace_sink.py tests\test_router_trace.py tests\test_typed_memory.py tests\test_memory_retrieval_quality.py tests\test_memory_retrieval_matrix.py -q
```

结果：focused memory / retrieval 集成集 `142 passed`，ruff 通过。

## 剩余风险

- 还没有引入真正的向量召回或 reranker；当前 semantic scorer 是 deterministic 第一阶段补强，适合锁边界，不适合作为最终语义搜索方案。
- Postgres SQL 预筛仍是 OR 式轻量匹配，后续数据量上来后需要用真实 explain / trace 数据决定是否加全文索引或独立检索表。
- alias graph 依赖案件包作者维护 clue/world_info 的 title、description、aliases、claim_patterns；缺少 authoring 质量 gate 时，召回质量会随案件包波动。
