# Roadmap Clarification - 2026-06-16

## 1. Postgres runtime 已经做了，问题在哪里

Postgres runtime 的代码实现已经做了，而且不是空壳。

已经落地的事实：

- `app/main.py` 支持 `AGENT_RUNTIME=postgres`。
- `PostgresActionRuntime` 会从 `world_events` replay 最新 `SessionState`。
- action 生成后通过 `expected_current_sequence` 追加事件，能防 stale write。
- `Idempotency-Key` 有 request hash 和 replay 原响应逻辑。
- runtime trace 在 Postgres runtime 下先进入 buffer，再随本轮事件同事务 flush。
- schema 已有 `world_events`、`memory_snapshots`、`runtime_traces`、`idempotency_keys` 等表。

剩余问题不是“没做”，而是“还没有被钉成生产入口”：

- 默认仍是 `AGENT_RUNTIME=memory`。这对测试友好，但生产必须明确强制 Postgres。
- schema check 还不是启动硬门槛。现在可以手动 `schema_admin check`，但生产部署流程还没强制它。
- schema apply 仍是可选启动行为 `AGENT_POSTGRES_APPLY_SCHEMA`，长期不应让应用启动时自动改生产库。
- CI 是否稳定跑 Postgres marker 还需要确认和固化。
- 生产 runbook 不完整：数据库用户、权限、迁移、备份、恢复、回滚、健康检查还没有形成硬文档。

所以准确表述应改为：Postgres runtime 已实现，下一步是生产化验收和运维固化，不是从零实现。

## 2. schema migration 是什么

这里的 migration 不是剧情、记忆或案例迁移，而是数据库表结构迁移。

当前是单文件：

```text
app/storage/schema.sql
schema_migrations(name, version)
CURRENT_SCHEMA_VERSION = 1
```

问题是单文件 apply 只能说明“现在应该长这样”，不能可靠表达“从 v1 到 v2 怎么安全变过去”。

生产上需要 versioned migrations，例如：

```text
migrations/
  001_initial_runtime_schema.sql
  002_add_memory_search_columns.sql
  003_add_npc_skill_events.sql
```

每条 migration 应记录：

- migration id
- checksum
- applied_at
- 执行顺序

它解决的问题：

- 防止生产库和代码里的 schema.sql 悄悄 drift。
- 支持多人开发时安全新增列、索引、表。
- 知道某个环境到底应用到了哪一步。
- 失败时能定位是哪条 SQL 出问题。
- projection rebuild、索引构建、数据回填可以绑定到具体版本。

当前 `schema_migrations` 只是“版本标识”，不是完整 migration 系统。

## 4. NPC Skill 事件化为什么可以做

现在 NPC Skill 已经能被选择并投影到 AgentContext，但还不是完整运行时状态。

值得做的原因：

- Skill selection 是叙事行为决策，应可 replay。
- cooldown 如果不事件化，重启后无法可靠恢复。
- skill rejected 的原因很重要，能解释为什么 NPC 没有使用某个能力。
- 真实 LLM 需要硬约束：选中的 skill 应该限制 intent、tactic、proposed_actions，而不是只作为提示。

最小落地范围：

```text
npc_skill.selected
npc_skill.rejected
npc_skill.cooldown.updated
```

事件 payload 不写 skill 正文、private 原文或 safe summary，只写：

- skill_id
- target_id
- action_event_id
- selected/rejected reason
- safe_fragment_refs
- allowed_intents
- allowed_tactics
- allowed_proposed_actions
- cooldown_until_turn 或 cooldown_remaining

这一步是合理的 P3，不应早于 Postgres 生产验收和主案例 claim graph 迁移，但方向对。

## 5. Memory DB-backed retrieval 为什么是重点

当前 MemoryRetriever 的核心路径仍是：

```python
snapshots = list(session.memory_snapshots.values())
working_candidates = _filter_snapshots(snapshots, working_filters)
LocalBM25KeywordScorer(...)
```

也就是先把 session 的 memory snapshots replay 到内存，再在 Python 里做 scope、visibility、layer、phase、metadata、keyword/BM25 排序。

这对 MVP 正确，但长期会出三个硬问题。

### 问题一：性能会随记忆量线性恶化

悬疑游戏里每个 session 会积累：

- 线索发现记忆
- 私有 NPC 互动记忆
- scene_shared 记忆
- director_audit 记忆
- 画像和关系派生记忆
- archival 冷记忆

如果每次 Agent turn 都把全量 snapshot 拉到内存再筛，数据量上来后成本不可控。

### 问题二：审计解释不够细

现在 trace 记录的是最终注入 memory 的安全摘要，但还不能稳定回答：

- DB 第一阶段有多少候选。
- 哪些因 scope 被过滤。
- 哪些因 visible_to 被过滤。
- 哪些因 phase 或 memory_layer 被过滤。
- 哪些因 forbidden content 被过滤。
- 每条候选的结构化分、关键词分、recency 分是多少。

生产排查时，这些信息比“最终用了哪几条 memory_id”更重要。

### 问题三：未来 embedding/reranker 不能直接建立在内存全扫上

embedding 或 reranker 应该吃的是“已经过硬边界过滤的小候选集”，不是全量记忆。否则容易出现两个问题：

- 成本高。
- 召回阶段绕过 privacy/scope/layer，后面再补过滤容易出事故。

正确顺序应是：

```text
Postgres hard filter
  -> text/metadata candidate recall
  -> optional embedding score
  -> optional reranker
  -> policy final check
  -> AgentContext selected memory projection
```

### 推荐方案

先不要引入外部向量库。Postgres 已经是主状态库，应先把 memory 检索压到 Postgres：

```text
MemoryStore
  -> PostgresMemoryStore
  -> query candidates by session/character/scope/layer/phase/metadata

MemoryRetriever
  -> rank returned candidates
  -> explain selected/filtered results

MemoryPolicy
  -> privacy, phase, visibility, archival, forbidden content
```

第一阶段索引建议：

- `(session_id, owner_character_id)`
- `visible_to_character_ids` GIN 已有
- `metadata` GIN 已有
- 增加 scope/layer/type 组合索引
- 增加 content full text 或 pg_trgm

pgvector 可以后置。等 hard filter + full text 能稳定解释召回后，再接 embedding scorer。不要用向量库掩盖基础边界没做实的问题。

### 验收标准

- 同一组 memory retrieval matrix 在 DB-backed 和当前 in-memory retriever 下结果一致。
- 每次检索 trace 能记录候选数、过滤原因、分数摘要和最终 memory_id。
- 普通 NPC 不能召回其他 NPC private、director_audit、未冷召回 archival。
- Director 审计入口可以走专门策略，但不能把 director memory 注入 NPC。
- 对 1k、10k、100k memory snapshots 有基本性能基准。

这就是为什么 5 是重点：它直接决定 Agent 是否能在长线剧情里稳定、可解释、低泄漏地“记起正确的事”。
