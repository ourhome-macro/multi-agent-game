# PostgreSQL 持久化与事件存储实现说明

日期：2026-06-15

## 实现范围

本次实现覆盖第一阶段的可落地骨架：

- 新增 `app/storage/schema.sql`，定义生产持久化最小表集。
- 新增 `PostgresEventStore`，负责 `WorldEvent` 追加写入、session 内 sequence 分配、幂等键处理和投影表同步。
- 新增 `PostgresSessionStore`，负责创建 session、写入 `session.created`、按事件流 replay 恢复 `SessionState`。
- 新增 `app/runtime/database.py`，提供环境变量读取、PostgreSQL 连接和 schema 初始化入口。
- 新增 `PostgresActionRuntime`，按数据库事件流 replay 最新 session，调用现有 `ActionService`，再用 `expected_current_sequence` 追加本轮新事件。
- 新增 `PostgresRuntimeBackend`，让 FastAPI 路由通过统一 runtime backend 访问 session/action/events。
- `POST /sessions/{session_id}/actions` 支持 `Idempotency-Key` 请求头。
- `app/main.py` 支持 `AGENT_RUNTIME=postgres` 切换到 PostgreSQL runtime；默认不设置时仍使用内存 runtime，避免本地测试强依赖数据库密码。

`WorldEvent` 领域模型仍不携带 sequence；sequence 是数据库事件流元数据，由 PostgreSQL 事务分配。

## Schema

`app/storage/schema.sql` 当前包含：

- `app_sessions`
- `world_events`
- `memory_snapshots`
- `memory_operations`
- `character_impressions`
- `character_fact_awareness`
- `runtime_traces`
- `idempotency_keys`

核心约束：

- `world_events` 是权威事件日志，`UNIQUE (session_id, sequence)` 保证同一 session 内顺序唯一。
- `app_sessions.current_sequence` 只在持有 session 行锁的事务中推进。
- `memory_snapshots`、`character_impressions`、`character_fact_awareness` 都通过 `last_updated_event_id` 关联事件，不允许无事件来源的投影更新。
- `idempotency_keys` 以 `(session_id, idempotency_key)` 为主键，保存请求 hash 和响应事件 id 列表。

## 建库与初始化

建议创建项目专用库和用户，不修改 PostgreSQL 全局认证策略：

```sql
CREATE DATABASE agent_runtime;
CREATE USER agent_app WITH PASSWORD 'replace-with-strong-password';
GRANT CONNECT ON DATABASE agent_runtime TO agent_app;
```

进入目标库后授权 schema：

```sql
GRANT USAGE, CREATE ON SCHEMA public TO agent_app;
```

部署环境设置连接串：

```powershell
$env:AGENT_DATABASE_URL = "postgresql://agent_app:replace-with-strong-password@localhost:5432/agent_runtime"
```

本地开发也可以写入项目根目录 `.env`。`.env` 已被 `.gitignore` 忽略，不应提交：

```text
AGENT_DATABASE_URL=postgresql://agent_app:***@localhost:5432/agent_runtime
AGENT_TEST_DATABASE_URL=postgresql://agent_app:***@localhost:5432/agent_runtime_test
AGENT_RUNTIME=postgres
```

应用读取数据库连接串时会在目标环境变量缺失时加载 `.env`，但不会覆盖 shell 中已经显式设置的变量。

启用 PostgreSQL runtime：

```powershell
$env:AGENT_RUNTIME = "postgres"
```

开发或首次部署时可以让应用启动时自动应用当前 schema：

```powershell
$env:AGENT_POSTGRES_APPLY_SCHEMA = "true"
```

生产环境更推荐显式 migration 流程，避免应用启动时静默修改 schema。

初始化 schema：

```python
from app.runtime.database import apply_schema, connect_postgres

connection = connect_postgres()
apply_schema(connection)
connection.close()
```

生产环境需要安装 `psycopg`，建议使用 `psycopg[binary]` 或平台标准 wheel。当前项目默认测试不强依赖该包。

## 事务模型

一次事件批次提交的事务边界：

```text
begin
  SELECT app_sessions FOR UPDATE
  compare expected_current_sequence when provided
  SELECT/INSERT idempotency_keys FOR UPDATE
  INSERT world_events with sequence = current_sequence + offset
  UPSERT memory_snapshots / character_impressions / character_fact_awareness
  INSERT memory_operations when snapshot lifecycle changes
  UPDATE app_sessions current_sequence/current_version/narrative_phase
  UPDATE idempotency_keys response_event_ids
commit
```

关键原则：

- sequence 只能由数据库事务内的 `app_sessions.current_sequence` 推进，客户端和 LLM 都不能指定。
- 生产动作提交应传入 `expected_current_sequence`；如果事件流已被其他请求推进，提交会失败，不能把基于旧 session 状态生成的事件接到新事件之后。
- `PostgresActionRuntime` 在调用 `ActionService` 前会先按 `Idempotency-Key + PlayerAction request hash` 查询已提交响应；命中时直接 replay 原响应事件，不再次运行 Agent/LLM。
- 事件写入事务中也会再次检查幂等键，防止并发请求绕过入口预检查。
- 幂等键相同但 request hash 不同，抛出冲突错误，不能复用旧 key 推动新剧情。
- projection 表只服务热读；权威恢复路径仍是 `world_events` replay。
- LLM 调用不应放在持锁事务中。正确路径是先生成受控意图，再进入短事务写事件和投影。

