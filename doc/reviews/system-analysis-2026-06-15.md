# System Analysis - 2026-06-15

## 结论

当前系统已经不是“LLM NPC 聊天 demo”，而是具备生产雏形的事件驱动叙事运行时：

- 世界状态通过 `WorldEvent` 推进，并能通过 replay 还原。
- `ActionService`、规则系统、记忆系统、Narrative Director、Agent Loop 的边界基本成立。
- 记忆系统已经从启发式 MVP 进入 v2 骨架：显式 memory operation、metadata 扩展、检索硬过滤、回归评测矩阵都已经有落点。
- PostgreSQL 落库已经有 schema、事件存储、session wrapper、幂等和顺序控制，但还没有成为默认 API 运行时。
- 真实 LLM 异常已经开始进入结构化 trace/API 响应，不再只是静默 fallback。

一句话判断：方向是对的，架构骨架已经立住；但系统还没有真正进入生产态，下一步不应该继续扩 NPC 自由度，而应该把“落库、可回放、可观测、可评测”打穿。

## 当前系统形态

主链路可以理解为：

```text
Client
  -> PlayerAction
  -> ActionService
  -> Rule/Director/Agent/Derivation/Memory systems
  -> WorldEvent[]
  -> SessionState projection
  -> API response + trace
```

现在比较关键的边界如下：

- LLM 主要负责表达、推理文本和意图建议，不直接拥有世界状态写权限。
- 真实状态变化必须通过规则系统和 `WorldEvent` 进入 session。
- 记忆不是直接散落在 prompt 中，而是从事件和 snapshot 派生。
- Narrative Director 负责剧透、防越权、事实释放策略。
- Postgres 方向是 append-only event store + projection，而不是直接把当前内存对象随手 dump 到数据库。

这是正确方向。这个项目最怕的是“LLM 说什么就改什么”，目前主干已经避开了这个根本错误。

## 好的地方

### 1. 状态权威边界清楚

系统把玩家动作、NPC 意图、规则验证、世界事件和状态投影拆开了。这个边界非常重要，因为悬疑游戏最核心的不是生成自然语言，而是可控地维护事实、线索、关系和剧情阶段。

这让后续做 replay、审计、回归测试、剧情修复都有基础。

### 2. 事件日志方向正确

`WorldEvent` 是当前项目最重要的资产。只要事件定义持续收敛，系统就能做到：

- session 内顺序可解释；
- 剧情可回放；
- bug 可定位到具体事件；
- 派生状态可以重建；
- 后续多端、存档、回滚、评测都有统一来源。

PostgreSQL 落库计划没有走“保存整个大 JSON 状态”的短路方案，而是保留 event store 作为真相来源，这是对的。

### 3. 记忆系统已经有产品化意识

当前记忆系统的关键进步是：

- 显式区分 `create / reinforce / revise / supersede / archive`；
- metadata 开始承载 `world_info_id / claim_id / scene_id / topic_tags / privacy_reason / decay_policy`；
- 检索链路开始从“按显著性兜底”转为“hard filter + keyword/BM25 + embedding/reranker 扩展点”；
- 无相关命中时不再按高 salience fallback 注入记忆；
- 已有 memory retrieval matrix 的回归评测方向。

这解决的是记忆系统的根问题：NPC 不能因为某条记忆“很重要”就无视视角、阶段、场景和玩家问法把它说出来。

### 4. Narrative Director 开始从字符串拦截进化

新增 fact gateway 的方向是必须的。悬疑叙事不能只靠 forbidden terms，因为同一个真相可以被换句话泄露。

正确方向应该是：

```text
world_info
  -> claim graph
  -> safe fragments
  -> forbidden inferences
  -> unlock conditions
  -> Director controls allowed disclosure
```

目前已经有结构化事实网关的骨架，后续要把真实 case 内容迁入这个模型。

### 5. LLM 可观测性开始补上

真实 LLM 链路不能只返回 fallback 文案。网络错误、schema 错误、策略违规、超时、JSON 解析失败必须进入 trace 和 API 响应。

现在系统已经开始把 `llm_error`、`llm_fallback_used` 这样的字段显式化，这对生产排障和模型替换都很关键。

## 主要问题

### 1. Postgres 还没有成为默认运行时

当前 Postgres 相关实现已经具备 schema、event store、session wrapper、幂等键和顺序检查，但默认 API 运行时仍偏内存态。

这意味着：

