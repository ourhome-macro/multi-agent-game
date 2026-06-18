# 真实 LLM 长跑链路快速摸底 - 2026-06-18

## 结论

项目主线不是“NPC 接一个 LLM 聊天”，而是事件溯源的悬疑叙事运行时。真实 LLM 只能产出结构化 `AgentIntent`，后续必须经过合同校验、Narrative Director 和 Rule Engine；世界状态、线索、关系、剧情阶段都不能由 LLM 直接写。

真实 LLM 长跑链路已经存在，历史上 `mist_clock_manor` 可以用真实 API 跑到 `resolved`。但当前真实 shadow drift 报告显示：稳定性没有达到上线门槛，根因集中在 schema/contract 不稳定、Director 拦截和 fallback。

## 真实长跑入口

- 端到端真实 API 长跑脚本：`scripts/run_mist_clock_manor_real_api.py`
- 真实 LLM 适配器：`app/agents/real_llm_agent.py`
- Agent 统一入口：`app/agents/gateway.py`
- Shadow / drift / redteam 评估入口：`app/evaluations/llm_shadow_eval.py`
- CLI 包装：`scripts/run_llm_shadow_eval.py`
- 案件标准路径：`cases/mist_clock_manor/scenarios/standard_path.yaml`

`scripts/run_mist_clock_manor_real_api.py` 会固定加载 `mist_clock_manor`，构造 27 步玩家路径，其中 21 步会进入 Agent turn。它显式设置：

- `LLM_BACKEND=real`
- `OPENAI_MODEL=<args.model>`
- `LLM_API_STYLE=<args.api_style>`

并使用 `OpenAILLMAgent.generate_strict(...)`，也就是失败直接暴露，不走静默安全兜底。

## 已有历史结果

历史文档显示真实 API 主线跑通过：

- `doc/agent-runtime-mvp/mist-clock-manor-real-api-run-20260606.md`
- `doc/agent-runtime-mvp/mist-clock-manor-real-api-branches-20260607.md`
- `doc/agent-runtime-mvp/real-api-contract-repair-hardening-20260607.md`

关键结果：

- 最终阶段：`resolved`
- 玩家步骤：`27`
- Agent turns：`21`
- 完成 beat：`sedative_found`、`mechanism_exposed`、`motive_chain_exposed`、`case_solved`
- Director block 是有效安全层，不是异常；历史主线约 4-5 次 block。

## 当前真实 Drift 风险

当前 `doc/case/mist_clock_manor/llm_shadow_drift_report.md` 是更有生产意义的信号：

- Backend：`real`
- Run count：`20`
- Total shadow calls：`80`
- State pollution：`0`
- State unchanged：`true`

但失败指标很硬：

- `runs_with_schema_failure = 7`
- `runs_with_director_block = 1`
- `runs_with_fallback = 8`
- `runs_with_speech_world_info_touch = 1`
- Step 6 漂移严重：20 次里 17 种变体，3 次 schema failure，1 次 Director block，4 次 fallback。
- Step 7 有 5 次 schema failure / fallback。

这说明状态边界守住了，但真实模型输出合同还不稳定。按当前 `drift --gate` 规则，这个结果不应放行生产。

## 关键配置坑

`.env` 里已有真实 API 相关键，但 shadow real 开关存在命名风险。

当前代码实际判断：

```text
LLM_SHADOW_EVAL=1
LLM_BACKEND=real
OPENAI_API_KEY=...
```

`.env` 里看到的是旧式键：

```text
LLM_SHADOW_EVAL_BACKEND
LLM_SHADOW_EVAL_ENABLE_REAL
```

代码只兼容 `LLM_SHADOW_EVAL_BACKEND=real` 作为 backend 选择，不读取 `LLM_SHADOW_EVAL_ENABLE_REAL` 作为启用开关。也就是说，如果没有显式设置 `LLM_SHADOW_EVAL=1`，即使传 `--backend real`，真实 shadow 也会被记录为 `skipped=shadow_eval_disabled`。

这个不是小问题。真实长跑和 shadow drift 的启动说明必须收敛到当前代码实际读取的环境变量，否则会出现“看起来跑 real，实际全跳过”的假验证。

## 当前架构判断

好的部分：

- LLM 没有状态写权限。
- `generate_strict`、本地合同校验、Director、Rule Engine 分层清楚。
- Shadow eval 明确保证状态零污染。
- 公共报告脱敏，不写玩家原文和 LLM 原文。
- 真实 drift 已经有 20-run 级别的稳定性观测。

硬问题：

- schema repair 仍依赖模型自我纠正，真实输出不够稳定。
- drift gate 指标已经证明当前真实 LLM 不能作为默认生产路径。
- `.env` shadow real 开关与代码实际读取不一致。
- 历史 real run 文档和当前 trace schema 已有差异，不能只看旧日志判断当前状态。
- context budget 历史上长期超过预算，虽然 compression 启用，但不能说明 prompt 尺寸真的受控。

## 建议下一步

先不要直接跑完整真实长跑刷成本。顺序应当是：

1. 本地跑 stub shadow / drift，确认 harness 没坏。
2. 修正或记录 `LLM_SHADOW_EVAL` 启用开关，避免假 real。
3. 先真实跑单步 `--step 6 --drift --runs 3`，因为 Step 6 是当前最大漂移点。
4. 修 Step 6 / Step 7 的 contract、safe fragment 或 prompt 约束后，再跑 `--runs 20 --gate`。
5. 只有 drift gate 过了，再跑 `scripts/run_mist_clock_manor_real_api.py` 的 27 步端到端真实长跑。

推荐验证命令：

```powershell
py -3.12 -m pytest tests\test_llm_shadow_eval.py -q

$env:LLM_SHADOW_EVAL="1"
$env:LLM_BACKEND="real"
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --backend real --drift --runs 3 --step 6 --gate
```

完整门槛命令：

```powershell
$env:LLM_SHADOW_EVAL="1"
$env:LLM_BACKEND="real"
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --backend real --drift --runs 20 --gate
```
