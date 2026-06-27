# PerceptionSystem V1

## 目标

`app/runtime/perception.py` 提供多 Agent 编排 V1 的观察切片：根据
`session.npc_locations` 和 `WorldEvent` 列表，为指定 NPC 生成未来
`npc.observed` 事件所需的安全 payload。

## 生产边界

- PerceptionSystem 只做可见性筛选和安全投影，不修改世界状态。
- 输出 payload 只包含 `observer_id`、`observed_event_id`、`scene_id`、
  `visibility`、`perception_quality`、`redacted_payload_ref`。
- 输出不复制原始 `WorldEvent.payload` 正文，NPC 后续上下文只能拿到受控引用。
- `director.blocked`、`rule.rejected`、`memory_candidate.created`、
  `agent_memory_snapshot.updated`、`character_impression.updated` 和
  `character_fact_awareness.updated` 默认不可观察。
- `memory_scope=npc_private` 或 `memory_scope=director_audit` 的事件不会进入普通
  NPC 观察上下文。

## V1 可见性规则

- 同场景公共事件可观察：事件 payload 必须有 `scene_id`，且 observer 当前
  `session.npc_locations[observer_id]` 位于同一场景。
- `present_clue(private)` 只给 `target_id` 对应 NPC。
- `present_clue(scene_shared)` 必须同时满足：
  - observer 在事件 `present_character_ids` 中；
  - observer 当前位于事件 `scene_id`。
- 带 `target_id` 的私聊型事件默认只给目标 NPC，第三方同场景也不可观察。

## 集成点

当前模型切片尚未定义 `EventType.NPC_OBSERVED`。后续模型切片补齐后，
orchestrator 可将 PerceptionSystem 输出 payload 包装为 `npc.observed`
`WorldEvent`，再交给 replay/projection 处理。
