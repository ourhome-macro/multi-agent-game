# Project Status and Roadmap - 2026-06-16

## 结论

当前项目已经不是 LLM NPC 对话 demo，而是一个以 `WorldEvent` 为权威、以 Rule Engine 和 Narrative Director 控制状态与叙事边界的后端运行时。主干方向正确，且 P0 硬链路已经基本成型：玩家输入被结构化为 `PlayerAction`，真实状态变化通过规则系统写入事件，Agent 只产出 `AgentIntent`，Director 在生成前后约束事实披露，replay 能恢复关键状态。

但是项目还没有达到生产态。核心问题不是“能力不够智能”，而是生产入口、数据库迁移、真实 LLM 质量门、案例资产结构化和 Agent Skill 状态化还没有完全打穿。后续不应优先扩 NPC 自由度，而应继续压实可回放、可观测、可测试、可审计的硬链路。

## 当前落地情况

### 1. 运行时权威链路已经站住

现有链路是：

```text
Raw Text / API Action
  -> ActionRouter / PlayerAction
  -> RuleEngine precheck / apply
  -> AgentContext / AgentLoop
  -> AgentGateway
  -> LLM contract validation
  -> NarrativeDirector
  -> RuleEngine proposed action apply
  -> DerivedEventSystem / MemorySnapshotSystem / RuleTriggerSystem
  -> WorldEvent
  -> replay_events
```

这个结构是正确的。LLM 没有直接写世界事实、关系、线索、剧情阶段或记忆快照的权限。`inspect`、`talk`、`ask_about`、`present_clue`、`accuse` 的边界清楚，`accuse` 不走 Agent，避免让模型判断正式推理结果。

### 2. PostgreSQL event stream 已经从方案进入实现

代码中已经存在 `AGENT_RUNTIME=postgres` 切换路径，`PostgresActionRuntime` 会从数据库事件流 replay 最新状态，调用同一套 `ActionService`，再用 `expected_current_sequence` 追加本轮新事件。schema 已覆盖：

- `app_sessions`
- `world_events`
- `memory_snapshots`
- `memory_operations`
- `character_impressions`
- `character_fact_awareness`
- `runtime_traces`
- `idempotency_keys`

幂等键、stale sequence 检查、投影表、runtime trace 同事务 flush 都已经有代码和测试覆盖。相较 2026-06-15 的分析，Postgres 不再只是设计骨架，已经是可切换 runtime。

### 3. Director 已经开始前置事实网关

`NarrativeDirector.safe_fragment_constraints(...)` 已进入 agent-backed 生成链路。`AgentLoop` 会把当前 NPC 可谈、已解锁的 `WorldInfo.claim_graph.safe_fragments` 投影到 `AgentContext.director_safe_fragments`，再进入 LLM 合同。

这比单纯后置 forbidden term 拦截更接近正确形态。当前模型最多看到 safe summary、fragment ref、allowed modes 和 source refs，不会看到 locked fragment、forbidden inference、solution claim 或全局真相原文。

### 4. Agent 输入与真实 LLM 合同边界较硬

真实 LLM 后端默认禁用，只有 `LLM_BACKEND=real` 且有 API key 时启用。启用后仍走严格 JSON schema、`validate_llm_agent_output(...)`、Director 审计和 Rule Engine。

真实 LLM 的 provider system prompt 只来自 `app/agents/prompts/system.md`，动态事实通过 `LLMAgentContractInput` 作为 user payload 进入。这避免了把系统级指令、运行时事实和可说边界混成一坨 prompt。

### 5. Memory v2 的方向正确

记忆系统已经有 typed memory、scope/layer、operation、metadata、projection skill、retrieval planner、archival lifecycle 和 matrix evaluation。最近代码还强化了 clue 相关 metadata 和 snake_case token 召回，避免只靠自然语言 content 或 target_id 做粗糙召回。

关键点是：系统开始解决“该 NPC 在当前动作、阶段、视角下应该记起什么”，而不是简单做高 salience 记忆注入。

### 6. 测试面已经覆盖核心边界

测试分布覆盖 runtime、router、Director、fact gateway、memory scope、memory retrieval、typed memory、Postgres persistence、trace sink、scenario harness、LLM shadow eval、deduction evaluator。这个项目的测试方向是正确的，尤其是把 narrative safety 和 memory boundary 当成回归对象，而不是只测 HTTP happy path。

