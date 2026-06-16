# PostgreSQL 持久化与事件存储实现说明

日期：2026-06-15

## 范围

本轮把 P0 的核心运行时状态从纯内存推进到 PostgreSQL event stream：

- `WorldEvent` 仍是世界状态权威，数据库只为事件分配 session 内 `sequence`。
- `PostgresEventStore` 负责追加 `world_events`、幂等键、投影表和 runtime trace。
- `PostgresSessionStore` 负责创建 session，并写入 `session.created`。
- `PostgresActionRuntime` 每次从数据库事件流 replay 最新 `SessionState`，调用现有 `ActionService`，再用 `expected_current_sequence` 追加本轮事件。
- `PostgresRuntimeBackend` 让 API 路由通过统一 runtime backend 访问 session/action/events。
- `schema_admin` 提供 `apply`、`check`、`rebuild-projection` 运维入口。

默认仍是内存 runtime。生产或本地联调显式设置：

```powershell
$env:AGENT_RUNTIME = "postgres"
```

## Schema

当前 `app/storage/schema.sql` 包含：

- `schema_migrations`
- `app_sessions`
- `world_events`
- `memory_snapshots`
- `memory_operations`
- `character_impressions`
- `character_fact_awareness`
- `runtime_traces`
- `idempotency_keys`

关键约束：

- `world_events` 通过 `UNIQUE(session_id, sequence)` 保证 session 内顺序唯一。
- `app_sessions.current_sequence` 只在持有 session 行锁的事务中推进。
- 投影表只服务热读，权威恢复路径始终是 `world_events` replay。
- `runtime_traces` 是观测数据，不推进 `world_events.sequence`，也不能作为世界状态来源。

## 运维命令

生产环境应显式执行 schema 管理，不长期依赖应用启动自动改库：

```powershell
py -3.12 -m app.runtime.schema_admin check
py -3.12 -m app.runtime.schema_admin apply
py -3.12 -m app.runtime.schema_admin check
```

指定测试库：

```powershell
py -3.12 -m app.runtime.schema_admin --env-name AGENT_TEST_DATABASE_URL check
```

重建投影表默认 dry-run：

```powershell
py -3.12 -m app.runtime.schema_admin rebuild-projection
```

真正执行：

```powershell
py -3.12 -m app.runtime.schema_admin rebuild-projection --execute
```

`rebuild-projection --execute` 会清空可重建投影表，再按 `world_events(session_id, sequence)` 重放当前支持的投影逻辑。

## 事务边界

一次 action 持久化的关键路径：

```text
load stored world_events
replay SessionState
ActionService.handle(...)
collect new_events and deferred runtime traces
begin
  SELECT app_sessions FOR UPDATE
  check expected_current_sequence
  claim/replay idempotency key
  INSERT world_events
  update projection tables
  INSERT runtime_traces for this action
  UPDATE app_sessions current_sequence/current_version/narrative_phase
  commit idempotency key response_event_ids
commit
```

真实 LLM 调用和规则计算不在数据库锁内。只有事件、投影和本轮 trace 进入短事务。

## Trace 语义

PostgreSQL runtime 不再让 `RuntimeTracer` 直接写库。它使用 `RuntimeTraceBuffer`：

```text
RuntimeTracer.finish_turn
  -> RuntimeTraceBuffer
  -> PostgresActionRuntime drains buffer
  -> PostgresEventStore.append(..., runtime_traces=...)
  -> same transaction as world_events
```

这样可以保证：

- action 事件成功提交时，trace 同事务落入 `runtime_traces`。
- stale sequence、幂等冲突或 append 失败时，不会留下“未提交动作”的 trace。
- trace payload 会补 `action_event_id`，便于从观测记录追到玩家 action 事件。

`PostgresTraceSink` 仍保留，适合手动或非 action 边界的直接 trace 写入；生产 action 路径使用 deferred buffer。

## 幂等与并发

`Idempotency-Key` 以 `(session_id, idempotency_key)` 为作用域。

- 相同 key + 相同 action hash：replay 原响应事件，不重新运行 Agent/LLM。
- 相同 key + 不同 action hash：冲突。
- action 生成后发现 `current_sequence` 已推进：抛 `StaleSessionSequenceError`，事件和 trace 都不写入。

## 验证

当前测试覆盖：

- API 写入 PostgreSQL 后 runtime 重建可恢复 session。
- 幂等 replay 不重复写事件。
- 幂等 key 复用不同 action 返回冲突。
- stale sequence append 被拒绝。
- 投影表跟随 `world_events`。
- 投影表可从 `world_events` 重建。
- runtime trace payload、`llm_error_type` 和 `action_event_id` 真实写入 `runtime_traces`。
- stale sequence 失败时不写 trace。

本地验证：

```powershell
py -3.12 -m pytest -p no:cacheprovider tests\test_postgres_integration.py -q
py -3.12 -m pytest -p no:cacheprovider tests\test_postgres_schema_admin.py tests\test_postgres_trace_sink.py -q
```

## 剩余风险

- `schema_migrations` 目前只是版本标识，不是完整迁移框架；后续需要 SQL hash/drift 检测。
- 新增投影表时必须同步纳入 `rebuild_projection_tables`。
- CI 还需要独立 PostgreSQL 服务来运行 `postgres` marker。
- `runtime_traces` 目前按 payload JSONB 存完整记录，后续要按查询需求补更多索引，而不是提前拆太多列。
