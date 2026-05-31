# FactDisclosureStrategy 测试矩阵

本矩阵用于验证 NPC 在不同事实认知、玩家已知、压力等级和 `disclosure_style` 限制下，`FactDisclosureStrategy` 允许说什么、必须禁止什么。

测试对象：

- `WorldInfo`: `will_swapped`
- `NPC`: `butler`
- `disclosure_style.max_mode_by_world_info`: `will_swapped: hint`
- 绝对禁止：`full reveal`
- 绝对禁止：输出 private 原文、secret 原文、forbidden fact 原文或 solution claim 原文

## 判定规则

- `max_mode_by_world_info=hint` 表示最高只能到 `hint`，即使玩家已掌握相关事实，也不能升级到 `partial` 或 `full`。
- 自动化测试中，“玩家已掌握 `WorldInfo`”会作为 `player_known_world_info_ids` 传入策略生成器；它只允许生成安全引用，例如 `player_knowledge:will_swapped`，不能自动放宽披露等级。
- `low` 压力下优先保持角色默认认知姿态。
- `medium` 压力下可以增加回避、反问或有限暗示，但不能突破 `hint`。
- `high` 压力下应收窄到更保守表达，优先 `deny` / `deflect` / `counter_question`，并保留 `must_not_claim`。
- `must_not_claim` 在所有组合中都应存在，用于禁止直接承认、完整揭露或改写案件核心事实。

## 完整组合矩阵

| NPC 认知态度 | 玩家已知状态 | 压力等级 | disclosure_style 限制 | expected FactDisclosureStrategy 输出 |
|---|---|---|---|---|
| `knows` | 未掌握 `will_swapped` | `low` | `max=hint` | 允许 `hint`；可用 `qualify_certainty`；禁止 `partial` / `full`；必须包含 `must_not_claim` |
| `knows` | 未掌握 `will_swapped` | `medium` | `max=hint` | 允许 `hint` / `deflect`；可用 `qualify_certainty` / `counter_question`；禁止 `partial` / `full`；必须包含 `must_not_claim` |
| `knows` | 未掌握 `will_swapped` | `high` | `max=hint` | 允许 `deflect` / `counter_question`；必要时 `deny`；禁止 `hint` 以上、`partial` / `full`；必须包含 `must_not_claim` |
| `knows` | 已掌握 `will_swapped` | `low` | `max=hint` | 允许 `hint`；可承认证据方向但不展开；禁止 `partial` / `full`；必须包含 `must_not_claim` |
| `knows` | 已掌握 `will_swapped` | `medium` | `max=hint` | 允许 `hint` / `deflect`；可用 `answer_adjacent_truth` 但只能邻近表达；禁止 `partial` / `full`；必须包含 `must_not_claim` |
| `knows` | 已掌握 `will_swapped` | `high` | `max=hint` | 允许 `deflect` / `counter_question`；可用 `shift_focus`；禁止 `partial` / `full`；必须包含 `must_not_claim` |
| `suspects` | 未掌握 `will_swapped` | `low` | `max=hint` | 允许 `deflect` / `hint`；可用 `qualify_certainty`；禁止 `partial` / `full`；必须包含 `must_not_claim` |
| `suspects` | 未掌握 `will_swapped` | `medium` | `max=hint` | 允许 `deflect` / `hint` / `counter_question`；强调不确定性；禁止 `partial` / `full`；必须包含 `must_not_claim` |
| `suspects` | 未掌握 `will_swapped` | `high` | `max=hint` | 允许 `deflect` / `counter_question`；可用 `shift_focus`；禁止直接确认、`partial` / `full`；必须包含 `must_not_claim` |
| `suspects` | 已掌握 `will_swapped` | `low` | `max=hint` | 允许 `hint`；可用 `qualify_certainty`；不得把怀疑说成确认；禁止 `partial` / `full`；必须包含 `must_not_claim` |
| `suspects` | 已掌握 `will_swapped` | `medium` | `max=hint` | 允许 `hint` / `deflect`；可反问玩家证据来源；禁止 `partial` / `full`；必须包含 `must_not_claim` |
| `suspects` | 已掌握 `will_swapped` | `high` | `max=hint` | 允许 `deflect` / `counter_question`；可降低确定性；禁止确认、`partial` / `full`；必须包含 `must_not_claim` |
| `conceals` | 未掌握 `will_swapped` | `low` | `max=hint` | 允许 `deny` / `deflect` / `hint`；可用 `shift_focus`；禁止 `partial` / `full`；必须包含 `must_not_claim` |
| `conceals` | 未掌握 `will_swapped` | `medium` | `max=hint` | 允许 `deny` / `deflect` / `hint` / `counter_question`；优先转移重点；禁止 `partial` / `full`；必须包含 `must_not_claim` |
| `conceals` | 未掌握 `will_swapped` | `high` | `max=hint` | 允许 `deny` / `deflect` / `counter_question`；必要时沉默或情绪遮挡；禁止 `hint` 以上、`partial` / `full`；必须包含 `must_not_claim` |
| `conceals` | 已掌握 `will_swapped` | `low` | `max=hint` | 允许 `deflect` / `hint`；可用 `answer_adjacent_truth`，但不得承认完整事实；禁止 `partial` / `full`；必须包含 `must_not_claim` |
| `conceals` | 已掌握 `will_swapped` | `medium` | `max=hint` | 允许 `deny` / `deflect` / `hint` / `counter_question`；可半真半假但只到暗示；禁止 `partial` / `full`；必须包含 `must_not_claim` |
| `conceals` | 已掌握 `will_swapped` | `high` | `max=hint` | 允许 `deny` / `deflect` / `counter_question` / `shift_focus`；禁止 `hint` 以上、`partial` / `full`；必须包含 `must_not_claim` |

## 建议自动化断言

- 每一行都断言 `DisclosureMode.FULL` 不在 `allowed_modes`。
- 每一行都断言 `DisclosureMode.FULL` 在 `forbidden_modes`。
- `max=hint` 时断言 `DisclosureMode.PARTIAL` 不在 `allowed_modes`。
- 高压组合断言输出模式收窄到 `deny` / `deflect` 或安全反问类话术。
- `conceals` 组合断言存在 `must_not_claim`，且不能出现直接承认。
- `suspects` 组合断言不能把怀疑升级成确认。
- 玩家已掌握事实时，只能影响压力和安全引用，不能绕过 `disclosure_style` 上限。
