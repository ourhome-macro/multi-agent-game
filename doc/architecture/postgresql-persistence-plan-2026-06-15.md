# PostgreSQL 持久化落地计划

日期：2026-06-15

## 本机确认结果

当前机器已经安装并运行 PostgreSQL：

- 服务名：`postgresql-x64-16`
- 版本：`psql 16.13`
- 服务状态：`Running`
- 启动目录：`D:\postgresql`
- 数据目录：`D:\postgresql\data`
- 客户端路径：`D:\postgresql\bin\psql.exe`

`psql` 没有进入 PATH，因此直接执行 `psql` 找不到命令。使用完整路径可以调用客户端。

当前无密码直连失败：

```text
fe_sendauth: no password supplied
```

这说明服务可用，但本地 `postgres` 用户需要密码或需要配置专用应用用户。不要修改 PostgreSQL 全局认证策略来绕过密码，应创建项目专用库和专用用户。

## 结论

项目后续生产化应使用 PostgreSQL 作为唯一权威持久化层。

SQLite 只适合本地 demo 或极早期单机场景；Redis 只能做缓存、限流、短期锁或异步队列辅助；独立向量库、MongoDB、Neo4j 都不应该成为第一阶段主库。

根因是本项目的核心不是普通聊天记录，而是可回放、可审计、可并发校验的叙事世界状态：

- `WorldEvent` 必须追加写入且顺序稳定。
- `SessionState` 必须能从事件流恢复。
- 记忆快照、角色画像、玩家已知、事实认知必须有来源事件。
- 玩家动作、规则派生、Director 审计、Agent trace 必须在事务边界内保持一致。
- 后续多人或并发请求不能靠内存字典维持正确性。

PostgreSQL 的事务、行锁、唯一约束、JSONB、GIN 索引和后续 `pgvector` 扩展正好匹配这些要求。

## 当前代码缺口

当前运行时仍使用内存存储：

- `app/storage/memory.py`
  - `InMemoryCaseStore`
  - `InMemorySessionStore`
- `app/runtime/persistence.py`
  - `JsonlEventStore`
- `app/runtime/events.py`
  - `EventRecorder.append(...)` 只向 `session.events` 追加事件

这意味着当前系统即使事件模型设计正确，也还没有生产持久化能力：

- 进程重启后 session 丢失。
- 事件追加和状态更新没有数据库事务。
- 缺少 session 级并发锁。
- 缺少幂等键。
- 记忆快照只存在内存对象中。
- replay 可测，但还不是线上恢复路径。

## 第一阶段数据库边界

第一阶段不要把所有领域对象都拆成过细表。应以事件日志为权威，关键查询状态建投影表。

推荐最小表：

```text
app_sessions
world_events
memory_snapshots
memory_operations
character_impressions
character_fact_awareness
runtime_traces
idempotency_keys
```

### app_sessions

保存 session 元信息和并发版本。

关键字段：

- `id`
- `case_id`
- `current_sequence`
- `current_version`
- `narrative_phase`
- `created_at`
- `updated_at`

每次处理玩家动作时先锁定 session 行，再追加事件和更新投影。

### world_events

追加式事件日志，是最高权威。

关键字段：

- `id`
- `session_id`
- `case_id`
- `sequence`
- `actor_id`
- `type`
- `payload jsonb`
- `caused_by_event_id`
- `created_at`
- `schema_version`

约束：

- `unique(session_id, sequence)`
- `unique(session_id, id)` 或 `id` 全局主键
- 可选 `unique(session_id, idempotency_key)`

`sequence` 必须由数据库事务内分配，不能由客户端或 LLM 决定。

### memory_snapshots

保存当前稳定记忆投影，仍然以 `agent_memory_snapshot.updated` 事件为来源。

关键字段：

- `session_id`
- `memory_id`
- `rule_id`
- `memory_type`
- `memory_scope`
- `memory_layer`
- `subject_id`
- `owner_character_id`
- `visible_to_character_ids text[]`
- `content`
- `source_event_ids text[]`
- `source_memory_ids text[]`
- `salience`
- `confidence`
- `visibility`
- `metadata jsonb`
- `last_updated_event_id`
- `created_at`
- `updated_at`

第一阶段检索仍可以走结构化字段和文本匹配。后续需要语义检索时，在同表增加 embedding 列并使用 `pgvector`，不要一开始引入独立向量库造成双写一致性问题。

### memory_operations

记录记忆生命周期操作，不替代事件日志。

