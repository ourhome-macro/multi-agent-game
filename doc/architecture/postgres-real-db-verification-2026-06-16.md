# PostgreSQL Real DB Verification - 2026-06-16

## 验证结论

已使用 `.env` 中的 `AGENT_DATABASE_URL` 连接真实 PostgreSQL。连接串和凭据未写入日志或文档。

本次验证覆盖三层：

- schema migration check/apply/check
- PostgreSQL runtime 事件持久化
- PostgreSQL-backed memory candidate retrieval

## 执行结果

初始检查：

```text
schema version is not installed; missing tables: schema_migrations
```

执行 schema apply：

```text
001_initial_runtime_schema schema version 1 is installed; core tables are present and checksum matches.
```

再次独立 check：

```text
001_initial_runtime_schema schema version 1 is installed; core tables are present and checksum matches.
```

## Runtime Smoke

使用 `fake_case_001` 创建真实 Postgres session，并通过 runtime backend 执行：

1. `inspect desk`
2. `ask_about butler scratched_drawer`

为避免调用外部 LLM，AgentGateway 显式使用 `llm_stub`。

Smoke session:

```text
fa298fb2-d8d5-4b59-9075-da72a0e5ce24
```

持久化信号：

```text
persisted_event_count=15
memory_snapshot_rows=2
runtime_trace_rows=1
```

`ask_about` 事件序列：

```text
player.asked_about
npc_skill.selected
npc.replied
character_impression.updated
character_fact_awareness.updated
memory_candidate.created
agent_memory_snapshot.updated
```

Runtime trace 中的 memory store 摘要显示生产路径已走 PostgreSQL：

```text
backend=postgres
candidate_count=1
phase=investigation
target_id=butler
layers=core, working
scopes=case, npc_private, scene_shared, session
memory_types=belief, episodic
```

## 注意事项

- 本次 smoke 会在真实库留下一个测试 session，用于审计本次验证。
- 如需清理，应只删除上述 session id 对应的 `app_sessions` 记录，依赖外键级联清理事件和投影。
- 真实 PostgreSQL 已验证连接和基本读写，但还没有做并发写入压测、长事务恢复、备份恢复演练或 EXPLAIN 级性能分析。
