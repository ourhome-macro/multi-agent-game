# Scenario 文件化协议 v0

## 定位

每个进入主干的真实案件，必须提供至少一条标准调查路径：

```text
cases/<case_id>/scenarios/standard_path.yaml
```

它不是剧情正文，也不是新规则系统，而是案件作者承诺的一条“最小可解、可回放、可审计”的验收路径。测试和生成脚本都读取这一份 YAML，避免把标准路径硬编码在 Python 里。

## 顶层结构

当前 v0 使用扁平结构，和 `tests/utils/scenario_evaluation.py` 的 loader 保持一致：

```yaml
case_id: mist_clock_manor
expected_final_phase: resolved
expected_final_beats:
  - sedative_found
expected_final_player_world_info_ids:
  - sedative_wine
forbidden_public_terms:
  - Jiang replaced the medicine
steps:
  - name: inspect wine table unlocks sedative fact
    label: 检查酒桌
    action:
      type: inspect
      target_id: wine_table
    expected_events:
      - player.inspected
      - clue.discovered
      - player_knowledge.updated
    expected_phase: investigation
    expected_player_world_info_ids:
      - sedative_wine
    accepted: true
    director_blocked: false
    expected_new_awareness: []
    expected_block: null
reconstruction:
  overview:
    - 面向复盘文档的案件概览。
  runtime_note:
    - 面向复盘文档的运行时说明。
  director_note: Director 拦截说明。
  facts:
    - 面向复盘文档的事实重建条目。
```

必填字段：

- `case_id`
- `expected_final_phase`
- `expected_final_beats`
- `expected_final_player_world_info_ids`
- `forbidden_public_terms`
- `steps`

可选字段：

- `reconstruction`：只用于生成 `case_reconstruction.md`，不参与世界状态更新。
- `steps[].label`：中文展示名，只用于产物；断言仍使用 `steps[].name`。

## Step 协议

每个 `steps[]` 至少包含：

- `name`：稳定英文说明，用于测试失败定位。
- `label`：可选中文说明，用于生成复盘文档。
- `action`：结构化 `PlayerAction`。
- `expected_events`：本步新增 `WorldEvent.type` 顺序，必须精确一致。
- `expected_phase`：本步结束后的剧情阶段。
- `expected_player_world_info_ids`：本步结束后的玩家已知事实集合。
- `accepted`：本步是否被运行时接受。
- `director_blocked`：本步是否触发 Director 拦截。
- `expected_new_awareness`：本步新增的角色事实认知，可为空数组。
- `expected_block`：Director block 的审计字段；无拦截时为 `null`。

`expected_new_awareness` 使用对象数组：

```yaml
expected_new_awareness:
  - character_id: jiang_yanhui
    world_info_id: timed_lock_modified
```

`expected_block` 使用安全审计字段，不能写 private 原文：

```yaml
expected_block:
  target_id: jiang_yanhui
  blocked_fact_id: jiang_yanhui_mechanism
  world_info_id: heart_medicine_replaced
  matched_by: forbidden_term
  matched_text: "[redacted]"
  safe_fallback_used: true
```

## Action 协议

`action` 必须能无损映射到 `PlayerAction`。v0 支持当前运行时已有动作：

```yaml
action:
  type: inspect
  target_id: wine_table
```

```yaml
action:
  type: ask_about
  target_id: lin_qichi
  subject_type: clue
  subject_id: bitter_wine
  text: What about the wine?
```

```yaml
action:
  type: present_clue
  target_id: lin_qichi
  clue_id: bitter_wine
  text: Explain the bitter wine.
```

```yaml
action:
  type: accuse
  target_id: jiang_yanhui
  claim_id: shared_death_chain
  evidence_clue_ids:
    - bitter_wine
  text: The death was caused by a chain of actions.
```

`force_forbidden: true` 只能作为 Director block 探针使用，不应成为正常叙事依赖。

## 标准路径覆盖要求

`standard_path.yaml` 必须覆盖：

- 至少一次关键线索调查，证明 hotspot 能释放 `Clue` 和 `WorldInfo`。
- 至少一次 `ask_about` 或 `present_clue`，证明 NPC 认知只通过合法事件更新。
- 至少一次 Director block，证明阶段外剧透会被拦截且脱敏。
- 结案所需的全部 `required_evidence`。
- 结案所需的全部 `required_world_info`。
- 一次正式 `accuse`，由规则系统推进到 `resolved`。
- 完整事件 replay，并证明 replay 后状态一致。

这条路径不是唯一玩法，也不是攻略文档。它是生产验收底线：案件至少存在一条能被系统规则完整跑通的闭环。

## 安全边界

Scenario 文件不得：

- 新增事实、线索、角色、阶段或规则。
- 写入 private 原文、solution claim 内部解释或 forbidden fact 原文。
- 依赖真实 LLM 的随机输出。
- 让 LLM 修改 PlayerKnowledge、CharacterFactAwareness 或剧情阶段。
- 用自然语言替代结构化断言。

Scenario 只能引用案件包里已经存在的 ID，包括角色、线索、WorldInfo、phase、beat、claim 和 blocked fact。

## 当前落地文件

- `cases/mist_clock_manor/scenarios/standard_path.yaml`
- `tests/test_mist_clock_manor_scenario.py`
- `tests/test_standard_scenario_discovery.py`
- `tests/utils/scenario_evaluation.py`
- `app/scenarios/validation.py`
- `app/scenarios/validate.py`
- `scripts/generate_case_run.py`

## 验收命令

```powershell
py -3.12 -m app.scenarios.validate cases
py -3.12 -m pytest tests/test_standard_scenario_discovery.py -q
py -3.12 scripts\generate_case_run.py --all
```

`app.scenarios.validate` 负责协议和引用校验；自动发现测试负责真实运行路径；`generate_case_run.py --all` 负责批量生成可审查产物。
