# Code Review: 记忆系统与生产演进建议

日期：2026-06-15

## 总体结论

这个项目的方向是对的：它不是把 NPC 对话直接丢给 LLM，而是已经形成了事件日志、规则引擎、Narrative Director、Agent 合约、记忆派生和回放的后端骨架。尤其是记忆系统，已经有“事件产生候选记忆 -> 快照归并 -> 按 scope/layer/可见性检索 -> 注入 AgentContext -> trace 审计”的闭环。

但它还不是生产级系统。当前最大短板不是“缺一个更强模型”，而是运行时仍是内存态、检索是启发式、记忆更新语义偏粗、并发和持久化边界缺失。下一阶段应优先把世界状态、事件日志和记忆快照做成可持久、可重放、可迁移、可观测的生产链路，再谈更复杂的多 Agent 自主行为。

## 做得好的地方

1. 架构边界清晰。`PlayerAction`、`AgentIntent`、`WorldEvent`、`SessionState`、记忆候选和快照都在强类型模型中表达，`app/domain/models.py:147`、`app/domain/models.py:876`、`app/domain/models.py:949`、`app/domain/models.py:973`、`app/domain/models.py:1054`、`app/domain/models.py:1065` 是核心基础。

2. LLM 没有直接改状态。Agent 只输出 `speech`、`intent`、`proposed_actions` 等结构化意图，`validate_llm_agent_output` 会拒绝 LLM 直接提出剧情阶段变更，真实状态变化仍走 `RuleEngine.apply_agent_intent`，见 `app/agents/llm_contract.py:28` 和 `app/rules/engine.py:68`。

3. Narrative Director 已经在 Agent 输出后做越权检查。它检查 forbidden fact、disclosure claim、world_info 直接触达，避免 LLM 绕过叙事阶段直接泄密，见 `app/director/narrative_director.py:84`、`app/director/narrative_director.py:169`。

4. 记忆系统有正确的第一性原则：记忆有来源事件、scope、layer、owner、visible_to、salience、confidence、metadata，而不是一堆无来源长文本。核心字段在 `app/domain/models.py:949` 和 `app/domain/models.py:973`。

5. 记忆隔离意识强。`case/session/npc_private/scene_shared/director_audit` 与 `core/working/archival` 已经形成访问边界；Agent 检索默认排除 `director_audit` 和 `archival`，见 `app/agents/memory.py:15`、`app/agents/retrieval_planner.py:15`、`app/agents/context.py:368`。

6. 回放能力已覆盖记忆状态。`replay_events` 能从 `MEMORY_CANDIDATE_CREATED` 和 `AGENT_MEMORY_SNAPSHOT_UPDATED` 还原候选记忆与快照，见 `app/runtime/replay.py:111`、`app/runtime/replay.py:140`。

7. 测试覆盖比一般原型强很多。当前测试文件约 294 个 `test_`，记忆主链路 65 个测试通过，覆盖 scope、NPC 隔离、归档、检索质量和雾钟庄园边界。

## 记忆系统现状

### 数据流

当前记忆链路是：

1. 玩家动作进入 `ActionService.handle`。
2. 规则引擎先记录玩家事件或拒绝非法动作，见 `app/runtime/service.py:121`、`app/runtime/service.py:145`、`app/runtime/service.py:169`。
3. `DerivedEventSystem` 从玩家事件、线索发现、关系阈值、导演阻断等事件派生记忆候选，见 `app/runtime/derivations.py:39`。
4. `MemorySnapshotSystem` 把候选记忆归并成快照，并写出 `AGENT_MEMORY_SNAPSHOT_UPDATED`，见 `app/runtime/memory_snapshots.py:17`。
5. `MemoryRetriever` 根据 action、case、session 和 retrieval plan 选择可见快照，见 `app/agents/memory.py:65`。
6. `build_agent_context` 注入选中的 `memory_snapshots`、recent events、角色内心上下文和披露约束，见 `app/agents/context.py:34`。
7. LLM 合约投影只保留被选中的 memory event 内容，避免 recent event 绕过检索暴露未选中记忆，见 `app/agents/llm_contract.py:72`。
8. Runtime trace 只记录 memory id/scope/layer/可见性，不记录正文，见 `app/runtime/tracing.py:177`。

### 值得保留的设计

- 记忆候选与记忆快照分层是正确的。候选保留事件级来源，快照承载 Agent 当前可用记忆，便于幂等归并和回放。
- `memory_scope` 和 `memory_layer` 是生产系统必需的权限边界，不应退化成 prompt 里的说明。
- `MemoryProjectionSkill` 用技能文件按动作选择投影策略，这比在检索器里写一堆条件更可维护，见 `app/agents/retrieval_planner.py:68` 和 `app/agents/skills/memory_projection/*.md`。
- 归档层默认不注入，但允许 cold recall，是一个合理方向，见 `app/runtime/memory_archival.py:13` 和 `app/agents/memory.py:160`。

## 主要问题

### P0：运行时仍是内存系统，不能承载生产

