# 前端接入前的后端 MVP 收口方案

生成时间：2026-06-18

## 结论

当前后端已经具备“接前端第一版”的核心能力：案件加载、创建 session、公开状态摘要、结构化动作、自然语言 action intake、事件日志、规则校验、Director 拦截、mock/real LLM 适配边界、PostgreSQL event stream 模式。

但还不能直接宣称后端初版完成。前端需要的不是更多 Agent 能力，而是更稳定的公开投影和 UI 语义。最该补的是：

1. 公开案件详情 / 场景图投影 API。
2. 前端动作可用性与错误 reason 规范。
3. 事件增量读取或最小轮询协议。
4. PostgreSQL 运行模式的启动、schema、幂等和回放验收脚本。
5. `mist_clock_manor` 标准路径作为前后端联调脚本。

不要现在做小镇多 Agent、NPC 自主 tick、复杂前端任务系统或真实 LLM 全量接入。那些会扩大不确定性，拖慢第一版 UI 闭环。

## 当前已具备

现有 API：

- `GET /health`
- `GET /cases`
- `POST /sessions`
- `GET /sessions/{session_id}/state`
- `POST /sessions/{session_id}/actions`
- `POST /sessions/{session_id}/raw-actions`
- `GET /sessions/{session_id}/events`

现有后端能力：

- `StateSummary` 已能返回公开角色、已发现线索、玩家知识、证据资产、关系和事件数量。
- `PlayerAction` 已覆盖第一版核心玩法：`inspect`、`talk`、`ask_about`、`present_clue`、`accuse`。
- `ActionRouter` 已支持 raw text 到结构化 action 的 intake。
- `RuleEngine` 已能拒绝非法线索、非法指控、未知对象、未发现证据。
- `NarrativeDirector` 已能拦截阶段外剧透和 forbidden fact。
- `AgentLoop` 已有 mock、stub、real LLM 后端边界。
- `RuntimeTrace` 已有脱敏 trace。
- `PostgreSQL` runtime 已有 event stream、幂等、trace 同事务落库路径。
- `mist_clock_manor` 已有标准路径和 deviation scenarios。

这说明第一版前端可以先做“静态场景探索 + 对话 / 展示证据 / 指控 + 线索板 + 事件反馈”，不必等小镇模拟。

## 必须补的后端接口

### 1. Case Detail / Scene Graph

前端不能直接读 `cases/*.yaml`。它需要后端提供公开案件投影。

建议新增：

```http
GET /cases/{case_id}
```

响应只包含公开字段：

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
          "name": "红酒杯",
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

明确禁止暴露：

- `truth_status`
- `reveals_world_info`
- `forbidden_facts`
- `solution_claims`
- character `private`
- mock dialogue
- memory derivation rules
- npc skill hidden config
- narrative rule internals

### 2. Action Affordance Projection

前端需要知道“当前可点什么”，否则只能盲目提交再被拒绝。

建议第一版不要做复杂 capability engine，先在 `StateSummary` 或新 endpoint 中给最小投影：

```json
{
  "available_hotspot_ids": ["wine_table", "study_lock"],
  "discovered_clue_ids": ["bitter_wine"],
  "evidence_asset_ids": ["bitter_wine"],
  "available_character_ids": ["lin_qichi", "qi_yan"],
  "can_accuse": false
}
```

更稳的做法是新增：

```http
GET /sessions/{session_id}/affordances
```

第一版只需支持：

- 当前所有公开 hotspot 可 inspect。
- 已发现 clue 可 ask_about / present_clue。
- 已有 evidence_assets 可用于 accuse。
- 正式 accuse 的 claim 列表暂不暴露，前端第一版可隐藏最终指控，或用固定按钮提交已配置 claim。

### 3. Events Incremental Read

现在 `GET /sessions/{session_id}/events` 返回全量事件。第一版可以用，但前端轮询会越来越重。

建议新增查询参数：

```http
GET /sessions/{session_id}/events?after_event_count=12
```

或：

```http
GET /sessions/{session_id}/events?after_sequence=12
```

当前 `WorldEvent` 没有 sequence 字段，短期可用 `StateSummary.event_count` 做游标；长期 PostgreSQL event stream 应显式返回 sequence。

第一版前端轮询策略：

- action response 已带 `new_events`，先直接渲染。
- 页面恢复 / 多标签时再拉全量或增量 events。
- 暂不做 websocket。

