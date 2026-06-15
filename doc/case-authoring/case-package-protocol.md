# 案件包协议

案件包是 `cases/{case_id}` 下的一组 YAML 文件。运行时会扫描 `cases/*`，加载所有包含 `case.yaml` 的目录。

## 文件结构

```text
cases/{case_id}/
  case.yaml
  world_info.yaml
  characters.yaml
  scenes.yaml
  clues.yaml
  relationships.yaml
  forbidden_facts.yaml
  mock_dialogues.yaml
  narrative_rules.yaml
  solution_claims.yaml
```

## 命名规则

- 实体身份统一使用 `id`。
- 玩家动作目标统一使用 `target_id`。
- 关系两端使用 `source_id` 和 `target_id`。
- 线索引用使用 `clue_id`、`discover_clues`、`asked_subject_id` 或 `presented_clue`。
- 世界事实锚点使用 `world_info_id` 或 `related_world_info_ids`。
- 正式指控使用 `claim_id`。
- 旧字段 `source`、`target` 或玩家动作里的通用 `target` 会被拒绝。

## world_info.yaml

`world_info.yaml` 定义案件中的稳定事实锚点。它不等于线索，而是“可被知道、隐藏、误解、禁说、证明、指控”的事实。

示例：

```yaml
- id: desk_forced_open
  title: 书桌抽屉被撬开
  description: 抽屉在案发前后被非正常打开过。
  category: physical_fact
  sensitivity: low
  aliases:
    - 抽屉被撬
    - 书桌被强行打开
  claim_patterns:
    - "抽屉.*(撬|强行打开)"
```

常用字段：

- `id`：稳定事实 ID。
- `title`：事实标题。
- `description`：事实说明。
- `category`：事实类别，例如 `physical_fact`、`character_action`、`case_truth`。
- `sensitivity`：敏感度，例如 `low`、`medium`、`high`。
- `aliases`：可选，该事实常见自然语言说法，只用于 Director 文本审计。
- `claim_patterns`：可选，该事实变体表达的正则 pattern，只用于 Director 文本审计。

`aliases` 和 `claim_patterns` 不是新事实，不是线索，也不是状态。它们不会进入 `PlayerKnowledge`，也不会让 NPC 自动知道该事实。它们的唯一职责是帮助 `NarrativeDirector` 判断最终 `speech` 是否实际触碰某个 `WorldInfo`。

Loader 会在案件加载时校验 `claim_patterns` 正则语法。非法 pattern 会导致服务启动或 `case validate` 明确失败。旧案件没有这两个字段时仍按空列表加载。

## characters.yaml

角色使用公开/私有角色卡结构：

```yaml
- id: butler
  display_name: 韩管家
  public_role: 老宅管家
  public_description: 熟悉书房和钥匙管理。
  speech:
    style: 克制、谨慎、礼貌
    default_tone: formal
    catchphrases: []
    defensive_style: evasive
  personality:
    traits:
      - cautious
      - loyal
      - observant
    pressure_response: conceal
    trust_response: cautious_help
    fear_response: panic_conceal
  private:
    goals:
      - id: avoid_suspicion
        summary: 避免玩家过早发现遗嘱真相。
        priority: high
        related_world_info_ids:
          - will_swapped
        tags:
          - avoid_suspicion
    secrets:
      - id: swapped_will_awareness
        summary: 知道遗嘱相关文件存在异常。
        priority: high
        related_clue_ids:
          - scratched_drawer
        related_world_info_ids:
          - desk_forced_open
          - will_swapped
        disclosure_policy:
          revealable: false
          allowed_modes:
            - deny
            - deflect
            - hint
          direct_reveal_allowed: false
          direct_quote_allowed: false
    knowledge:
      - id: drawer_opened_last_night
        summary: 书桌抽屉昨夜被人打开过。
        priority: medium
        related_clue_ids:
          - scratched_drawer
        related_world_info_ids:
          - desk_forced_open
    disclosure_style:
      preferred_tactics:
        - answer_adjacent_truth
        - shift_focus
      forbidden_tactics:
        - emotional_screen
      max_mode_by_world_info:
        will_swapped: hint
```

`defensive_style` 可用值：`evasive`、`hostile`、`anxious`、`neutral`。

响应风格可用值：`answer`、`conceal`、`deflect`、`refuse`、`panic_conceal`、`cautious_help`。

Loader 仍兼容旧字段 `name`、`role`、`personality`、`speech_style`、`secrets`、`goals`、`knowledge`，并会归一化为新角色卡结构。新案件应使用显式 public/private 结构。

`private` 表示角色自己的非公开视角，不是对 NPC 自己隐藏：

- `private.goals`：内部动机，影响行为、偏好、回避和压力反应。
- `private.secrets`：NPC 默认有理由隐藏的信息。
- `private.knowledge`：NPC 自己视角中知道的事实。
- `private.disclosure_style`：角色表达风格偏好，只影响事实披露策略投影，不写入世界状态。

`private` 不等于 `forbidden_facts`，也不是永久禁言。它不能自动暴露给玩家、其他 NPC、`StateSummary`、玩家旅程 Markdown 或运行时事件。

新案件应给 private 项配置 `related_world_info_ids`，旧的 `related_clue_ids` 保留用于证据触发兼容。