## 主要问题

### 1. 默认运行时仍是 memory，不是生产入口

`app/main.py` 支持 `AGENT_RUNTIME=postgres`，但默认仍是 memory。对开发友好，但生产意义上还缺一个明确的部署标准：

- 生产配置必须强制 Postgres runtime。
- 启动时不应长期依赖 `AGENT_POSTGRES_APPLY_SCHEMA` 自动改库。
- schema check 应成为启动前或 CI/CD gate。
- 缺少一份明确的 production runbook，包括数据库、迁移、环境变量、回滚和健康检查。

根因不是代码没写，而是“可切换实现”还没有升级成“生产默认操作规程”。

### 2. schema migration 仍是弱项

`schema_migrations` 当前只是版本标识，`schema.sql` 是单文件 apply。短期可用，但后续一旦表结构变动，会有 drift 风险：

- 无 SQL hash 校验。
- 无逐版本迁移文件。
- 无 downgrade/forward-only 策略说明。
- rebuild projection 虽然已能按事件重放投影，但仍需要和未来每个投影表变更绑定验收。

这个问题必须尽早解决。事件存储一旦上生产，schema 变更不能靠“重新执行一个大 SQL 文件”。

### 3. 真实案例的 claim graph 迁移不完整

`fake_case_001` 已有 `claim_graph.safe_fragments`，但 `mist_clock_manor/world_info.yaml` 主要仍是 `aliases` 和 `claim_patterns`，没有大规模 `claim_graph.safe_fragments / forbidden_inferences / unlock_conditions`。

这意味着主案例的 Director 能力上限仍受 authoring 数据限制。代码网关已经在了，真正的工作变成把谜题事实拆成：

- 可安全暗示的 fragment。
- 需要证据解锁的 fragment。
- 多 fragment 组合后会泄露的 forbidden inference。
- 每个 NPC 在不同阶段最多能表达到的 mode。

没有这层，真实 LLM 仍会更多依赖后置审计和 mock dialogue。

### 4. NPC Skill 仍是投影能力，不是事件化能力

NPC Skill v0 已能被 loader 读取、selector 选择，并作为安全投影进入 AgentContext 和 trace。但文档也明确写了尚未落地：

- 没有 `npc_skill.selected / rejected` 事件。
- cooldown 没有真实状态和 replay。
- selected skill 还没有硬接入 LLM output contract，不能严格限制 intent、tactic、proposed action。
- skill memory policy 还没有和 retrieval planner 深度合并。
- 缺少 skill matrix 评测。

所以当前 NPC Skill 更像“生成前边界投影”，还不是完整领域行为系统。

### 5. Memory 检索还没有数据库化

当前 `MemoryRetriever` 仍从 `session.memory_snapshots.values()` 取全量快照，然后在内存中 hard filter、BM25、排序。对 MVP 和测试足够，但不是大规模生产方案。

下一步要把 MemoryStore、MemoryRetriever、MemoryPolicy 拆清楚：

- Store 负责 DB 查询和索引。
- Retriever 负责召回、排序和解释。
- Policy 负责视角、隐私、阶段、归档、衰减。

Postgres schema 已有 `memory_snapshots`，但检索路径还没变成 DB-backed hard filter，也没有 pg full text / pg_trgm / pgvector 的落地计划和验收测试。

### 6. 真实 LLM 仍缺质量门和线上评测闭环

真实 LLM adapter 的安全降级、schema repair、错误分类和 trace 已经存在。但生产前还缺：

- 用真实主案例跑固定脚本的 nightly shadow eval。
- fallback rate、schema error rate、Director block rate 的门槛。
- 模型升级时的对比评估。
- 同义改写泄露红队样本池。
- provider 兼容差异的明确支持矩阵。

当前真实 LLM 是“可接入、可观测、可降级”，还不是“可承诺质量”。

### 7. 前端和产品闭环还没成为主战场

代码和文档已经定义了 evidence assets、StateSummary、公开角色卡、raw-actions、structured actions 等前端接口。但当前项目重心仍是后端运行时和案例链路，没有看到完整 2D 客户端、线索板、关系图、任务日志和多人场景互动 UI。

这不是当前最大技术债，但会影响下一阶段产品验证。没有 UI 工作流，很多 API 契约无法被真实玩家行为压力测试。

## 后续规划

### P0：把生产入口钉死在 Postgres runtime