### 4. Stable UI Reason

前端不能解析英文异常字符串。

建议给 `rule.rejected`、raw action rejected、Director block 统一稳定 reason code。

现状已有部分 reason，但需要承诺：

```json
{
  "code": "clue_not_discovered",
  "message": "This clue has not been discovered.",
  "field": "clue_id"
}
```

第一版最少要覆盖：

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

### 5. Frontend Bootstrap Contract

建议前端启动流程固定为：

```text
GET /cases
GET /cases/{case_id}
POST /sessions { case_id }
GET /sessions/{session_id}/state
```

之后每个玩家交互：

```text
POST /sessions/{session_id}/actions
  -> render speech
  -> apply state
  -> append new_events to log
```

自然语言输入：

```text
POST /sessions/{session_id}/raw-actions
  -> if needs_clarification: show clarification UI
  -> if rejected: show reason
  -> if accepted: render nested ActionResponse
```

## 后端初版完成定义

后端 MVP 完成，不是“所有设想都做完”，而是满足下面验收。

### API 验收

- 前端无需读 YAML。
- 前端能拿到公开 scene / hotspot / character。
- 前端能创建 session 并恢复公开状态。
- 前端能提交五类结构化 action。
- 前端能提交 raw text，并处理 clarification / rejected / accepted。
- Action response 足够渲染台词、事件、状态、证据栏和关系变化。
- 所有失败都有稳定 reason code 或 event type。

### 剧情验收

用 `mist_clock_manor/scenarios/standard_path.yaml` 做联调脚本，前端能跑通：

1. 检查酒桌。
2. 询问 / 展示酒液。
3. 检查门锁。
4. 检查录音机进入 confrontation。
5. 触发一次 Director block。
6. 展示门锁线索。
7. 检查烧毁供词、药盒、电闸箱。
8. 正式指控进入 resolved。

每一步前端只依赖 API 响应，不读内部案件文件。

### 状态验收

- `StateSummary` 不泄露 private、truth、solution、forbidden fact。
- `events` 中 `director.blocked.payload.matched_text` 始终脱敏。
- replay 后 `StateSummary` 与当前状态一致。
- PostgreSQL runtime 下重复同一 `Idempotency-Key` 不重复写事件。

### 观测验收

- action backend error 不等于 LLM fallback。
- LLM fallback 有 `llm_fallback_used` 和 `llm_error`。
- Director block 有 `director_blocked` 和 `director_reason`。
- runtime trace 不记录玩家原文、memory content、private 原文、safe fragment summary。

## 第一版不做什么

不要把这些塞进前端接入前置：

- 小镇式多 Agent tick。
- NPC 自主移动。
- NPC-NPC 社交传播。
- WebSocket。
- 复杂任务日志。
- 关系图高级推理。
- 真实 LLM 作为默认路径。
- 向量库。
- 前端可见 NPC private memory。

这些都应该在第一版 UI 闭环稳定后再做。

## 推荐执行顺序

### Step 1：补公开案件详情接口

新增 DTO：

- `CaseDetail`
- `SceneSummary`
- `HotspotSummary`

新增 endpoint：

```http
GET /cases/{case_id}
```

加测试：不得泄露 `truth_status`、`forbidden_facts`、`solution_claims`、character private。

### Step 2：补 affordances

第一版可以简单：

```http
GET /sessions/{session_id}/affordances
```

返回 hotspot、known clue、evidence asset、character ids。

### Step 3：补 reason code

统一 `rule.rejected` payload 和 raw action rejected response。不要让前端从英文 message 猜 UI。

### Step 4：跑前后端联调脚本

把 `mist_clock_manor` 标准路径转成 Postman / curl / Playwright API 流程。先用 mock backend。

### Step 5：PostgreSQL 模式冒烟

用：

```powershell
$env:AGENT_RUNTIME="postgres"
$env:AGENT_POSTGRES_APPLY_SCHEMA="1"
uvicorn app.main:app --reload
```

验证：

- create session
- submit action
- repeat idempotency key
- restart server
- get state from replay

## 最终建议

现在后端初版的最优收口不是继续堆 Agent 能力，而是把“公开投影 API + 稳定 UI 语义 + 标准路径联调”补齐。只要这三件事完成，前端就可以开始做 2D 场景、热点、对话框、线索板、关系面板和指控流程。

