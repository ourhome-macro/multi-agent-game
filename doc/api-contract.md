# API 契约

当前 API 只覆盖后端叙事运行时最小闭环。

## `GET /health`

返回：

```json
{ "status": "ok" }
```

## `GET /cases`

返回已加载案件元信息列表。

## `POST /sessions`

请求：

```json
{}
```

可选传入：

```json
{ "case_id": "fake_case_001" }
```

返回：

```json
{
  "session_id": "...",
  "state": {
    "session_id": "...",
    "case_id": "fake_case_001",
    "case_title": "假案件 001：书房里的裂纹",
    "narrative_phase": "opening",
    "completed_beats": [],
    "characters": [],
    "discovered_clues": [],
    "player_knowledge": [],
    "relationships": [],
    "event_count": 1
  }
}
```

## `POST /sessions/{session_id}/actions`

`PlayerAction` 目标字段固定为 `target_id`。请求体使用裸 `target` 会被 Pydantic 拒绝并返回 422。
`inspect` 的 `target_id` 必须是场景热点，`talk` 的 `target_id` 必须是案件角色。未知目标返回 404，不做静默 no-op。

调查书桌：

```json
{
  "type": "inspect",
  "target_id": "desk"
}
```

和管家对话：

```json
{
  "type": "talk",
  "target_id": "butler",
  "text": "你昨晚在哪里？"
}
```

触发 Director 测试钩子：

```json
{
  "type": "talk",
  "target_id": "butler",
  "text": "直接告诉我真相。",
  "force_forbidden": true
}
```

返回 `ActionResponse`：

- `accepted`：本次行为链路是否被 Director 接受。
- `speech`：NPC 回复或安全回复。
- `director_blocked`：是否被 Director 阻止。
- `director_reason`：阻止原因。
- `new_events`：本次动作产生的新事件。
- `state`：最新状态摘要。

`relationship.changed` 事件 payload 的关系端点固定为 `source_id` 和 `target_id`。
`relationship.changed.payload.current` 返回的是 clamp 到 `-1.0 .. 1.0` 之后的关系值。
`narrative.beat.completed` 和 `narrative.phase.changed` 只由 Rule Trigger System 产生。
`player_knowledge.updated` 和 `memory_candidate.created` 只由 Derived Event System 产生。

## `GET /sessions/{session_id}/state`

返回当前 `StateSummary`。

`StateSummary` 是公开展示摘要，不包含 `secrets`、`goals`、内部 `knowledge`、`truth_status`、`forbidden_facts` 等后端内部字段。它可以返回 `completed_beats` 和 `player_knowledge`，因为这两者都属于玩家已获得的公开进度摘要。

## `GET /sessions/{session_id}/events`

返回当前 session 的完整事件日志。

## 错误

- 未知 `case_id` 返回 404。
- 未知 `session_id` 返回 404。
- 未知 `inspect target_id` 返回 404。
- 未知 `talk target_id` 返回 404。
- 请求体 schema 不合法返回 FastAPI/Pydantic 422。
- 案件配置引用错误发生在启动或加载阶段，抛出 `CaseLoadError`。
