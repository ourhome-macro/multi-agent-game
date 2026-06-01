# Scenario Runner 与 CI 验收标准 v0

## 定位

这份文档定义文件化 Scenario 如何被通用 runner 执行、生成哪些产物、CI 按什么顺序验收，以及为什么必须在接真实 LLM 前完成这一步。

一句话：先用确定性的标准路径证明案件包、规则系统、Director、事件日志和 replay 都稳定，再让真实 LLM 进入表达层。反过来做，只会把规则缺陷、泄密缺陷和 LLM 随机性混在一起。

## 当前问题

当前剧情级测试已经证明了 harness 的方向，但如果标准路径长期硬编码在测试或专用脚本里，会留下三个生产风险：

- 案件作者看不到完整验收协议，只能读测试代码猜路径。
- 新案件会复制 Python 断言，导致内容配置和测试实现耦合。
- CI 失败时难以判断是案件文件错、Scenario 协议错、runner 错，还是运行时规则错。

最优解不是继续写更多专用测试，而是让 `cases/<case_id>/scenarios/standard_path.yaml` 成为输入协议，让测试和脚本只负责执行协议。

## 通用 Runner 契约

通用 runner 的输入：

```text
case_dir: cases/<case_id>
scenario_file: cases/<case_id>/scenarios/standard_path.yaml
artifact_dir: doc/case/<case_id> 或 CI 临时目录
llm_mode: mock
strict: true
```

通用 runner 的执行顺序：

```text
load case package
validate scenario schema
validate scenario references
create runtime
create session
execute steps in order
assert each step
assert global invariants after each step
run replay_events
compare replay state
run LLM fallback no-pollution check
run leak audit
write artifacts
return non-zero on any mismatch
```

当前落地入口：

```powershell
py -3.12 -m app.scenarios.validate cases
py -3.12 -m pytest tests/test_standard_scenario_discovery.py -q
py -3.12 scripts\generate_case_run.py --all
```

runner 必须保持确定性：

- 默认不调用真实 LLM。
- 不允许从 LLM 文本反推世界状态。
- 不允许跳过 Rule Engine 写状态。
- 不允许把 Scenario 当脚本执行。
- 不允许在断言失败后继续生成“看起来成功”的复盘。

现有 `tests/utils/scenario_evaluation.py` 是 in-process harness；`scripts/generate_case_run.py` 是通用产物生成器。二者都读取 `cases/<case_id>/scenarios/standard_path.yaml`，不再为每个案件复制一套路径代码。

## 每步验收

runner 对每个 step 至少验收：

- `ActionResponse.accepted` 与 Scenario 一致。
- `ActionResponse.director_blocked` 与 Scenario 一致。
- 本步新增 `WorldEvent.type` 顺序精确一致。
- 本步结束后的 `narrative.phase` 一致。
- 本步结束后的玩家已知 `world_info_id` 集合一致。
- 本步新增 `character_fact_awareness.updated` 只发生在预期角色和预期事实上。
- 如果发生 `director.blocked`，payload 字段完整且 `matched_text` 已脱敏。
- 如果 Scenario 声明 `forbidden_event_types`，本步不得出现这些事件。

这一步的关键不是“跑过流程”，而是证明状态变化只能来自合法事件链。

## 全局不变量

runner 每步后都应检查：

- `PlayerKnowledge` 只引用案件包真实存在的 `WorldInfo`。
- `PlayerKnowledge.knowledge_id` 格式为 `player_knowledge.<world_info_id>`。
- `narrative.phase.changed` 只能由 `rule_trigger_system` 写入。
- `rule.rejected` 只能由 `rule_engine` 写入。
- `npc.replied` 或 `director.blocked` 中的 `disclosure_claims` 必须能被当前 NPC 的 `FactDisclosureStrategy` 审计。
- `StateSummary`、action response 和生成产物不得泄露 private 原文、forbidden terms、`forbidden_facts`、`solution_claims` 或 `inner_context`。

如果这些不变量失败，不应靠改 prompt 兜底，应该回到运行时规则、案件配置或 Director 审计边界修根因。

## 生成产物

runner 应至少生成两个产物：

```text
standard_run.json
case_reconstruction.md
```

推荐目录：

```text
doc/case/<case_id>/
```

CI 中可以写入临时目录，但产物结构应保持一致。

### standard_run.json

机器可读，供 CI、回放和差异审查使用。至少包含：

- `case_id`、`scenario_id`、`generated_at`。
- 每步 `action`、`accepted`、`director_blocked`、`phase_after`。
- 每步新增 `new_event_types`。
- 每步新增 `new_events`。
- 每步后 `known_world_info_after`。
- 最终 `final_state_summary`。
- 最终 `final_player_knowledge`。
- 最终 `final_character_fact_awareness`。
- `completed_beats`。
- 完整 `event_log`。
- `replay_check`。
- `leak_check`。
- `fallback_check`。

### case_reconstruction.md

人类可读，供案件作者、策划和代码审查人确认剧情闭环。至少包含：