`InMemoryCaseStore` 和 `InMemorySessionStore` 只适合 MVP，见 `app/storage/memory.py:21`、`app/storage/memory.py:43`。事件、世界状态、记忆快照、角色画像都在进程内，重启即丢；并发请求也没有事务、版本号、幂等键或乐观锁。

后果：同一个 session 并发提交动作时，事件顺序、记忆归并和剧情阶段推进都可能产生不可审计的不一致。

下一步：先落地事件表和快照表，而不是先做更多 Agent 能力。事件 append 必须有单 session 顺序号、幂等 key、caused_by_event_id 索引、schema_version；记忆快照更新必须和事件写入处于同一事务边界。

### P0：真实 LLM 失败会被静默降级

`OpenAILLMAgent.generate` 捕获所有异常并返回 safe fallback，见 `app/agents/real_llm_agent.py:66`。这对 demo 友好，但对生产不可接受，因为它会把模型不可用、schema 不兼容、网络超时、合约校验失败都伪装成 NPC 正常拒答。

后果：线上质量下降无法快速定位，玩家体验和审计数据都会被污染。

下一步：区分 `transport_error`、`schema_error`、`policy_violation`、`timeout`、`rate_limit`；在 trace 和响应中记录错误类别；对关键剧情动作应允许返回明确的系统错误或可重试状态，而不是统一 fallback。

### P1：检索仍是启发式，离生产级记忆召回有距离

`MemoryRetriever` 主要依赖结构化锚点、文本 token、recency、reinforcement、salience 加权，见 `app/agents/memory.py:188`。中文处理是 CJK n-gram，见 `app/agents/memory.py:222`。这适合早期可控测试，但无法稳定处理同义表达、角色别称、案件语义、反事实问题和长剧情上下文。

最危险的是 fallback：没有相关命中时，会按 salience 注入高显著记忆，见 `app/agents/memory.py:148`。这会在玩家泛泛聊天时把高 salience 但不相关的敏感记忆塞给 NPC，增加越权披露概率。

下一步：保留当前规则检索作为 hard filter，再引入混合检索：结构化过滤、BM25/关键词、embedding、reranker。fallback 不能直接注入高 salience 记忆，应改为“无召回”或只允许白名单类型的低风险公共记忆。

### P1：记忆快照归并语义过硬编码

`MemorySnapshotSystem._reduce_candidate` 对已有快照会保留旧的 `rule_id/memory_type/memory_scope/memory_layer/owner/visible_to/content`，只合并来源、metadata、salience、confidence，见 `app/runtime/memory_snapshots.py:107` 到 `app/runtime/memory_snapshots.py:143`。

这保证了稳定性，但也会掩盖真实变化：同一 memory_id 后续如果应该提升可见范围、修正内容、降低 confidence、从 working 移入 archival，当前归并语义会让规则作者很难表达。归档系统能改 layer，但普通派生规则不能自然表达“修订”。

下一步：给记忆更新增加显式 operation：`create`、`reinforce`、`revise`、`supersede`、`merge_visibility`、`archive`。不同 operation 有不同字段变更白名单，并在事件 payload 中保留旧值摘要。

### P1：禁忌事实过滤仍是字符串匹配

记忆检索会用 forbidden fact 的 text 和 blocked_terms 做 substring 过滤，见 `app/agents/memory.py:261`；上下文 recent event 过滤也有类似逻辑，见 `app/agents/context.py:533`。Director 对输出也主要依赖 blocked terms、world_info title、aliases、patterns，见 `app/director/narrative_director.py:210`。

这比没有强，但不能覆盖改写、隐喻、同义词、部分泄密、跨句组合泄密。悬疑游戏最怕“半句真相”提前泄露，字符串过滤不能作为最终防线。

下一步：每个 `world_info` 应有 claim graph、safe fragments、forbidden inferences、phase gate；Director 后检不仅查文本，还要对 `disclosure_claims` 和 touched facts 做结构化一致性校验。

### P1：记忆元数据模型太窄，缺少生产索引字段

当前 metadata 只允许少量 key：`relationship_delta`、`strategy_id`、`belief_subject`、`belief_polarity`、`emotion_delta`、`clue_id`，见 `app/domain/models.py:157` 和 `app/domain/models.py:1147`。

这很安全，但记忆系统后续需要更多可索引字段：`world_info_id`、`claim_id`、`scene_id`、`topic_tags`、`source_action_type`、`observed_by`、`truth_status`、`decay_policy`、`privacy_reason`、`schema_version`。没有这些字段，检索质量和审计能力都会被迫依赖正文。

下一步：扩展 metadata schema，但不要放任任意 dict。每个 key 要有类型、索引策略和披露风险等级。

### P1：Agent 合约投影仍携带完整 memory snapshot 内容

`build_llm_agent_input` 会投影 context，但 `memory_snapshots` 本身仍在 `AgentContext` 中，见 `app/agents/llm_contract.py:20`、`app/agents/llm_contract.py:72`。这是合理的，因为 LLM 需要读取被检索出的记忆内容；真正的问题是这使检索边界成为唯一入口防线。

