# 前端接入前的后端 MVP 收口方案

原始日期：2026-06-18  
整理日期：2026-06-26

## 结论

后端已经具备第一版前端接入的核心链路：案件加载、session、公开状态、结构化动作、自然语言 action intake、事件日志、Rule Engine、Narrative Director、mock/real LLM 边界、PostgreSQL event stream 和 `mist_clock_manor` 标准路径。

但前端还不能直接宣称接入完成。缺口不是更多 Agent 能力，而是稳定公开投影：

1. 公共 case detail / scene graph API。
2. action affordances API。
3. 稳定 error reason code。
4. 增量 events 读取。
5. 标准路径前后端 smoke test。

Three.js 具体实现方案见 [../frontend/threejs-frontend-plan.md](../frontend/threejs-frontend-plan.md)。

## 必须补的接口

### `GET /cases/{case_id}`

返回公开案件详情：

```json
{
  "id": "mist_clock_manor",
  "title": "雾钟山庄",
  "description": "...",
  "initial_phase": "opening",
  "scenes": [
    {
      "id": "study",
      "name": "书房",
      "description": "...",
      "characters": ["lin_qichi", "qi_yan", "jiang_yanhui"],
      "hotspots": [
        {
          "id": "wine_table",
          "name": "红酒桌",
          "description": "..."
        }
      ]
    }
  ],
  "characters": [
    {
      "id": "lin_qichi",
      "display_name": "林栖迟",
      "public_role": "...",
      "public_description": "..."
    }
  ]
}
```

禁止暴露：

- `truth_status`
- `reveals_world_info`
- `forbidden_facts`
- `solution_claims`
- character `private`
- mock dialogue
- memory derivation rules
- npc skill hidden config
- narrative rule internals

### `GET /sessions/{session_id}/affordances`

返回当前可交互对象和合法动作：

```json
{
  "available_hotspot_ids": ["wine_table", "study_lock"],
  "available_character_ids": ["lin_qichi", "qi_yan"],
  "discovered_clue_ids": ["bitter_wine"],
  "evidence_asset_ids": ["bitter_wine"],
  "valid_presentation_modes": ["private", "scene_shared"],
  "can_accuse": false
}
```

第一版 affordances 不需要完整 capability engine，只需要避免前端盲交互。

### `GET /sessions/{session_id}/events?after_count=N`

当前 `GET /events` 可用于调试，但前端轮询长期会变重。短期可以用 `StateSummary.event_count` 作为游标；长期 PostgreSQL event stream 应返回稳定 sequence。

### 稳定错误 DTO

不要让前端解析异常字符串。统一错误结构：

```json
{
  "code": "clue_not_discovered",
  "message": "This clue has not been discovered.",
  "field": "clue_id"
}
```

至少覆盖：

- `unknown_session`
- `unknown_case`
- `unknown_target`
- `unknown_clue`
- `clue_not_discovered`
- `knowledge_not_unlocked`
- `invalid_presentation_mode`
- `scene_required`
- `target_not_in_scene`
- `claim_not_available`
- `missing_evidence`
- `director_blocked`
- `needs_clarification`

## 前端启动流程

```text
GET /cases
GET /cases/{case_id}
POST /sessions { case_id }
GET /sessions/{session_id}/state
GET /sessions/{session_id}/affordances
```

玩家交互：

```text
POST /sessions/{session_id}/actions
  -> render speech
  -> apply state
  -> append new_events
  -> refresh affordances
```

自然语言输入：

```text
POST /sessions/{session_id}/raw-actions
  -> accepted: render nested ActionResponse
  -> needs_clarification: show clarification UI
  -> rejected: show reason code
```

## 第一版不做

- NPC 自主 tick。
- NPC 自主移动。
- NPC-NPC 社交传播。
- WebSocket。
- 复杂任务系统。
- 前端推理关系图。
- 真实 LLM 默认路径。
- 向量库。
- 前端可见 NPC private memory。

## 验收路径

用 `mist_clock_manor/scenarios/standard_path.yaml` 做前后端联调脚本：

1. 检查酒桌。
2. 询问或展示红酒线索。
3. 检查门锁。
4. 检查录音机进入 confrontation。
5. 触发一次 Director block。
6. 展示门锁线索。
7. 检查烧毁供词、药盒、电闸箱。
8. 正式指控进入 resolved。

每一步前端只依赖 API，不读取内部案件文件。

