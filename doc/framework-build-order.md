# 框架搭建顺序

当前只有一个案件方向，但案件内容尚未给出。因此框架搭建不能依赖具体剧情文本，而应先定义“案件包 Case Package”接口，让案件作为可替换内容接入系统。

## 核心结论

先搭系统骨架，不等案件细节。正确顺序是：领域模型 -> 案件包协议 -> 规则引擎 -> 事件日志 -> mock Agent -> API -> 前端壳 -> 再接真实 LLM 和真实案件。

不要一开始写完整剧情，也不要先做炫酷前端。否则后面案件一变，状态系统、线索系统和对话链路会全部返工。

## 第一阶段：建立领域骨架

目标是把游戏世界中不可变和可变的核心对象定义清楚。

优先建立这些概念：

- `Case`：案件定义，包含案件 ID、标题、简介、初始世界状态、角色、线索、场景和结案条件。
- `Character`：NPC 的身份、性格、目标、秘密、认知范围和说话风格。
- `Scene`：2D 场景、可交互热点、可出现角色、可调查物件。
- `Clue`：线索定义、发现条件、可见性、真假状态、关联事件和关联角色。
- `Relationship`：角色之间的信任、怀疑、恐惧、亲密、敌意。
- `WorldEvent`：所有玩家行为、NPC 行为和状态变化的事件日志。
- `NarrativeState`：剧情阶段、已释放线索、禁说事实、真相锚点。

这一阶段不要接 LLM。先让系统知道“什么是合法世界”。

## 第二阶段：定义案件包协议

案件内容没出来时，最重要的是定义案件怎么被加载。

建议案件以配置加脚本的方式组织：

```text
cases/
  case_001/
    case.yaml
    characters.yaml
    scenes.yaml
    clues.yaml
    relationships.yaml
    forbidden_facts.yaml
    mock_dialogues.yaml
```

各文件职责：

- `case.yaml`：案件元信息、初始剧情阶段、胜负条件。
- `characters.yaml`：NPC 设定、秘密、目标、初始关系。
- `scenes.yaml`：地图、热点、物件、初始可见角色。
- `clues.yaml`：线索、发现条件、依赖关系、是否关键线索。
- `relationships.yaml`：初始关系网络，端点字段固定为 `source_id` 和 `target_id`。
- `forbidden_facts.yaml`：当前阶段禁说事实和可释放阶段。
- `mock_dialogues.yaml`：当前阶段 mock Agent 固定回复和 proposed action 配置。

真实案件没出来前，可以做一个极小 fake case：1 个房间、2 个 NPC、3 条线索、1 个秘密。它不追求剧情精彩，只验证框架。

## 第三阶段：先做规则引擎

规则引擎是整个项目的地基，必须早于真实 Agent。

最小规则包括：

- 玩家能否调查某个热点。
- 玩家能否获得某条线索。
- NPC 是否能透露某个事实。
- 某个行为是否会改变关系。
- 哪些事件会推进剧情阶段。
- 哪些状态变化必须写入事件日志。

LLM 以后只提交 `proposed_actions`，规则引擎决定是否执行。

## 第四阶段：建立事件日志和回放能力

事件日志必须在 Agent 之前完成。

原因很简单：没有事件日志，就无法解释 NPC 为什么改变、线索为什么出现、剧情为什么推进。

最小事件类型：

- `player.moved`
- `player.inspected`
- `player.asked`
- `npc.replied`
- `clue.discovered`
- `relationship.changed`
- `narrative.phase.changed`
- `narrative.beat.completed`
- `memory.created`

每个事件至少包含：

- event_id
- case_id
- session_id
- actor_id
- event_type
- payload
- created_at
- caused_by_event_id

## 第五阶段：用 mock Agent 跑通闭环

真实 LLM 不要太早接入。先用 mock Agent 返回固定结构。

最小输出结构：

```json
{
  "speech": "我昨晚没见过他。",
  "intent": "conceal",
  "emotional_shift": { "fear": 1 },
  "proposed_actions": [
    {
      "type": "relationship.change",
      "source_id": "butler",
      "target_id": "player",
      "deltas": { "suspicion": 1 }
    }
  ],
  "memory_refs": []
}
```

这个阶段要验证：

- API 能收到玩家问题。
- 后端能加载角色、关系、线索和剧情阶段。
- mock Agent 能返回结构化意图。
- Director 能检查禁说内容。
- Rule Engine 能执行或拒绝 proposed_actions。
- WorldEvent 能完整记录链路。

## 第六阶段：搭 API，而不是先搭页面

API 是前后端契约，应该先稳定。

最小接口：

- `POST /sessions`：创建游戏会话。
- `GET /sessions/{id}/state`：读取当前世界状态摘要。
- `POST /sessions/{id}/actions`：提交玩家行为。
- `GET /sessions/{id}/events`：读取事件日志。
- `GET /sessions/{id}/clues`：读取玩家已发现线索。
- `GET /sessions/{id}/relationships`：读取关系图。

玩家所有操作都走统一 `actions` 入口，不要为每种动作随意加状态修改接口。

## 第七阶段：搭前端壳

前端第一版只做功能壳，不追求美术。

最小前端包括：

- 一个 2D 房间场景。
- 一个玩家角色或点击式移动。
- 两个 NPC 热点。
- 三个调查热点。
- 对话面板。
- 线索板。
- 事件调试面板。
- 关系状态面板。

前端不判断线索是否应该解锁，只展示后端返回结果。

## 第八阶段：接入真实 LLM

当 mock Agent 闭环稳定后，再接 LLM。

接入时要保留以下硬约束：

- LLM 输出必须 JSON schema 校验。
- schema 不合法时重试或降级到安全回复。
- Director 必须检查剧透和越权信息。
- Rule Engine 必须校验 proposed_actions。
- 所有 LLM 输入输出要能关联事件日志，便于调试。

## 第九阶段：接入真实案件

真实案件内容出来后，不应改系统骨架，只填案件包。

要补充：

- NPC 设定。
- 真实案件真相。
- 初始关系网。
- 场景与热点。
- 线索依赖图。
- 剧情阶段。
- 结案条件。
- 禁说事实与可说范围。

如果接真实案件时需要大改框架，说明前面的案件包协议设计失败。

## 最推荐的实际开发顺序

```text
1. 初始化仓库结构和文档
2. 建 FastAPI 空服务
3. 定义 Pydantic 领域模型
4. 定义案件包配置格式
5. 写一个 fake case
6. 实现事件日志
7. 实现规则引擎最小版
8. 实现 mock Agent
9. 实现 Director 最小剧透检查
10. 实现 actions API
11. 写后端集成测试
12. 搭 Next.js 前端壳
13. 接 Phaser/PixiJS 单场景
14. 接对话、线索板、关系图
15. 接真实 LLM
16. 替换为正式案件内容
```

## 当前阶段不该做什么

- 不要先写完整 UI。
- 不要先接复杂多 Agent 社交模拟。
- 不要先做向量记忆检索。
- 不要先设计开放世界。
- 不要把规则写进 prompt。
- 不要让前端直接修改权威状态。
- 不要等案件完整出来才开始搭框架。

## 当前最小可执行目标

当前最应该完成的是后端最小闭环：

```text
fake case
  -> 创建 session
  -> 玩家提交 PlayerAction
  -> mock Agent 返回 AgentIntent
  -> Director 检查
  -> Rule Engine 执行
  -> Rule Trigger System 评估 narrative_rules.yaml
  -> 写 WorldEvent
  -> 返回新状态摘要
```

这个闭环打通后，案件内容、前端表现、LLM 能力都可以逐步替换和增强。