关键字段：

- `id`
- `session_id`
- `memory_id`
- `operation`
- `source_event_id`
- `payload jsonb`
- `created_at`

典型操作：

- `created`
- `merged`
- `reinforced`
- `archived`
- `redacted`

这张表用于审计“某条记忆为什么变成现在这样”，解决 `memory_snapshots` 只看当前值不看演化过程的问题。

### character_impressions

保存 NPC 对玩家的私有画像投影。

关键字段：

- `session_id`
- `observer_id`
- `target_id`
- `trust`
- `suspicion`
- `fear`
- `current_strategy`
- `source_memory_ids text[]`
- `source_event_ids text[]`
- `payload jsonb`
- `last_updated_event_id`

它必须继续由事件驱动更新，不能允许 Agent 或 LLM 直接写库。

### character_fact_awareness

保存角色事实认知账本。

关键字段：

- `session_id`
- `awareness_id`
- `character_id`
- `world_info_id`
- `stance`
- `confidence`
- `source_type`
- `source_refs text[]`
- `evidence_clue_ids text[]`
- `source_event_ids text[]`
- `last_updated_event_id`

这张表对记忆系统很关键，因为它承担“NPC 视角下知道、怀疑、隐瞒、误信什么”的结构化边界。

### runtime_traces

保存 Agent/Director 调用轨迹和记忆投影摘要。

关键字段：

- `id`
- `session_id`
- `action_event_id`
- `target_character_id`
- `backend`
- `memory_projection jsonb`
- `director_decision jsonb`
- `llm_error_type`
- `created_at`

禁止把完整私密 prompt 或敏感 memory content 无边界塞进 trace。trace 应默认记录结构化摘要，需要调试明文时再受控开启。

### idempotency_keys

保存外部动作幂等请求。

关键字段：

- `session_id`
- `idempotency_key`
- `request_hash`
- `response_event_ids`
- `created_at`

同一个动作重复提交时必须返回同一批事件结果，而不是重新推进剧情。

## 事务模型

处理一次玩家动作时，数据库事务边界应覆盖：

```text
begin
  lock app_sessions row
  load current projected state or replay needed slice
  validate PlayerAction
  append player/rule/director/agent events with sequence
  apply derived events
  upsert memory_snapshots / character_impressions / fact_awareness
  update app_sessions current_sequence/current_version/narrative_phase
  save runtime_trace summary
commit
```

核心原则：

- 事件追加和投影更新必须同事务提交。
- 同一 session 同时只能处理一个写动作。
- LLM 调用不应在持锁事务里长时间等待。更好的做法是先生成受控意图，再进入短事务提交；如果提交前状态版本变化，必须重新校验。
- replay 仍是权威恢复能力，但线上热路径应读投影表，避免每次动作全量 replay。

## 记忆系统落库优先级

第一优先级不是向量检索，而是可审计和可回放：

1. `world_events` 先落地，保证事件不丢。
2. `memory_snapshots` 跟随 `agent_memory_snapshot.updated` 事件 upsert。
3. `memory_operations` 记录 merge/archive/reinforce 的原因。
4. `character_fact_awareness` 和 `character_impressions` 落投影表。
5. `runtime_traces` 记录每次 Agent turn 使用了哪些 memory id。
6. 最后再加 `pgvector` 做语义召回。

不要先做独立 RAG 服务。当前记忆问题的根因不是“相似度不够强”，而是来源、边界、生命周期和事务权威还没落库。

## 下一步建议

推荐按这个顺序推进：

1. 创建项目专用数据库和用户，例如 `agent_runtime`。
2. 增加 PostgreSQL 连接配置，不把密码提交到仓库。
3. 引入 `psycopg` 或 SQLAlchemy 2.x。
4. 写第一版 SQL migration，先覆盖 `app_sessions`、`world_events`、`memory_snapshots`。
5. 新增 `PostgresSessionStore` 和 `PostgresEventStore`，保留内存 store 给测试。
6. 给 `ActionService` 加 session 锁、幂等键和事务提交边界。
7. 增加 replay 对照测试：同一批 `world_events` 从数据库读出后必须恢复等价 `SessionState`。

第一版验收标准：

- 重启进程后 session 和事件仍存在。
- 同一 action 重复提交不会重复生成剧情事件。
- 两个并发 action 不能交错破坏 sequence。
- memory snapshot 能从数据库恢复并参与 AgentContext。
- replay 结果和热投影结果一致。