目标：一条真实 session 在 Postgres 下完成创建、行动、Agent 回复、事件追加、trace 落库、进程重启恢复和 replay 校验。

验收标准：

- 生产启动必须使用 `AGENT_RUNTIME=postgres`。
- 启动前执行 schema check，失败直接阻断部署。
- `Idempotency-Key` 是 action/raw-action 的强制生产约束。
- stale sequence 返回明确 409，不写事件，不写 trace。
- 进程重启后 session 只靠 DB event stream 恢复。
- Postgres integration tests 进入 CI，而不是只本地手跑。

### P1：建立真实迁移体系

目标：数据库 schema 变更可审计、可回放、可阻断 drift。

要做：

- 从单文件 schema 演进到 versioned migrations。
- `schema_migrations` 记录 migration id、checksum、applied_at。
- 加 schema drift check。
- 每次新增投影表必须同步 projection rebuild 测试。
- 写 production database runbook。

### P2：迁移 `mist_clock_manor` 到 claim graph

目标：主案例不再主要依赖 aliases、claim_patterns 和 mock dialogue，而是有结构化事实释放图。

要做：

- 为高敏 `WorldInfo` 补 `safe_fragments`。
- 为组合泄露补 `forbidden_inferences`。
- 为 fragment 写 unlock conditions。
- 把角色 private world info、FactDisclosureStrategy、NPC skill safe refs 对齐。
- 建同义改写泄露评测，覆盖“台词没用禁词但表达了真相”的情况。

### P3：把 NPC Skill 变成事件化行为系统

目标：Skill 不只是投影，而是可回放、可冷却、可审计的运行时能力。

要做：

- 新增 `npc_skill.selected`、`npc_skill.rejected`、`npc_skill.cooldown.updated` 事件。
- selected skill 写入 trace 和 WorldEvent，replay 可恢复 cooldown。
- skill 限制进入 `LLMAgentOutputContract`，硬限制 intent、tactic、proposed_actions。
- skill memory policy 与 retrieval plan 合并。
- 建 skill matrix 测试。

### P4：Memory DB-backed retrieval

目标：记忆召回不再依赖全量内存快照扫描。

要做：

- 定义 `MemoryStore` 接口。
- Postgres 查询先执行 session、character visibility、scope、layer、phase、metadata hard filter。
- 引入 pg full text 或 pg_trgm 作为第一阶段文本召回。
- embedding/pgvector 保留为 P4 后段，不要先引入外部向量库。
- trace 记录候选数、过滤原因、分数和最终注入 memory id，但不记录 content。

### P5：真实 LLM 质量门

目标：真实 LLM 从“可调用”进入“可上线灰度”。

要做：

- 主案例 nightly shadow eval。
- schema repair/fallback 样本池。
- Director block/fallback/error rate 阈值。
- 多模型对比报告。
- 红队样本覆盖 prompt injection、同义剧透、角色越权、伪造证据、非法 proposed action。

### P6：前端工作流验证

目标：用真实玩家操作压力测试后端契约。

要做：

- 2D 场景、热点、结构化动作提交。
- 线索板使用 `StateSummary.evidence_assets`，但不把前端状态作为权威。
- 人物关系图只展示公开关系，不展示 private portrait。
- raw text 入口保留，但核心推理动作优先走结构化 UI。
- 任务日志和事件回放对齐 `WorldEvent`。

## 不建议做

- 不要继续扩大 LLM 对世界状态的控制面。
- 不要把 `mist_clock_manor` 的真相释放继续堆到 prompt 或 mock dialogue。
- 不要为了向量检索提前引入第二套主存储。
- 不要让 Skill 在没有事件和 cooldown 的情况下承担剧情分支权威。
- 不要把 runtime trace 当成状态来源。
- 不要在 schema migration 没成型前频繁调整生产表结构。

## 下一步最优解

最优下一步不是加新 NPC 能力，而是做一个“Postgres 生产验收切片”：

```text
schema check
  -> create session
  -> structured inspect
  -> ask_about / present_clue
  -> Agent turn
  -> Director safe fragment gate
  -> event append
  -> runtime trace flush
  -> process restart
  -> DB replay
  -> state equality assertion
```

这条链路打穿后，再迁移 `mist_clock_manor` 的 claim graph。否则继续扩 Agent 行为只会把复杂度堆在尚未完全产品化的运行时之上。