## 当前接口

`PostgresEventStore.append(session, events, idempotency_key=None, request_hash=None, expected_current_sequence=None)`：

- 校验事件的 `case_id` / `session_id` 与 session 一致。
- 锁定 session 行。
- 分配 session 内 sequence。
- 写入 `world_events`。
- 根据事件类型同步投影表。
- 返回 `StoredWorldEvent`，其中包含领域事件和数据库 sequence。
- 当 `expected_current_sequence` 与当前数据库 sequence 不一致时抛出 `StaleSessionSequenceError`。

`PostgresEventStore.load(session_id)`：

- 按 sequence 顺序读取事件并反序列化为 `WorldEvent`。
- 读路径也显式提交事务，避免 psycopg 在非 autocommit 模式下留下隐式事务。

`PostgresSessionStore.create(package)`：

- 创建 `app_sessions` 行。
- 写入 `session.created` 事件。
- 返回内存中的 `SessionState`。

`PostgresSessionStore.get(session_id, package)`：

- 读取事件流并调用现有 replay 逻辑恢复 `SessionState`。

`PostgresActionRuntime.handle(case, session_id, action, idempotency_key=None)`：

- 用结构化 `PlayerAction` 计算 request hash。
- 命中已提交幂等响应时，直接从 `response_event_ids` 和完整事件流重建 `ActionResponse`。
- 从 `world_events` 读取最新事件流。
- replay 出最新 `SessionState`。
- 调用现有 `ActionService.handle(...)` 产生本轮 `new_events`。
- 用 `expected_current_sequence` 将 `new_events` 追加回数据库事件流。

`PostgresRuntimeBackend`：

- `create_session(case)` 通过 `PostgresSessionStore` 创建 `app_sessions` 和 `session.created`。
- `get_session(session_id)` 先读取 session 对应 case，再按事件流 replay。
- `handle_action(session_id, action, idempotency_key)` 路由到 `PostgresActionRuntime`。
- `get_events(session_id)` 返回数据库事件流，而不是内存 session 对象。

FastAPI 路由不再直接依赖 `runtime.session_store.get(session_id)`，而是通过 `RuntimeContainer.create_session/get_session/handle_action/get_events` 访问运行时 backend。

## 验收标准

第一阶段验收：

- 应用重启后，`app_sessions` 和 `world_events` 仍可恢复 session。
- 同一 session 内事件 sequence 连续且不重复。
- 重复提交相同 idempotency key 和相同 request hash，不产生第二批事件。
- 相同 idempotency key 携带不同 request hash 必须报错。
- API `Idempotency-Key` 请求头必须传入 runtime backend。
- `agent_memory_snapshot.updated` 能 upsert `memory_snapshots` 并记录 `memory_operations`。
- `character_impression.updated` 和 `character_fact_awareness.updated` 只能由对应事件驱动投影。
- 默认内存 store 测试和启动路径不需要 PostgreSQL 密码。
- `PostgresActionRuntime` 能把现有内存 ActionService 包成数据库事件流写入边界。

当前真实 PostgreSQL 集成测试覆盖：

- `POST /sessions` + `POST /actions` 写入真实 `agent_runtime_test`。
- runtime 重建后从数据库事件流恢复 session state。
- 重复 `Idempotency-Key` replay 原响应，不重复写事件。
- 相同 `Idempotency-Key` 携带不同 action 返回冲突。
- 并发式 stale sequence append 被拒绝。
- `app_sessions`、`world_events`、`memory_snapshots`、`memory_operations` 投影与事件一致。
- `.env` loader 不覆盖显式环境变量。

本地运行：

```powershell
py -3.12 -m pytest tests\test_postgres_integration.py -vv
```

普通 pytest 通过 `tests/conftest.py` 默认固定 `AGENT_RUNTIME=memory`，避免本地 `.env` 中的 Postgres 配置污染原有内存版单元测试。PostgreSQL 集成测试显式使用 `AGENT_TEST_DATABASE_URL`。

## 未完成风险

- `AGENT_RUNTIME=postgres` 已可将 FastAPI 接到 `PostgresActionRuntime`；未设置时仍默认内存 runtime。
- 已在本地 `agent_runtime_test` 专用库上跑通真实 PostgreSQL 集成测试。后续还需要在 CI 中提供隔离 PostgreSQL 服务，并把该 marker 纳入生产前验证。
- `runtime_traces` 已有落库接口，但现有 `RuntimeTracer` 仍默认写 JSONL；后续需要增加 PostgreSQL trace writer。
- `memory_snapshots` 未来接入语义检索时应在 PostgreSQL 内扩展 `pgvector`，不要引入独立向量库造成双写一致性问题。