`disclosure_style` 可配置：

- `preferred_tactics`：角色偏好的话术战术，例如 `answer_adjacent_truth`、`shift_focus`、`counter_question`、`qualify_certainty`、`emotional_screen`、`silence`。
- `forbidden_tactics`：该角色不应使用的话术战术，会从当前策略候选中移除。
- `max_mode_by_world_info`：按 `WorldInfo` 限制最高披露等级，取值为 `none`、`deny`、`deflect`、`hint`、`partial`、`full`。

关键边界：`max_mode_by_world_info` 只能收紧，不能放宽。配置 `will_swapped: hint` 表示这个角色最多暗示该事实；配置 `desk_forced_open: full` 也不会绕过通用策略、Narrative Director 或 Rule Engine 的禁令。Loader 会校验 `max_mode_by_world_info` 中的每个事实 ID 必须存在于 `world_info.yaml`。

## clues.yaml

`Clue` 是证据，不是真相本身。线索通过 `reveals_world_info` 指向事实锚点。

```yaml
- id: scratched_drawer
  title: 抽屉划痕
  description: 锁孔旁有新鲜划痕。
  truth_status: "true"
  reveals_world_info:
    - desk_forced_open
  related_characters:
    - butler
  key: true
```

`truth_status` 不会出现在公开 `StateSummary` 中。

## forbidden_facts.yaml

禁说事实应绑定到 `world_info_id`。关键词只是文本兜底校验，不是唯一事实锚点。

```yaml
- id: swapped_will
  world_info_id: will_swapped
  text: 遗嘱被调换过。
  blocked_terms:
    - 遗嘱被调换
  reveal_phase: reveal
```

`text` 和 `blocked_terms` 不得进入 `AgentContext` 或公开 API。

## mock_dialogues.yaml

每个对话块用 `character_id` 绑定角色。reply 可以按以下条件匹配：

- `phase`
- `asked_subject_type`
- `asked_subject_id`
- `presented_clue`
- `min_interaction_pressure`
- `max_interaction_pressure`
- `requires_subject_sensitive`
- `requires_discovered`
- `missing_discovered`
- `requires_memory`
- `missing_memory`
- `min_relationship`
- `max_relationship`

示例：

```yaml
- character_id: butler
  default_speech: 我不知道你是什么意思。
  default_intent: conceal
  relationship_delta_on_talk:
    suspicion: 1
  replies:
    - phase: investigation
      asked_subject_type: clue
      asked_subject_id: scratched_drawer
      min_interaction_pressure: 0.6
      requires_subject_sensitive: true
      speech: 你是在问我有没有打开过它吗？
      intent: probe
```

`asked_subject_id` 必须按 `asked_subject_type` 引用已存在的线索、角色或场景。`presented_clue` 必须引用已存在的线索。

`requires_memory` 和 `missing_memory` 匹配 `AgentMemorySnapshot.memory_id`。它们只是确定性 MockAgent 选择规则，不是向量记忆、RAG、LLM 摘要，也不能让 Agent 修改记忆。

## narrative_rules.yaml

支持字段：

- `phases`
- `beats`
- `all_completed`
- `min_completed`
- `all_discovered`
- `trigger_event_type`
- `trigger_payload`
- `next_phase`

只有 `RuleTriggerSystem` 可以完成 beat 或推进 phase。Agent 提出的 `narrative.phase.change` 会被 schema 接受以便审计，但会被 Rule Engine 拒绝。

事件触发 beat 示例：

```yaml
- id: case_solved
  phase: reveal
  all_completed:
    - hidden_meeting_connected
  trigger_event_type: accusation.evaluated
  trigger_payload:
    target_id: butler
    claim_id: butler_moved_key
    result: correct
  next_phase: resolved
```

触发检查只看导致 `RuleTriggerSystem.evaluate` 运行的当前事件，不扫描任意未来事件。

## solution_claims.yaml

`solution_claims.yaml` 定义正式指控。Rule Engine 使用它处理 `PlayerAction.accuse`；Agent 和 LLM 不评估指控正确性。

```yaml
claims:
  - id: butler_moved_key
    target_id: butler
    required_evidence:
      - scratched_drawer
      - dustless_frame
      - torn_note
    required_world_info:
      - desk_forced_open
      - portrait_was_moved
      - secret_meeting_note_exists
    allowed_phases:
      - reveal
    result: correct
```

校验内容：

- claim id 唯一
- `target_id` 引用已存在角色
- `required_evidence` 引用已存在线索
- `required_world_info` 引用已存在 WorldInfo
- `allowed_phases` 引用已声明剧情阶段
- `result` 只能是 `correct` 或 `incorrect`

claim 配置是案件作者真相数据，不得出现在 `StateSummary`。

## 校验命令

```powershell
py -3.12 -m app.cases.validate cases
```

校验会覆盖 characters、world_info、world_info claim patterns、scenes、clues、hotspots、relationships、mock_dialogues、forbidden_facts、narrative_rules、solution_claims 和线索可达性。

## 公开摘要安全

`StateSummary` 不得返回 `secrets`、`goals`、内部 `knowledge`、`truth_status`、禁说事实原文、blocked terms、`forbidden_facts`、`solution_claims` 或角色 private world_info refs。