- 案件概览。
- 标准调查路径逐步复盘。
- 玩家最终已知事实。
- NPC 认知变化摘要。
- Director block 审计摘要。
- replay 结果。
- fallback 不污染结论。
- 未泄露项说明。

这份 Markdown 不是玩家攻略，不应暴露 private 原文或 forbidden 原文。

### 可选产物

后续可增加：

- `event_log.jsonl`：逐事件审计。
- `replay_check.json`：replay 差异专用文件。
- `leak_audit.json`：泄露扫描命中与脱敏结果。
- `failure_report.md`：CI 失败时的最小定位报告。

可选产物不能替代 `standard_run.json` 和 `case_reconstruction.md`。

## CI 验收顺序

建议 CI 按从便宜到昂贵、从协议到全量的顺序执行：

```powershell
py -3.12 -m app.cases.validate cases
```

第一步先做案件包字段和引用校验。这里失败，说明案件本体还不是合法输入。

```powershell
py -3.12 -m pytest tests/test_mist_clock_manor_scenario.py -q
```

当前真实样例案件测试已读取 `cases/mist_clock_manor/scenarios/standard_path.yaml`，而不是在测试里硬编码路径。

```powershell
py -3.12 -m pytest tests/test_standard_scenario_discovery.py -q
```

这一步会自动发现所有 `cases/*/scenarios/standard_path.yaml`，逐个执行 `ScenarioEvaluationHarness`，并做 replay、泄露边界和 fallback no-pollution 验收。新增真实案件后，只要放入标准路径 YAML，就会自动进入回归网。

```powershell
py -3.12 -m pytest tests/test_scenario_evaluation_harness.py -q
```

再验收通用 harness 在假案件上的边界行为，防止只对真实样例路径“刚好可用”。

```powershell
py -3.12 -m pytest -q
```

最后跑全量测试，确认本轮没有破坏运行时其他能力。

```powershell
py -3.12 -m ruff check app tests scripts
```

代码质量检查放在全量测试后或并行阶段均可，但不得替代剧情级验收。

通用 runner 当前命令：

```powershell
py -3.12 scripts\generate_case_run.py --case-id mist_clock_manor
```

批量生成所有标准路径产物：

```powershell
py -3.12 scripts\generate_case_run.py --all
```

兼容旧入口：

```powershell
py -3.12 scripts\generate_mist_clock_manor_run.py
```

两者都读取 `cases/mist_clock_manor/scenarios/standard_path.yaml`，并输出到 `doc/case/mist_clock_manor/`。

## CI 必须失败的情况

出现任一情况，CI 必须失败：

- `standard_path.yaml` 缺失。
- Scenario schema 不合法。
- Scenario 引用不存在的角色、线索、事实、阶段、beat 或 claim。
- 任一步事件顺序不一致。
- 玩家已知 `WorldInfo` 超出预期或缺失。
- NPC 认知更新发生在错误角色或错误事实上。
- Director block 没触发、payload 不完整或 `matched_text` 未脱敏。
- block 步骤同时产生 `npc.replied`。
- 最终 phase 不是 `resolved`。
- replay 后关键状态不一致。
- fallback 写入事件、改变状态或产生 `proposed_actions`。
- 公开输出泄露 private、forbidden、solution 内部信息或 inner context。

这些失败都不是“测试太严格”，而是生产可回放叙事系统的状态边界失败。

## 为什么必须在真实 LLM 前做

真实 LLM 接入前先做 Scenario 文件化和 runner 验收，原因很直接：

- **隔离变量**：先证明规则、事件、Director 和 replay 稳定，再评估 LLM 表达质量。
- **防止幻觉掩盖缺陷**：LLM 可能把缺失线索说圆，但系统状态仍然是错的。
- **防止剧透扩散**：真实 LLM 会改写、联想和扩展文本，必须先有可审计的 forbidden 边界。
- **降低回归成本**：文件化 Scenario 能让每个案件以同一 runner 验收，不必复制测试代码。
- **保护状态一致性**：LLM 只能输出表达和意图，不能成为世界状态、线索状态或剧情阶段来源。
- **稳定 CI**：真实 LLM 有延迟、成本和随机性，不能作为基础验收的前置条件。

接真实 LLM 的正确顺序是：

```text
Case YAML 合法
standard_path.yaml 合法
mock runner resolved
Director block 可审计
replay 一致
fallback 不污染
公开输出不泄露
再接真实 LLM
```

任何跳过前面步骤直接接 LLM 的方案，本质上是在用生成效果掩盖状态系统没有闭环。

## 完成定义

Scenario runner 与 CI 验收完成，必须满足：

```text
每个真实案件有 cases/<case_id>/scenarios/standard_path.yaml
通用 runner 能读取 Scenario 并执行完整路径
runner 产出 standard_run.json
runner 产出 case_reconstruction.md
CI 先验案件包，再验 Scenario，再跑全量测试
CI 不调用真实 LLM
任何状态、泄露、replay、fallback 失败都会阻断合入
```

达到这个标准后，真实 LLM 接入才有稳定地基；否则 LLM 只是把不可审计的系统风险包装成更流畅的台词。
