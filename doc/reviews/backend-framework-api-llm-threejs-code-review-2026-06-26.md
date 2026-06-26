# 后端框架、前端化 API、LLM Payload 与 Three.js 前端选型 Review

日期：2026-06-26

## 总结结论

后端主干方向是对的：玩家动作先进规则系统，LLM 只产出 NPC 表达和意图，真实状态由 Rule Engine 与事件日志驱动，Postgres 运行时也已经有 replay、expected sequence 与幂等写入意识。这不是玩具架构。

当前最核心的问题不是某个接口缺失，而是三个投影边界没有切干净：

1. 前端公开 DTO 与内部案件配置没有分离。
2. 真实 LLM Provider Payload 与审计/回放 Contract 没有分离。
3. 前端事件流 DTO 与内部 WorldEvent 审计日志没有分离。

这三个边界不切开，前端会继续拿不到稳定、低泄露、低耦合的数据；LLM token 会继续被审计字段浪费；后续维护会被大文件和隐式投影拖住。

## P0 问题

### 1. 真实 LLM 请求仍在发送完整审计 Contract

位置：

- `app/agents/real_llm_agent.py:202`
- `app/agents/real_llm_agent.py:249`
- `app/agents/real_llm_agent.py:386`
- `app/agents/llm_contract.py:38`
- `app/agents/llm_contract.py:176`
- `app/agents/llm_contract.py:252`
- `app/domain/models.py:1408`
- `app/domain/models.py:1444`

问题：

`RealLLMAgent` 把 `LLMAgentContractInput.model_dump(mode="json")` 直接序列化后发给 provider。`LLMAgentContractInput` 内部仍包含 `AgentContext`，而 `AgentContext` 里有 `recent_events`、`memory_snapshots`、`reply_options`、`inner_context`、`npc_skill_projections` 等内部对象。`_project_context_for_llm` 做了一层投影，但它返回的仍是 `AgentContext`，不是 provider 专用 DTO。

更严重的是，`_project_recent_events_for_llm` 只对 `memory.generated` 事件做了专门压缩，其他事件基本原样进入模型。这说明现在发送给模型的是“审计/回放对象的局部遮盖版”，不是“生成需要的最小上下文”。

影响：

- token 浪费是结构性问题，不是单纯记忆条数过多。
- 模型会看到不需要的审计字段，例如事件 payload、source ids、规则 trace、metadata、timestamps。
- 后续任何内部审计字段扩展，都可能无意进入模型上下文。
- schema repair 路径也重新发送完整 contract，失败重试时会继续放大成本。

建议：

新增真实 provider 专用 DTO，例如：

- `LLMProviderTurnPayload`
- `LLMProviderNPCProfile`
- `LLMProviderMemoryItem`
- `LLMProviderSafeFact`
- `LLMProviderRecentBeat`
- `LLMProviderOutputContract`

真实 provider payload 只允许包含：

- 当前 turn 的动作摘要。
- NPC 可公开角色风格与当前情绪目标。
- 被选择后的少量记忆摘要，且只保留来源类型或可信等级，不保留完整 audit id 列表。
- Narrative Director 给出的安全事实碎片。
- 对话输出合同、长度限制、禁止事项。
- 最近剧情 beat 的短文本摘要，不发完整 `WorldEvent`。

保留完整 `LLMAgentContractInput` 作为本地审计、回放、shadow eval、mock 测试对象，但不要直接给真实 provider。

验收测试：

- 真实 LLM 请求 payload 中不得包含 `reply_options`。
- 不得包含完整 `WorldEvent.payload`。
- 不得包含 `source_event_ids`、`source_memory_ids`、`created_at`、`updated_at`、`rule_id`，除非进入显式 allowlist。
- schema repair 请求不得重新发送完整审计 contract。

### 2. token 预算估算对象与真实发送对象不一致

位置：

- `app/agents/loop.py:248`
- `app/agents/loop.py:399`
- `app/agents/loop.py:631`
- `app/agents/real_llm_agent.py:202`

问题：

`AgentLoop` 先对 `PromptBundle` 文本做预算，再构造 `LLMAgentContractInput` 给真实 provider。预算用的是 prompt builder 产物，真实发送的是 contract JSON。也就是说，当前预算机制没有覆盖真正的 provider 输入。

