# Case Package 协议

本文件冻结当前阶段的案件包文件协议。后续真实案件接入前，优先改这里和 Pydantic 模型，不允许文档、fake case、loader 三处各说各话。

## 目录结构

```text
cases/{case_id}/
  case.yaml
  characters.yaml
  scenes.yaml
  clues.yaml
  relationships.yaml
  forbidden_facts.yaml
  mock_dialogues.yaml
  narrative_rules.yaml
```

## 命名冻结

- 统一使用 `id` 表示配置实体自身 ID。
- 玩家行为目标固定使用 `target_id`，禁止使用裸 `target`。
- 关系端点固定使用 `source_id` 和 `target_id`，禁止使用裸 `source` / `target`。
- 线索引用固定使用 `clue_id` 或 `discover_clues`。
- proposed action 类型只能来自 `ProposedActionType` 白名单：`clue.discover`、`relationship.change`、`narrative.phase.change`。
- `narrative.phase.change` 可以被 Agent 提出，但 Rule Engine 必须拒绝；真实 phase 只能由 `narrative_rules.yaml` 推进。

## 文件职责

- `case.yaml`：`id`、`title`、`description`、`initial_phase`。
- `characters.yaml`：角色公开身份，以及后端内部使用的 `secrets`、`goals`、`knowledge`。
- `scenes.yaml`：场景、热点、角色出现位置和热点可解锁线索。
- `clues.yaml`：线索定义。`truth_status` 必须写成 `"true"`、`"false"` 或 `"unknown"` 字符串。
- `relationships.yaml`：初始关系，端点字段为 `source_id`、`target_id`。
- `forbidden_facts.yaml`：Director 禁说事实、触发词和允许透露阶段。
- `mock_dialogues.yaml`：当前 mock Agent 回复和关系变化配置。
- `narrative_rules.yaml`：剧情阶段、beat 条件和 phase 推进规则。

## Narrative Rules

`narrative_rules.yaml` 当前支持：

- `phases`：声明所有合法剧情阶段。
- `beats`：声明可完成的剧情 beat。
- `all_completed`：要求已完成的 beat 列表。
- `min_completed`：要求至少完成的 beat 数。
- `all_discovered`：要求已发现的线索列表。
- `next_phase`：beat 完成后推进到的阶段。

Rule Trigger System 会在动作事件后评估 rules。满足条件时写入 `narrative.beat.completed`；如果配置了 `next_phase`，再写入 `narrative.phase.changed`。

## 校验命令

使用以下命令校验所有案件包：

```powershell
py -3.12 -m app.cases.validate cases
```

校验范围包括角色、场景、线索、热点、关系、mock dialogues、forbidden facts、narrative rules 引用，以及所有线索至少有一种可达方式。

## 防泄露要求

`StateSummary` 只能返回展示摘要：

- 角色只返回 `id`、`name`、`role`。
- 线索只返回已发现线索的 `id`、`title`、`description`、`key`。
- 不返回 `secrets`、`goals`、`knowledge`、`truth_status`、`forbidden_facts`。

这个约束已经由测试覆盖，未来新增字段时必须先判断它是公开展示字段还是后端内部字段。
