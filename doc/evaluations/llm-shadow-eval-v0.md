# LLM Shadow Eval v0

LLM Shadow Eval v0 是真实 LLM 的影子评测链路，不是正式 runtime 输出链路。正式游戏仍由 `MockAgent` 和规则系统生成可回放状态；真实 LLM 只生成候选 `AgentIntent`，随后由 `NarrativeDirector` 审计。

## 边界

Shadow Eval 只做：

- 读取 case 和 `standard_path.yaml`。
- 在 `talk`、`ask_about`、`present_clue` 步骤构造真实 `AgentContext`。
- 调用 `LLMAgentStub` 或显式启用的 `OpenAILLMAgent` 生成候选 intent。
- 调用 `NarrativeDirector.validate` 审计候选 intent。
- 记录 schema、Director、disclosure 和状态零污染结果。

Shadow Eval 不做：

- 不评估 `inspect` 和 `accuse`。
- 不调用 `RuleEngine.apply_agent_intent`。
- 不写 `npc.replied`、`director.blocked` 或任何正式 `WorldEvent`。
- 不修改 `PlayerKnowledge`、`CharacterFactAwareness`、relationships、phase、memory、impressions。
- 不把 shadow speech 返回给玩家。
- 不污染 scenario snapshot 或 replay。

即使真实评测进程设置了 `LLM_BACKEND=real`，Shadow Eval 推进标准剧情路径时也固定使用 `MockAgent`。真实 LLM 只用于 shadow candidate，不能接管正式路径。

## 命令

默认使用 stub，不访问真实 API：

```powershell
py -3.12 scripts\run_llm_shadow_eval.py --case mist_clock_manor
```

只评测指定标准路径步骤：

```powershell
py -3.12 scripts\run_llm_shadow_eval.py --case mist_clock_manor --step 6
```

发现并运行所有标准路径：

```powershell
py -3.12 scripts\run_llm_shadow_eval.py --all
```

## 真实 LLM 手动开启

真实 LLM 必须显式开启：

```powershell
$env:LLM_SHADOW_EVAL="1"
$env:LLM_BACKEND="real"
$env:OPENAI_API_KEY="..."
$env:OPENAI_BASE_URL="https://api.xiaomimimo.com/v1"
$env:OPENAI_MODEL="mimo-v2.5"
py -3.12 scripts\run_llm_shadow_eval.py --case mist_clock_manor
```

当前小米 API 适配使用 OpenAI-compatible base URL。适配器会先尝试 `/responses`；如果兼容服务明确不支持，会降级到 `/chat/completions`。`mimo-v2.5` 是本轮真实 shadow eval 验证过的模型。

没有 API key 时，真实 LLM shadow step 会被记录为 `skipped=true`、`skip_reason=missing_api_key`，普通测试和 CI 不失败。CI 默认不设置 `LLM_SHADOW_EVAL=1`，因此不会调用真实 API。

## 报告

单 case 输出：

```text
doc/case/<case_id>/llm_shadow_report.json
doc/case/<case_id>/llm_shadow_report.md
```

`--all` 额外输出：

```text
doc/evaluations/llm_shadow/summary.json
doc/evaluations/llm_shadow/summary.md
```

报告统计包含：

- `total_shadow_calls`
- `schema_failure_count`
- `director_block_count`
- `missing_disclosure_claim_count`
- `speech_touched_world_info_count`
- `mode_violation_count`
- `full_reveal_block_count`
- `fallback_count`
- `skipped_count`
- `state_unchanged`

每个 step 摘要包含：

- `case_id`
- `scenario_path`
- `scenario_id`
- `step_index`
- `action_type`
- `target_id`
- `current_phase`
- `llm_backend`
- `llm_success`
- `schema_valid`
- `director_allowed`
- `director_blocked`
- `block_reason`
- `rejected_world_info_ids`
- `disclosure_claim_count`
- `missing_disclosure_claim`
- `speech_touched_world_info`
- `fallback_used`
- `state_unchanged`
- `event_count_before`
- `event_count_after`
- `latency_ms`

## 敏感信息

默认报告不写 raw speech，不写玩家 action 自由文本，不写 private 原文，不写 forbidden fact 原文，不写 solution claim 原文。

`action.text` 只记录 `text_redacted` 和 `text_length`。`generated_intent` 只记录 intent 类型、speech 长度、proposal 数量、memory ref 数量和 disclosure claim 数量。`disclosure_claims` 只记录 `world_info_id`、`mode`、`tactic` 和引用数量，不写引用原文。

如果未来需要保存 raw speech，只能使用显式调试开关写入本地 ignored 目录 `.shadow_eval/`，不能进入 `doc` 产物。

## 状态零污染

每个 shadow step 都记录：

- `event_count_before`
- `event_count_after`
- `state_unchanged`

状态指纹覆盖 `StateSummary`、narrative、relationships、relationship thresholds、discovered clues、player knowledge、character fact awareness、memory candidates、memory snapshots、character impressions 和 event log。

Shadow Eval 会在复制的 `SessionState` 上临时应用玩家事件来构造真实 `AgentContext`，但候选 LLM 输出和 Director 审计不会写回主 session。

## 本轮真实 API 测试记录

测试时间：2026-06-01。

配置：

- `LLM_SHADOW_EVAL=1`
- `LLM_BACKEND=real`
- `OPENAI_BASE_URL=https://api.xiaomimimo.com/v1`
- `OPENAI_MODEL=mimo-v2.5`
- API key 来自本地 `.env`，不写入公开报告。

过程记录：

- 初始 `/responses` 请求返回 404，确认该兼容服务不支持 Responses API。
- 降级到 `/chat/completions` 后，默认 `gpt-4.1-mini` 返回 400，根因是模型不存在于该服务。
- 查询 `/models` 后确认可用模型包含 `mimo-v2.5`。
- 使用 `mimo-v2.5` 后，模型可返回 JSON；进一步收紧输出合同后，`mist_clock_manor` 单案和 `--all` 均稳定生成报告。

最终 `--all` 指标：

- `total_shadow_calls=4`
- `schema_failure_count=0`
- `director_block_count=0`
- `missing_disclosure_claim_count=0`
- `speech_touched_world_info_count=0`
- `fallback_count=0`
- `state_unchanged=true`

报告文件：

- `doc/case/mist_clock_manor/llm_shadow_report.json`
- `doc/case/mist_clock_manor/llm_shadow_report.md`
- `doc/evaluations/llm_shadow/summary.json`
- `doc/evaluations/llm_shadow/summary.md`