影响：

- token 预算数据不可信。
- 压缩策略可能压错对象。
- 你实测的 `agent_context` 10.5k tokens 无法被当前预算机制精准治理。

建议：

预算入口应改为“真实 provider payload 序列化后的字符串”。也就是先构造 compact provider DTO，再预算、压缩、裁剪，最后发送同一个对象。审计 contract 可以单独存，不参与 provider 预算。

### 3. 前端化 API 缺少公开投影层

位置：

- `app/api/routes.py:31`
- `app/api/routes.py:35`
- `app/api/routes.py:58`
- `app/api/routes.py:75`
- `app/api/routes.py:160`
- `app/domain/models.py:836`
- `app/domain/models.py:844`
- `app/domain/models.py:852`
- `app/domain/models.py:1542`

问题：

目前 API 主要是 runtime 控制面：

- `GET /cases`
- `POST /sessions`
- `GET /sessions/{session_id}/state`
- `POST /sessions/{session_id}/actions`
- `GET /sessions/{session_id}/events`

这不足以支撑前端 2D/Three.js 场景。前端需要的是公开的“可渲染、可交互、无真相泄露”的投影，而不是内部 case config 或 runtime summary。

必须新增：

- `GET /cases/{case_id}`：公开场景、角色、热点、初始可见资源，不泄露真相。
- `GET /sessions/{id}/affordances`：当前能点什么、能问谁、能展示哪些证据、为什么不能做某些动作。
- `GET /sessions/{id}/events?after_count=N`：增量事件流。

关键点：

`GET /cases/{case_id}` 不能直接返回 `CasePackage`、`SceneConfig` 或 `ClueConfig`。`ClueConfig` 有 `truth_status`、`reveals_world_info` 等字段，属于推理真相和释放机制，不应进入公开 DTO。

Three.js 前端还需要场景布局字段。当前 `SceneHotspotConfig` 只有 `id`、`name`、`description`、`discover_clues`、`backtrack_unlocks`，缺少前端渲染所需的 position、bounds、camera、layer、asset reference 等公开 presentation 配置。建议新增可选的 authoring 字段，但只通过 public DTO 暴露安全子集。

## P1 问题

### 4. 错误响应不是前端级契约

位置：

- `app/api/routes.py:68`
- `app/api/routes.py:96`
- `app/api/routes.py:141`

问题：

路由层大量使用 `detail=str(exc)` 或 `detail=exc.message`。`ActionValidationError` 甚至被映射成 404。前端需要稳定的 error code、message、retryability、field/path、action hint，而不是人类字符串。

建议：

新增统一错误 DTO：

- `code`
- `message`
- `details`
- `retryable`
- `correlation_id`

例如：

- `CASE_NOT_FOUND`
- `SESSION_NOT_FOUND`
- `ACTION_NOT_ALLOWED`
- `CLUE_NOT_DISCOVERED`
- `TARGET_NOT_VISIBLE`
- `IDEMPOTENCY_CONFLICT`

### 5. 增量事件 API 需要 cursor DTO，不能直接暴露审计 WorldEvent

位置：

- `app/api/routes.py:160`
- `app/storage/postgres.py:486`
- `app/runtime/postgres_runtime.py:136`

问题：

Postgres 事件表有 session-local `sequence`，并且按 sequence replay，这是正确的。但 API 当前返回的是 `list[WorldEvent]`，`WorldEvent` 自身没有 sequence 字段。`after_count=N` 如果只按数量切片，必须明确它是 count cursor 还是 event sequence cursor，否则前端断线续拉会出现语义不清。

建议：

新增 `EventStreamItem`：

- `sequence`
- `event_id`
- `type`
- `actor_id`
- `public_payload`
- `created_at`

再新增 `EventStreamResponse`：

- `items`
- `next_after_count`
- `has_more`

内部 `WorldEvent` 保持审计用途；前端只拿公开事件投影。

### 6. `StateSummary` 可以服务 runtime，但不应替代公开场景 DTO

位置：

- `app/domain/models.py:1503`
- `app/domain/models.py:1516`
- `app/domain/models.py:1542`
- `app/storage/memory.py:338`

问题：

