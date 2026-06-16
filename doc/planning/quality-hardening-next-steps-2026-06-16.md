# Quality Hardening Next Steps - 2026-06-16

## 结论

下一阶段不要继续泛泛加 Agent 能力，应围绕四个能被量化验收的方向推进：

1. 真实玩家非标准路径覆盖。
2. 真实 LLM shadow eval。
3. PostgreSQL 性能与并发压测。
4. 语义检索能力。

优先级应是 1 -> 2 -> 3 -> 4。原因是：偏航场景先把规则和剧情边界补牢；shadow eval 再观察真实 LLM 是否稳定服从合同；Postgres 压测验证状态链路能否承载并发；语义检索最后上，因为它会放大召回能力，也会放大误召回风险。

## 偏航场景是什么

偏航场景是玩家没有按标准攻略走时，系统仍必须稳定处理的调查路径。它不是随机试玩，而是结构化回归用例。

典型偏航包括：

- 顺序偏航：先问 NPC 再找线索、先指控再收齐证据。
- 重复偏航：反复询问同一事实、重复展示同一线索。
- 对象偏航：把线索展示给错误 NPC、问不相关 NPC。
- 信息偏航：玩家直接猜真相、套话、要求 NPC 泄露内心独白。
- 结论偏航：错误指控、证据不全指控、错误 claim。
- 注入偏航：要求忽略剧情规则、输出 private memory、伪造 disclosure_claims。

偏航场景必须断言：

- 不非法推进 phase。
- 不污染 PlayerKnowledge。
- 不让错误 NPC 获得不该知道的事实。
- Director block 发生在应发生的位置，且不泄露禁说原文。
- replay 后状态一致。
- memory 召回没有因为 target_id 或 salience 带入无关事实。

建议落地：

```text
cases/<case_id>/scenarios/
  standard_path.yaml
  deviation_wrong_accusation.yaml
  deviation_repeated_probe.yaml
  deviation_wrong_npc.yaml
  deviation_spoiler_probe.yaml
  deviation_out_of_order.yaml
```

并扩展 scenario discovery，让 CI 跑所有 `standard_path.yaml` 和 `deviation_*.yaml`。

## 真实 LLM shadow eval 是什么

真实 LLM shadow eval 是“影子调用真实 LLM，但不让它改世界状态”的评测。

流程：

```text
真实/标准 scenario 跑到某一步
  -> 复制当前 SessionState
  -> 构造 AgentContext
  -> 调真实 LLM
  -> 校验输出 schema
  -> 交给 NarrativeDirector 审计
  -> 记录报告
  -> 丢弃输出，不写 WorldEvent，不改变真实 session
```

它解决的问题不是“玩家能不能通关”，而是：

- 真实 LLM 是否按结构化 `AgentIntent` 输出。
- 是否乱提 `proposed_actions`。
- 是否泄露未解锁 WorldInfo。
- 是否缺失 `disclosure_claims` 却在 speech 里碰事实。
- 是否频繁触发 Director block。
- fallback、schema invalid、timeout 是否可观测。
- 同一上下文多次调用是否漂移严重。

当前项目已有雏形：

- `app/evaluations/llm_shadow_eval.py`
- `tests/test_llm_shadow_eval.py`
- `run_standard_path_shadow_eval`
- `run_shadow_redteam_eval`
- `run_shadow_safety_benchmark`

下一步应把它变成质量门槛：

```powershell
$env:LLM_SHADOW_EVAL="1"
$env:LLM_BACKEND="real"
py -3.12 -m app.evaluations.llm_shadow_eval standard-path --case mist_clock_manor
```

如果当前没有 CLI，就补 CLI。报告必须继续脱敏，不写玩家原文、LLM 原文、private 原文和 forbidden term。

## PostgreSQL 性能与并发压测

目标不是证明“能连库”，而是证明在并发 action 下：

- world_events sequence 不乱。
- idempotency key 正确去重。
- stale sequence conflict 可预期。
- projection 表更新在同一事务内。
- runtime_traces 随事件提交。
- memory_snapshots 查询 p95 可接受。

建议新增：

```text
app/scripts/postgres_benchmark.py
tests/test_postgres_concurrency.py
doc/evaluations/postgres-benchmark-*.md
```

基准维度：

- 1 / 10 / 50 并发 session。
- 每个 session 10 / 100 / 500 action。
- 每个 session 100 / 1k / 10k memory_snapshots。
- append action p50/p95/p99。
- load/replay p50/p95。
- PostgresMemoryStore candidate query p50/p95。
- conflict/idempotency 行为。

必须用 `AGENT_TEST_DATABASE_URL`，不能误压生产库。

## 语义检索能力

当前 memory retrieval 是结构化锚点 + token + hard filter + ranking。它可控，但不够“语义”。语义检索要解决：

- 玩家换一种说法时仍能召回同一事实相关记忆。
- 中文同义表达、隐喻表达、错别字、简称能命中。
- 长期记忆里不完全包含 clue_id 的内容能被找回。

但语义检索不能绕开权限边界。正确设计是：

```text
PostgresMemoryStore SQL 预筛
  -> hard filters: scope/layer/visibility/phase/forbidden fact
  -> semantic scorer / embedding scorer
  -> reranker
  -> trace 只记录 ids 和分数摘要，不记录 content
```

建议顺序：

1. 先扩充 memory retrieval matrix，加入同义问法和 forbidden cases。
2. 再接 embedding scorer，默认关闭。
3. 再考虑 pgvector index。
4. 最后做 hybrid search：结构化锚点优先，embedding 只补召回，不做授权。

验收必须看 expected / forbidden 集合，而不是只看“召回更多”。

## 推荐推进顺序

### P1: 偏航场景

为 `mist_clock_manor` 先补 5 条：

- wrong accusation before reconstruction
- ask wrong NPC about wine
- repeat present same clue
- out-of-order medicine probe
- direct spoiler probe

目标：跑通所有偏航 scenario，且不污染状态。

### P2: 真实 LLM shadow eval

把已有 shadow eval 包成可运行命令，跑：

- standard_path
- redteam
- safety benchmark
- repeated N=20 drift run

目标：输出脱敏报告和 summary，形成人工评审入口。

### P3: Postgres benchmark

新增测试库压测脚本，先做 10 并发 session / 100 actions / 1k memories 的小规模基准。

目标：得到 p50/p95 和 conflict 行为，不追求一次性调优。

### P4: 语义检索

先补 matrix，再上 embedding scorer，最后考虑 pgvector。

目标：提高同义问法召回，同时 forbidden memory 不漂移。