后果：只要检索放错一个敏感快照，LLM 就能看到完整内容。当前 trace 不记正文是对的，但线上调试会更难还原“为什么泄露”。

下一步：把 memory snapshot 分成 `content_for_llm` 和 `audit_payload`。LLM 只拿经过 Narrative Director 预检的安全摘要，原文只在服务端审计链路保留。

### P2：上下文预算压缩只是占位

`ContextBudgetManager` 用 `len(text)//4` 估 token，并在超阈值时只记录 ids，不做真正摘要，见 `app/runtime/budget.py:46`。这在长剧情、多角色、多记忆后很快失效。

下一步：压缩必须从事件日志和记忆快照生成可验证摘要，摘要本身也要有 source_event_ids/source_memory_ids，并且经过 Director 检查。

### P2：API 和运行环境还不够生产

API 没有认证、会话权限、速率限制、请求幂等和错误码体系，见 `app/api/routes.py:71`。`pyproject.toml` 声明 Python 3.11，但默认 `python` 在本机是 3.10，导致测试直接 collection error；项目依赖 `StrEnum` 和 `datetime.UTC`，必须强制 Python 3.11+。`.pytest_cache` 在工作区不可写也导致警告。

下一步：固定 `.python-version` 或工具链；CI 明确 `py -3.12`；pytest cache 和 basetemp 指向可写目录；API 加 session ownership 和 idempotency key。

## 后续路线

### 第一阶段：生产化状态底座

目标：任何剧情状态都能从事件日志稳定还原。

- 引入持久化事件存储：`world_events` 表，包含 session 顺序号、schema_version、actor_id、event_type、payload_json、caused_by_event_id、idempotency_key、created_at。
- 引入快照存储：session state、memory snapshots、character impressions 可由事件重放生成，也可定期保存快照加速读取。
- 所有动作处理加单 session 事务锁或乐观版本号。
- `ActionService.handle` 返回明确错误类别，不把系统错误伪装成剧情拒绝。

### 第二阶段：记忆系统升级

目标：记忆可解释、可检索、可降权、可修订。

- 定义 Memory v2 schema：增加 topic tags、world_info refs、scene refs、claim refs、privacy reason、decay policy、truth status。
- 增加显式 memory operation，不再只靠同 id 归并。
- 把当前检索器拆成 hard filter、candidate retriever、reranker、policy filter。
- 建立记忆检索评测集：每个标准剧情路径声明“该问法应召回/不应召回哪些 memory_id”。
- 归档不应只是 layer 切换，还应有摘要、冷召回触发条件和反泄密检查。

### 第三阶段：Narrative Director 强化

目标：Director 成为事实披露网关，而不是字符串防火墙。

- 给 world_info 建 claim graph：已知事实、可暗示事实、禁止推断、解锁条件。
- LLM 输出必须声明 touched_world_info 和 disclosure_claims；Director 对 speech 与声明做一致性校验。
- 对 memory content 预投影：Agent 只能拿当前 phase 允许的 memory fragment。
- 对玩家非线性探索做“可回答范围”规划，而不是简单拒绝。

### 第四阶段：真实 LLM 链路与观测

目标：线上问题能定位到输入、检索、模型、导演、规则哪个环节。

- LLM 调用错误分类、重试、熔断、超时、降级都进 trace。
- trace 中记录 memory projection、retrieval scores、policy filter reasons，但正文脱敏。
- 增加 shadow eval：同一事件序列跑 mock、real、repair 后模型，比较披露违规率和记忆引用准确率。

## 推荐最近两周工作顺序

1. 固定 Python 3.12/3.11 运行环境，修复 pytest cache/temp 权限问题。
2. 把事件日志和 session state 从内存迁到 SQLite/Postgres 的最小实现。
3. 给记忆快照加 operation 语义和 schema_version。
4. 禁止无相关性 fallback 注入高 salience 记忆。
5. 扩展 memory metadata，至少加入 `world_info_id`、`claim_id`、`scene_id`、`topic_tags`。
6. 建立记忆检索评测矩阵，先覆盖雾钟庄园核心线索。
7. 让 LLM fallback 错误进 trace 和 API 响应，不再静默吞掉。

## 本次验证

- `py -3.12 -m pytest tests/test_memory_layer.py tests/test_memory_retrieval_quality.py tests/test_typed_memory.py tests/test_memory_archival_p2.py tests/test_memory_scope.py tests/test_npc_memory_isolation.py tests/test_mist_clock_manor_memory_boundaries.py -k "not agent_trace_memory_ids_exclude_other_npc_private_memory and not real_backend_trace_records_memory_scope_layer_projection"`
- 结果：65 passed, 2 deselected。
- 被排除的两个 trace 测试依赖 `tmp_path`；本机 pytest 默认临时目录和工作区 `.pytest_cache` 存在权限问题，之前运行时在 fixture setup 阶段报 `PermissionError`，不是业务断言失败。
- 默认 `python` 指向 Python 3.10，会因为 `StrEnum` 和 `datetime.UTC` 导致 collection error；项目实际需要 Python 3.11+。