`StateSummary` 目前包含角色、已发现线索、player knowledge、evidence assets、relationship、event_count。它适合 session runtime UI，但不适合作为案件公开详情。尤其 `PlayerKnowledgeSummary` 和 `EvidenceSummary` 中的 `world_info_id` 对前端不一定必要，容易让 UI 与内部世界信息锚点耦合。

建议：

- `GET /cases/{case_id}` 返回 public static projection。
- `GET /sessions/{id}/state` 返回 session dynamic projection。
- `GET /sessions/{id}/affordances` 返回 interaction projection。
- `GET /sessions/{id}/events` 返回 event stream projection。

不要让一个 summary DTO 承担所有用途。

### 7. affordances 必须复用 Rule Engine，而不是在前端重写规则

位置：

- `app/rules/engine.py:84`
- `app/rules/engine.py:268`
- `app/rules/engine.py:361`
- `app/rules/engine.py:458`
- `app/rules/engine.py:536`

问题：

`RuleEngine` 已经掌握 inspect、talk、ask_about、present_clue、accuse 的合法性。affordances 如果由前端猜，必然和后端分叉。

建议：

新增 `AffordanceService`，以当前 `WorldState`、`CasePackage`、`StateSummary` 为输入，枚举可交互对象，再调用与 `precheck_player_action` 同源的规则函数。输出允许项与禁止项都要有 reason code。这样前端可以灰显、隐藏、解释，而后端仍是唯一裁判。

## P2 问题

### 8. 大文件职责已经越界，应按边界拆分

位置：

- `app/runtime/derivations.py`
- `app/agents/real_llm_agent.py`

`real_llm_agent.py` 当前混合了 provider transport、重试、schema repair、JSON extraction、本地输出 projection、schema 构建、环境变量解析。建议拆为：

- `app/agents/provider_payload.py`：compact provider DTO 与投影。
- `app/agents/provider_transport.py`：Responses API、Chat Completions、重试。
- `app/agents/provider_schema.py`：JSON schema 构建。
- `app/agents/provider_repair.py`：schema repair。
- `app/agents/output_projection.py`：provider response 到 `AgentIntent`。
- `app/agents/provider_errors.py`：错误分类。

`derivations.py` 当前混合 clue memory、scene shared memory、accusation、impressions、metadata、evidence narration。建议拆为：

- `app/runtime/derivations/player_knowledge.py`
- `app/runtime/derivations/clue_memory.py`
- `app/runtime/derivations/scene_shared.py`
- `app/runtime/derivations/accusation.py`
- `app/runtime/derivations/impressions.py`
- `app/runtime/derivations/metadata.py`

保留一个薄的 `DerivedEventSystem` 作为编排层。

### 9. domain models 也偏大，但不应优先拆

位置：

- `app/domain/models.py`

`models.py` 已经接近 1500 行，但现在先拆它不是最优先。真正阻碍生产化的是 public API DTO、provider DTO 和 event stream DTO 没切出来。等这些边界稳定后，再按 case authoring、runtime state、LLM contract、public API 分拆模型文件。

## 架构优点

1. `ActionService` 的状态变更链路是正确的：玩家动作进入规则系统，Agent 只生成回复和意图，Director 校验后才落事件。
2. `RuleEngine` 没把核心规则藏在 prompt 里，这是生产级悬疑系统必须坚持的边界。
3. Postgres runtime 以事件流 replay 当前状态，并使用 expected sequence 做并发保护，方向正确。
4. mock LLM、shadow eval、trace projection 已经有基础，只是 provider payload 边界需要独立。

## 推荐实现顺序

1. 新增 `PublicCaseDetail` 和 `GET /cases/{case_id}`，补测试证明不泄露 `truth_status`、`reveals_world_info`、private dialogue、mock reply。
2. 新增 `AffordanceService` 和 `GET /sessions/{id}/affordances`，复用 Rule Engine 输出可用动作与 reason code。
3. 新增 `EventStreamItem`、`EventStreamResponse`，让 `GET /sessions/{id}/events?after_count=N` 返回带 sequence 的公开增量事件。
4. 新增 `LLMProviderTurnPayload`，真实 provider 只吃 compact DTO。
5. 把 token budget 移到 compact provider payload 上。
6. 拆 `real_llm_agent.py`。
7. 拆 `derivations.py`。

## Three.js 前端选型