- 重启后 session 不是天然可恢复；
- 并发请求的最终权威还不完全在数据库；
- 真实线上问题还无法完全依赖 DB 事件流审计；
- Postgres 代码更多是“可用骨架”，不是“生产入口”。

下一步必须把 API runtime builder 做出来，通过环境变量或配置切换：

```text
memory runtime
postgres runtime
```

并让真实接口走 `PostgresActionRuntime`。

### 2. LLM 调用与事务边界还需要生产化

不能在数据库锁里等待 LLM，这是对的；但现在的实际含义是：

```text
load events -> replay -> call LLM/rules -> append events with expected sequence
```

如果并发期间 sequence 变了，append 会失败。这个机制能防脏写，但还缺少生产级处理：

- API 层需要稳定的 idempotency key；
- stale sequence 后需要明确返回冲突或进行 bounded retry；
- retry 时必须重新 replay 最新事件，不能复用旧上下文；
- trace 里要记录这次冲突和重试；
- 长期最好拆出 command/event/outbox 边界。

否则上线后会出现“LLM 已经生成，但提交失败”的用户体验问题。

### 3. trace 仍未完全落库

事件已经规划落 Postgres，但 runtime trace 默认仍偏 JSONL。JSONL 对本地调试有用，但生产态不够：

- 不方便按 session/action/error_type 查询；
- 不方便和 world_events join；
- 不方便做线上质量统计；
- 不方便回放某次 LLM 失败上下文。

下一步要做 trace sink abstraction：

```text
RuntimeTracer
  -> JsonlTraceSink
  -> PostgresTraceSink
```

生产环境默认写 Postgres，本地开发可以继续写 JSONL。

### 4. Fact Gateway 还没有充分进入 Agent 前置上下文

目前结构化 fact gateway 更像后置校验器。后置校验能拦错，但成本高，且会让模型先生成不该说的内容再被拒绝。

更优路径是：

- Director 在 LLM 调用前生成 allowed fragments；
- Agent prompt/context 只能看到允许表达的事实碎片；
- LLM 输出仍要带 `disclosure_claims`；
- Director 后置验证 claims 和自然语言内容。

也就是前置收窄空间，后置兜住越权。

### 5. 真实 case 还没完全迁移到 claim graph

fact gateway 的代码骨架已经有了，但真正决定效果的是 case authoring。`mist_clock_manor` 这类主案例必须把关键真相、误导线索、角色视角和解锁条件整理成 claim graph。

如果 case 仍主要依赖散落文本、forbidden terms 和 prompt 提示，Director 的能力上限会被作者数据拖住。

### 6. 记忆检索还没有真正数据库化

当前检索 pipeline 方向正确，但还不是最终态：

- BM25/keyword 仍偏本地实现；
- embedding/reranker 还主要是扩展点；
- 没有 pgvector 索引；
- 没有 per-session/per-character 的 DB 查询计划；
- decay、archive、privacy reason 还需要更稳定的查询语义。

记忆系统下一阶段不该继续堆 prompt，而要把检索变成可解释、可评测、可替换的 retrieval service。

### 7. 测试环境还有 Windows 临时目录权限噪音

`.gitignore` 已经应该忽略 pytest 临时目录，但本机还可能残留权限受限的 tmp 目录。这个不是领域逻辑问题，但会干扰全量测试和 CI 信心。

后续要么清理残留目录，要么固定 pytest basetemp 到可控目录，并确保 CI 用干净环境执行。

## 记忆系统专项判断

记忆系统现在的方向是对的，但仍处在 v2 早期。

最关键的改进不是“让 NPC 记得更多”，而是“让 NPC 只在正确条件下记起正确来源的内容”。悬疑系统里，错误召回比召回不足更危险，因为它会直接破坏推理闭环。

### 已经站住的点

- operation 语义开始清楚，避免所有变化都叫 update。
- metadata 开始承载叙事约束，而不只是 tags。
- 不相关时禁止 salience fallback，这是关键修复。
- matrix evaluation 可以把“应该召回/不应该召回”固化成回归测试。

### 还缺的点

- memory operation 需要完整迁移策略和历史事件兼容报告。
- retrieval 需要 DB-backed hard filter，不应该把大量 snapshot 拉到内存后再筛。
- keyword/BM25、embedding、reranker 需要统一 scoring trace，便于解释为什么命中。
- decay/archive 不能只做存储字段，要进入检索排序和冷记忆恢复规则。
- 每次 Agent 回复应记录使用了哪些 memory_id、为什么使用、哪些候选被过滤。

推荐下一步把记忆系统拆成三个明确层次：

