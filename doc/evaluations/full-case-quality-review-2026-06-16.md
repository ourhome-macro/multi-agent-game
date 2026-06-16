# Full Case Quality Review - 2026-06-16

## 结论

当前项目已经具备“规则权威 + Agent 表达 + 可回放事件流”的基础生产形态。完整案件标准路径、上下文边界、Director 审计、runtime trace、memory retrieval matrix 和 PostgreSQL-backed memory candidate retrieval 在测试内均通过。

但这不等于已经完成真实线上质量闭环。当前最可靠的是规则化悬疑链路、事件可回放、memory scope/layer/visibility 约束；最薄弱的是真实 LLM 长程输出质量、真实玩家非标准路径覆盖、PostgreSQL 性能/并发压测和语义检索能力。

## 本次测试

完整案件级：

```powershell
py -3.12 -m pytest -q tests\test_runtime_scenario.py tests\test_scenario_evaluation_harness.py tests\test_standard_scenario_discovery.py tests\test_mist_clock_manor_scenario.py
```

结果：

```text
6 passed
```

上下文、Director、观测与 P0 链路：

```powershell
py -3.12 -m pytest -q tests\test_agent_runtime_mvp.py tests\test_agent_runtime_remaining_phases.py tests\test_agent_prompt_phase2.py tests\test_director_fact_gateway.py tests\test_director_generation_gateway.py tests\test_narrative_director_disclosure_audit.py tests\test_fact_disclosure_strategy_matrix.py tests\test_progressive_disclosure_skill.py tests\test_p0_regression_matrix.py tests\test_router_trace.py tests\test_postgres_trace_sink.py tests\test_real_llm_observability.py
```

结果：

```text
84 passed
```

Memory 系统专项：

```powershell
py -3.12 -m pytest -q tests\test_memory_retrieval_matrix.py tests\test_memory_retrieval_quality.py tests\test_memory_db_retrieval.py tests\test_memory_scope.py tests\test_memory_layer.py tests\test_memory_v2.py tests\test_memory_archival_p2.py tests\test_memory_projection_skills.py tests\test_typed_memory.py tests\test_npc_memory_isolation.py tests\test_mist_clock_manor_memory_boundaries.py
```

结果：

```text
92 passed
```

全量回归：

```powershell
py -3.12 -m pytest -q
```

结果：

```text
527 passed
```

## 完整案件质量

当前完整案件测试覆盖：

- `fake_case_001`、`fake_case_002` 完整 runtime snapshot。
- 标准 scenario harness 的逐步事件序列、阶段、玩家知识、角色 awareness、Director block 和 replay 等价性。
- `mist_clock_manor` 标准路径 discovery + scenario 运行。

这说明标准路径能够从开局推进到解决阶段，且关键状态来自事件日志重放，不依赖不可见隐式状态。

当前缺口：

- 真实玩家自由输入路径仍不足，需要更多偏航路径、错误指控、重复询问、跨角色绕问测试。
- 完整案件质量主要是规则和 mock/stub Agent 下的确定性质量，不代表真实 LLM 文风、节奏和误导能力已达标。

## 观测与上下文

已处理到当前生产固化所需的第一阶段：

- Runtime trace 记录 `memory_projection`、`npc_skill_projection`、Director decision、LLM fallback、schema validation error、new event types 和 phase before/after。
- trace sanitizer 禁止写入 memory content、private summary、prompt 全文和敏感玩家文本。
- PostgreSQL trace sink 已覆盖，Postgres runtime 会事务性 buffer trace 并随事件提交。
- AgentLoop 的 `memory_snapshots`、`memory_ids_used`、trace `memory_projection` 和 tool summary 来自同一次注入 retriever，避免上下文与观测各说各话。
- Narrative Director 前后置约束仍在 LLM 外部执行，NPC 输出不能越过规则直接改世界状态。

仍未闭环：

- 没有真实监控面板、指标告警、trace 采样策略。
- 还没有长上下文多小时会话的压缩质量评测。
- 真实 LLM 输出只覆盖 observability/fallback 合同，不等于稳定内容质量评测。

## Memory 系统可行性

当前 memory 系统在“结构化、可回放、可审计”的方向是可行的：

- memory snapshot 来源于 WorldEvent 和 derivation rule，不是 LLM 直接写库。
- scope/layer/type/owner/visible/phase/forbidden fact 均有 hard filter。
- retrieval matrix 覆盖 expected / forbidden memory，防止 salience 或 target_id 把无关记忆带入上下文。
- archival cold recall 只在 working/core 无命中时触发，且不放宽可见性和 forbidden fact。
- PostgreSQL runtime 已注入 `PostgresMemoryStore`，真实 smoke 中 trace 显示 `backend=postgres` 且有 candidate 命中。

当前 memory 不是“最终形态”：

- 尚未接 pgvector / embedding / hybrid search。
- Postgres 查询只做第一阶段候选预筛，真实相关性仍由 Python ranking 和 hard filters 完成。
- 没有大规模记忆量下的性能基准、EXPLAIN 分析、索引选择验证。
- 没有真实玩家长期游玩产生的记忆漂移评估。

## 当前质量评级

- 规则权威链路：可进入生产前硬化阶段。
- 完整案件标准路径：通过，可作为 CI gate。
- 上下文安全边界：当前测试内可信。
- 观测链路：具备审计基础，但不是完整运维观测体系。
- Memory 系统：架构方向可行，第一阶段能用；语义检索和规模化还没完成。
- 真实 LLM 叙事质量：还不能判定为生产达标，需要 shadow eval 和人工剧本评审。

## 下一步建议

1. 把完整 scenario harness 和 memory matrix 纳入 CI 必跑。
2. 增加真实 Postgres 的 nightly smoke，包括 schema check、runtime action、trace、memory store backend。
3. 为 `mist_clock_manor` 增加 5-10 条偏航场景：重复询问、错误指控、绕开线索追问、跨角色泄密试探。
4. 加真实 LLM shadow eval：同一固定事件序列跑 20 次，统计 Director block、fallback、schema validation、forbidden term 和 disclosure claim 漂移。
5. 做 memory 性能基准：1k/10k/100k snapshot 下的 retrieval latency、candidate count、SQL EXPLAIN 和 trace 体积。