结论：这个项目不适合直接套一个重物理、自由漫游的 3D 游戏模板。它更像“2.5D 悬疑房间 + 热点交互 + 对话/线索 UI”。前端应以 React UI 为主，Three.js 场景作为可点击的空间层。

推荐技术栈：

- React + TypeScript。
- `@react-three/fiber` 作为 Three.js 的 React renderer。
- `@react-three/drei` 提供 camera、controls、HTML overlay、常用 helpers。
- `gltfjsx` 把 GLB/GLTF 资产转成 React component，并做压缩优化。
- TanStack Query 或 SWR 读取 `/cases/{id}`、`/state`、`/affordances`、`/events`。
- Zustand 或 Jotai 管理 UI 层临时状态。

可参考项目：

1. `pmndrs/react-three-next`
   - 地址：https://github.com/pmndrs/react-three-next
   - 适合 Next.js 项目。它强调 persistent canvas 与 DOM/Canvas 路由组织，适合作为“React UI + Three 场景层”的起点。
2. `pmndrs/react-three-fiber`
   - 地址：https://github.com/pmndrs/react-three-fiber
   - 核心库。仓库说明它是 Three.js 的 React renderer，并列出 drei、gltfjsx、postprocessing、rapier、uikit 等生态。
3. `pmndrs/drei`
   - 地址：https://github.com/pmndrs/drei
   - 常用 helpers 集合，camera、controls、HTML overlay、environment、text 等能力都能减少自造轮子。
4. `pmndrs/gltfjsx`
   - 地址：https://github.com/pmndrs/gltfjsx
   - 用于把 GLTF 转为 JSX component，并支持 transform、压缩、裁剪无用节点，适合管理场景资产。
5. `wass08/r3f-vite-starter`
   - 地址：https://github.com/wass08/r3f-vite-starter
   - 如果前端不用 Next，而是 Vite，可以参考它的最小结构。但这个仓库体量和维护信号弱于 pmndrs 官方生态，不建议直接作为生产基座。
6. `pmndrs/ecctrl`
   - 地址：https://github.com/pmndrs/ecctrl
   - 如果后续要做键盘自由移动和物理角色控制再引入。当前 MVP 更建议用 orthographic camera、raycaster/hotspot mesh 和 HTML overlay，不要先上物理控制器。
7. `pmndrs/racing-game`
   - 地址：https://github.com/pmndrs/racing-game
   - 可看 R3F 组件组织和游戏 loop 写法，不适合作为悬疑叙事游戏基座。

官方参考：

- Three.js 文档：https://threejs.org/docs/

## 前端 API 建议形态

### `GET /cases/{case_id}`

用途：进入案件前渲染公开地图、场景、角色、热点、可见资源。

返回应包含：

- `case_id`
- `title`
- `public_summary`
- `initial_scene_id`
- `scenes`
- `characters`
- `assets`

必须排除：

- `truth_status`
- `reveals_world_info`
- 全局真相锚点
- 未解锁 clue 真实含义
- private memory
- mock `reply_options`

### `GET /sessions/{id}/affordances`

用途：告诉前端当前能点什么，而不是让前端猜规则。

返回应包含：

- `inspectable_hotspots`
- `talk_targets`
- `askable_topics`
- `presentable_evidence`
- `accusation_options`
- `disabled_actions`
- `reason_code`

### `GET /sessions/{id}/events?after_count=N`

用途：前端断线续拉、动画补帧、对话增量更新。

返回应包含：

- `items`
- `next_after_count`
- `has_more`

每个 item 至少包含：

- `sequence`
- `event_id`
- `type`
- `actor_id`
- `public_payload`
- `created_at`

## 最小验收标准

1. public case API 的测试断言 JSON 中不存在 `truth_status`、`reveals_world_info`、`world_truth`、`reply_options`。
2. affordances 的测试覆盖 inspect、talk、ask_about、present_clue、accuse 的允许与禁止路径。
3. event stream 的测试覆盖 `after_count=0`、中间 cursor、越界 cursor。
4. 真实 LLM payload 的测试断言不会出现 `reply_options`、完整 `WorldEvent.payload`、audit source ids、timestamps。
5. token budget 测试使用真实 provider payload 字符串，而不是 prompt builder 的另一份文本。