```text
MemoryStore        负责持久化和索引
MemoryRetriever   负责过滤、召回、排序、解释
MemoryPolicy      负责隐私、阶段、视角、衰减、归档规则
```

## Postgres 落库专项判断

Postgres 是这个项目当前最合适的主数据库。

理由很直接：

- `WorldEvent`、session、projection、trace 都适合关系型事务。
- 需要 session 内严格顺序、幂等、唯一约束和行锁。
- 后续可以用 JSONB 承载事件 payload，同时用 generated/indexed columns 优化常用查询。
- 记忆检索后续可以接 `pg_trgm`、full text search、pgvector，不必一开始引入多个存储系统。

不建议现在引入 MongoDB、Redis 作为主状态库或专门向量库。Redis 可以做缓存，不能做叙事事实权威；专门向量库可以以后再评估，但现在会增加一致性复杂度。

### Postgres 下一步必须补齐

- 建项目专用 database/user，不要直接用 `postgres` 超级用户。
- schema migration 机制，不能只靠手动执行 `schema.sql`。
- API runtime 切换到 Postgres。
- 每个 API action 带 idempotency key。
- 并发写入测试：同 session 双请求、重复请求、stale sequence、失败重放。
- runtime trace 写入 Postgres。
- replay 从 DB event stream 重建 session 的端到端测试。

## 优先级路线

### P0：把生产状态权威落到数据库

目标：真实 API 可以在 Postgres runtime 下跑通。

要做：

- 建 `agent_game` database/user。
- 接入 schema migration。
- API runtime builder 支持 `AGENT_RUNTIME=postgres`。
- action 请求支持 idempotency key。
- Postgres runtime 返回明确的 conflict / in_progress / idempotency_conflict 错误。
- 选一条真实剧情路径，用 DB event stream replay 验证状态一致。

### P1：事件存储生产化

目标：事件流成为唯一可信审计链。

要做：

- 固化 event envelope：event_id、session_id、sequence、type、payload、causation_id、correlation_id、created_at。
- 所有状态副作用必须对应事件。
- trace 与 event 关联。
- 增加 append/replay/property 测试。
- 明确哪些 projection 可以重建，哪些只作为缓存。

### P2：记忆系统 v2 真正落地

目标：记忆召回可解释、可评测、可替换。

要做：

- memory snapshots/operations 全量落库。
- retriever 改为 DB-backed hard filter。
- 引入 PostgreSQL full text search 或 pg_trgm。
- embedding 先接 pgvector，保留 reranker 接口。
- matrix evaluation 进入 CI。
- trace 记录候选、过滤原因、分数、最终注入 memory_id。

### P3：Director 事实网关前置化

目标：不是等 LLM 泄露后再拦，而是在生成前就限制可说事实。

要做：

- 将 `world_info.claim_graph` 迁入真实 case。
- AgentContext 增加 allowed/blocked fact fragments。
- LLM 输出必须声明 `disclosure_claims`。
- Director 校验 claims 与自然语言表述一致。
- 建立“同义改写泄露”的红队评测。

### P4：真实 LLM 链路生产观测

目标：任何 fallback 都能定位根因。

要做：

- trace sink 写 Postgres。
- API 响应区分 timeout/network/schema/policy/private_leak。
- 模型请求和响应做脱敏归档。
- schema 错误进入评测样本池。
- 统计每个角色、场景、模型的 fallback 率。

## 不建议做的事

- 不要现在继续扩大 NPC 自由发挥范围。
- 不要用 prompt 替代规则、事实网关和记忆策略。
- 不要为了“快点有智能感”绕过 `WorldEvent`。
- 不要引入第二个主数据库或专门向量库来掩盖当前落库未完成的问题。
- 不要把 memory 全量注入 prompt。
- 不要把 forbidden terms 当成长期剧透防护主方案。

## 后续执行建议

下一轮最值得做的是：把 API 默认运行时接到 Postgres，并让一条真实 session 从创建、行动、Agent 回复、事件写入、trace 写入、replay 校验完整跑通。

验收标准应该很硬：

- 关闭进程后，session 能从 Postgres 恢复。
- 重复提交同一个 idempotency key 不产生重复事件。
- 同 session 并发写入不会乱序。
- replay 后的状态与 action 后状态一致。
- LLM fallback 会写入 trace，并能按 session 查询。
- 记忆召回 trace 能解释每条 injected memory 的来源和过滤过程。

做到这里，这个系统才真正从“架构正确的 MVP”进入“可生产验证的运行时”。
