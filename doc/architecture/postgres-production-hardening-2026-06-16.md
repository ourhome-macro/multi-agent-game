# PostgreSQL Production Hardening - 2026-06-16

## 本次结论

PostgreSQL runtime 已经不是待实现项。本次把它从“可切换 runtime”推进到“生产启动必须校验 schema”的状态，并补上最小 migration checksum 机制。

## 启动语义

`AGENT_RUNTIME=postgres` 时，启动路径现在必须满足其一：

```text
AGENT_POSTGRES_APPLY_SCHEMA=1
  -> apply_postgres_schema(...)
  -> 写入 migration checksum

默认
  -> ensure_postgres_schema(...)
  -> 校验 migration version、checksum、核心表

AGENT_POSTGRES_SKIP_SCHEMA_CHECK=1
  -> 仅供测试或特殊运维绕过
```

生产环境不应依赖 `AGENT_POSTGRES_APPLY_SCHEMA=1` 长期自动改库。推荐流程是部署前显式执行：

```powershell
py -3.12 -m app.runtime.schema_admin check
py -3.12 -m app.runtime.schema_admin apply
py -3.12 -m app.runtime.schema_admin check
```

应用启动时只做 `check`。如果 schema 未安装、缺表、版本过低或 checksum drift，启动失败。

## Migration 语义

当前最小 migration id：

```text
001_initial_runtime_schema
```

`schema_migrations` 现在记录：

- `name`
- `version`
- `checksum`
- `description`
- `applied_at`

`schema_checksum(...)` 对当前 `app/storage/schema.sql` 做 SHA-256。`apply_postgres_schema(...)` 会执行 schema SQL，然后 upsert `001_initial_runtime_schema` 的 checksum，并删除旧的 `postgres_runtime_schema` 标识。

这仍不是完整多文件迁移系统，但已经能阻断最危险的 drift：代码里的 schema.sql 改了，生产库仍停在旧结构。

## 下一步 migration 演进

当出现第二次真实表结构变更时，不应继续扩大单文件语义，而应拆成：

```text
app/storage/migrations/
  001_initial_runtime_schema.sql
  002_add_npc_skill_events.sql
  003_add_memory_search_indexes.sql
```

每个 migration 必须独立记录 checksum。生产只允许 forward migration，不在应用启动时自动执行破坏性变更。

## 当前仍需注意

- `AGENT_POSTGRES_SKIP_SCHEMA_CHECK=1` 只能用于测试 fake connection 或明确受控的运维场景。
- projection rebuild 仍依赖 `world_events` 权威重放，新增投影表必须同步纳入 rebuild。
- schema checksum 校验只保证 SQL 文件与 migration 记录一致，不替代真实数据库权限、备份、恢复和监控。
- Postgres marker 测试仍需要 CI 提供独立测试库。
