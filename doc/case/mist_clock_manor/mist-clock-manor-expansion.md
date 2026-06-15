# 雾钟山庄案件扩写记录

日期：2026-06-14

## 目标

本次扩写只加厚 `cases/mist_clock_manor` 的证据密度和旧案氛围，不改变主线结论：

- 保留四人各推动一枚齿轮的共同因果结构。
- 保留镇静剂、录音刺激、延时门锁、空胶囊、停电叠加的死亡链。
- 保留 `shared_death_chain` 作为标准路径正确指控。
- 新增证据不作为标准路径必需条件，避免破坏 scenario 精确回归。

## 场景与热点

新增可选场景：

- `clock_tower`：钟楼，服务停电、钟声、备用线路、齿轮维护的物证厚度。
- `gallery`：画廊，服务江若岚旧案、陆澜生改写叙事和动机压力。

书房新增可选 hotspot：

- `desk_embossed_pages`：释放 `lock_test_scrap`、`trust_indent_page`。
- `medicine_drawer_liner`：释放 `capsule_powder_on_liner`、`sedative_bottle_label`。
- `editing_lamp`：释放 `tape_splice_mark`。
- `pocket_watch`：释放 `pocket_watch_offset`。

这些 hotspot 不在 `scenarios/standard_path.yaml` 的 action 中，因此不会改变标准路径的事件序列、阶段推进或玩家已知集合。

## 新增线索层级

证据厚度层：

- `backup_timer` -> `backup_timer_kept_recorder_power`
- `breaker_sequence_tag` -> `power_cut_was_prepared`
- `fresh_gear_oil` -> `clock_tower_serviced_before_death`
- `muted_bell_hammer` -> `real_bell_was_muted`
- `lock_test_scrap` -> `lock_delay_tested`
- `trust_indent_page` -> `trust_terms_pressured_guests`
- `capsule_powder_on_liner` -> `capsule_powder_removed`
- `sedative_bottle_label` -> `sedative_source_matches_wine`
- `tape_splice_mark` -> `tape_was_edited_twice`
- `pocket_watch_offset` -> `fake_chime_confused_death_time`

氛围与旧案层：

- `covered_ruolan_photo` -> `ruolan_erased_from_archive`
- `altered_gallery_plaque` -> `ruolan_credit_rewritten`
- `lake_death_clipping` -> `old_lake_report_inconsistent`
- `incomplete_evidence_box` -> `old_case_file_incomplete`
- `gallery_mud_trace` -> `lake_mud_trace_recent`
- `missing_visitor_log_page` -> `manor_log_page_removed`

## 指控与误导

`shared_death_chain.required_evidence` 和 `required_world_info` 保持不变，标准路径仍只要求原六条核心证据。

新增两个错误单因指控用于表达反证关系：

- `qi_tape_single_cause`：录音链足以说明声音刺激和剪接复杂性，但不足以单独解释死亡。
- `shen_power_single_cause`：断电链足以说明时序和设备异常，但不足以单独解释死亡。

## Agent 与记忆

新增 mock 回复只覆盖可选线索的克制反应，不直接输出 `WorldInfo.title`、`aliases` 或 `claim_patterns` 中可触发直接披露审计的文本。

新增两条可选 memory derivation rule：

- `memory_rule.qi_tape_splice_pressure.asked_about.v1`
- `memory_rule.jiang_lock_test_pressure.presented_clue.v1`

它们只在玩家询问或展示新增线索时触发，不影响标准路径现有 `empty_capsules` typed memory 测试。

## 泄露边界

`StateSummary` 会公开：

- discovered clue 的 `title` / `description`
- player knowledge 的 `WorldInfo.title` / `WorldInfo.description`

因此新增公开文本只描述可观察痕迹和可审计物证推断，不写以下内容：

- 最终共同责任链的完整结论。
- 某 NPC 的 private summary 原文。
- forbidden fact 的 blocked terms 原文组合。
- “谁独立杀人”式定罪文本。

现有 `forbidden_facts.yaml` 继续保护 `shared_death_chain`、`jiang_yanhui_mechanism`、`shen_power_cut` 三类阶段外禁说事实。

## 回归范围

变更后至少需要运行：

- `pytest tests/test_mist_clock_manor_scenario.py`
- `pytest tests/test_standard_scenario_discovery.py`
- `pytest tests/test_mist_clock_manor_memory_boundaries.py`
- `pytest tests/test_typed_memory.py`
- 与 loader、router、forbidden/private leak 相关的 `mist_clock_manor` 测试

若标准路径失败，优先检查：

- 是否误把新线索挂到标准路径已有 hotspot。
- `expected_events` 是否因新增自动发现发生漂移。
- `expected_player_world_info_ids` 是否多出新 `WorldInfo`。
- 新 mock 回复是否命中 `WorldInfo` 直接披露审计但没有 disclosure claim。
