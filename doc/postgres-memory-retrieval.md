# PostgreSQL Memory Retrieval

## 目标

`PostgresMemoryStore` 只负责从 `memory_snapshots` 投影表做第一阶段候选召回。它可以为了性能和召回率下推粗粒度 SQL 条件，但不能成为权限边界，也不能替代 `MemoryRetriever` 的硬过滤。

最终边界仍在 `MemoryRetriever`：

- `visible_to_target`
- `scope_allowed`
- `layer_allowed`
- `phase_allowed`
- `has_source_event_ids`
- `plan_allowed`
- `forbidden_text_absent`
- `subject_is_player`

DB 层返回过多候选是允许的，返回越权候选后必须被 retriever 拒绝；DB 层返回过少候选才是召回质量风险。

## 当前 SQL 召回形态

当 `MemoryStoreQuery.query_anchors/query_tokens` 非空时，`PostgresMemoryStore` 会把它们规范化为最多 24 个 query term，并在原有 ILIKE / JSON / source id 预筛基础上增加 PostgreSQL FTS 预筛：

- `memory_id ILIKE term`
- `content ILIKE term`
- `source_event_ids/source_memory_ids ILIKE term`
- `metadata::text ILIKE term`
- `metadata ? term`
- `metadata.topic_tags / adjacent_clue_ids / reveals_world_info ? term`
- `to_tsvector('simple', concat_ws(...)) @@ plainto_tsquery('simple', term)`

FTS 文档只拼接 `memory_id`、`content`、source ids 和 `metadata::text`。它不读取 `world_events` 或 `runtime_traces`，也不产生状态变化。

## pg_trgm

`pg_trgm` 召回通过 `PostgresMemoryStore(enable_trigram_prefilter=True)` 显式开启。默认不开启，避免生产库未安装扩展时查询失败。

开启后 SQL 会增加：

- `word_similarity(term, content) >= threshold`
- `word_similarity(term, memory_id) >= threshold`
- `word_similarity(term, metadata::text) >= threshold`
- `word_similarity(term, source_event_ids/source_memory_ids item) >= threshold`

生产启用前应显式安装并验证：

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

可选索引方向：

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_memory_snapshots_content_trgm
    ON memory_snapshots USING gin (content gin_trgm_ops);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_memory_snapshots_memory_id_trgm
    ON memory_snapshots USING gin (memory_id gin_trgm_ops);
```

`metadata::text` trigram 索引写放大较高，只有在真实慢查询证明必要时再加。

## FTS 索引建议

当前实现先落 SQL shape，不强制迁移 schema。生产库如果需要放大 session 规模，应补表达式 GIN 索引，并用真实查询计划验证：

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_memory_snapshots_recall_fts
    ON memory_snapshots USING gin (
        to_tsvector(
            'simple',
            concat_ws(
                ' ',
                memory_id,
                content,
                array_to_string(COALESCE(source_event_ids, ARRAY[]::text[]), ' '),
                array_to_string(COALESCE(source_memory_ids, ARRAY[]::text[]), ' '),
                metadata::text
            )
        )
    );
```

## pgvector 后续扩展点

当前 fake connection 只能安全验证 SQL shape，不适合在本轮引入 pgvector 存储、embedding 生成、迁移和向量距离排序。后续如果接 pgvector，应保持同一边界：

- 向量只参与候选召回或软排序。
- 向量召回结果必须回到 `MemoryRetriever` 走同一套 hard filters。
- embedding 内容不能来自 `runtime_traces` 或未选中事件 payload。
- embedding 版本、模型、生成来源和重建策略必须可审计。
