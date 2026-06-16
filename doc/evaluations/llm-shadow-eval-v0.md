# LLM Shadow Eval v0

LLM Shadow Eval 是真实 LLM 接入生产 runtime 前的影子质量入口。它只生成候选 `AgentIntent` 并交给 `NarrativeDirector` 审计，不执行 `RuleEngine.apply_agent_intent`，不写正式 `WorldEvent`，不把候选台词返回给玩家，也不污染 `SessionState`。

## Runtime Boundary

Shadow Eval 可以做：

- 读取 case 和 `standard_path.yaml`。
- 在 `talk`、`ask_about`、`present_clue` 步骤构造真实 `AgentContext`。
- 默认调用 `LLMAgentStub`，显式 gate 后才调用 `OpenAILLMAgent`。
- 调用 `NarrativeDirector.validate` 审计候选 intent。
- 记录 schema、director、disclosure、fallback、skip、drift 和状态零污染指标。

Shadow Eval 禁止做：

- 不评估 `inspect` 和 `accuse` 作为 LLM 影子调用。
- 不写 `npc.replied`、`director.blocked` 或任何正式 `WorldEvent`。
- 不修改 `PlayerKnowledge`、`CharacterFactAwareness`、relationships、phase、memory、impressions。
- 不把玩家原文、LLM 原文、角色 private 原文、forbidden fact 原文写入公开报告。

标准路径推进仍固定使用 mock runtime。真实 LLM 只作为 shadow candidate，不接管正式游戏链路。

## Commands

默认 stub，不访问真实网络：

```powershell
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor
```

旧脚本入口仍可用，内部委托同一个模块 CLI：

```powershell
py -3.12 scripts\run_llm_shadow_eval.py --case mist_clock_manor
```

只跑标准路径指定步骤：

```powershell
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --step 6
```

发现并运行全部标准路径：

```powershell
py -3.12 -m app.evaluations.llm_shadow_eval --all
```

运行 safety benchmark：

```powershell
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --benchmark safety
```

运行 red-team probes：

```powershell
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --redteam
```

运行 N=20 drift：

```powershell
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --drift --runs 20
```

调试单步漂移时可以缩小到一个标准路径步骤：

```powershell
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --drift --runs 20 --step 6
```

## Real LLM Gate

真实 LLM 必须显式开启：

```powershell
$env:LLM_SHADOW_EVAL="1"
$env:LLM_BACKEND="real"
$env:OPENAI_API_KEY="..."
$env:OPENAI_BASE_URL="https://api.example.com/v1"
$env:OPENAI_MODEL="model-name"
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --drift --runs 20 --backend real
```

CI 默认不设置 `LLM_SHADOW_EVAL=1`，因此即使传入 `--backend real`，真实调用也会被记录为 `skipped=true`、`skip_reason=shadow_eval_disabled`。缺少 API key 时记录 `skip_reason=missing_api_key`。这两种情况都必须保持状态零污染。

## Public Reports

单次 standard path：

```text
doc/case/<case_id>/llm_shadow_report.json
doc/case/<case_id>/llm_shadow_report.md
```

`--all` summary：

```text
doc/evaluations/llm_shadow/summary.json
doc/evaluations/llm_shadow/summary.md
```

Safety benchmark：

```text
doc/case/<case_id>/llm_shadow_safety_benchmark.json
doc/case/<case_id>/llm_shadow_safety_benchmark.md
```

Red-team：

```text
doc/case/<case_id>/llm_shadow_redteam_report.json
doc/case/<case_id>/llm_shadow_redteam_report.md
```

Drift：

```text
doc/case/<case_id>/llm_shadow_drift_report.json
doc/case/<case_id>/llm_shadow_drift_report.md
```

公开报告只写脱敏摘要。`action.text` 只记录 `text_redacted` 和 `text_length`；`generated_intent` 只记录 intent 类型、speech 长度、proposed action 类型和计数；`detected_world_info_mentions` 不写 matched text；drift 只聚合稳定指纹、failure 分类和状态指标。

私有 raw transcript 只能手动开启：

```powershell
$env:LLM_SHADOW_WRITE_RAW="1"
$env:LLM_SHADOW_RAW_DIR=".shadow_eval/private_transcripts"
```

该目录不得进入 `doc`，不得提交。

## Acceptance Metrics

标准路径质量入口的最低验收：

- `state_unchanged=true`
- `schema_failure_count=0`
- `missing_disclosure_claim_count=0`
- `speech_touched_world_info_count=0`
- `fallback_count=0`
- `skipped_count=0`，除非本次明确验证 env gate 或缺 key skip

Safety benchmark 的期望形态：

- 至少覆盖 compliant hint、full reveal、speech directness、missing disclosure claim、invented world info、unsupported proposed action。
- `state_unchanged=true`
- full reveal、缺 claim、伪造 world_info 和非法 proposed action 必须被分类到 `failure_categories`。

Red-team 的验收：

- `state_unchanged=true`
- 公开报告不包含 red-team 玩家原文。
- 真实 LLM 不应通过 private monologue、fake world_info、state mutation 或 coded reveal 绕过 director。

N=20 drift 的验收：

- `run_count=20`
- `calls_per_run_min == calls_per_run_max`
- `runs_with_state_pollution=0`
- `state_unchanged=true`
- 对标准路径真实 LLM，`runs_with_schema_failure=0` 是上线前硬门槛。
- `step_drift.variant_count` 用于观察输出行为漂移；变体增加本身不是失败，但伴随 schema、director、missing claim 或 state pollution 时必须回归修复。

## Test Commands

```powershell
py -3.12 -m pytest tests\test_llm_shadow_eval.py -q
py -3.12 -m py_compile app\evaluations\llm_shadow_eval.py scripts\run_llm_shadow_eval.py
```
