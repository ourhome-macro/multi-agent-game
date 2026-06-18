# 真实 LLM DeepSeek Gate 跟进 - 2026-06-18

## 结论

DeepSeek OpenAI-compatible provider 已通过 `mist_clock_manor` 标准路径真实 shadow 20-run drift gate。

本次通过不是把失败降级为忽略，而是修掉了两个真实长跑暴露的问题：

- 本地 LLM contract 曾把普通证据 ref 当成 safe fragment 引用，导致本地校验放行、Director 后置拦截。
- 真实 provider 请求超时硬编码为 20 秒，DeepSeek 长跑中会把慢响应放大成 fallback 失败。

## 已验证结果

真实 DeepSeek 20-run：

```powershell
$env:OPENAI_BASE_URL="https://api.deepseek.com"
$env:OPENAI_MODEL="deepseek-v4-flash"
$env:LLM_API_STYLE="chat_completions"
$env:LLM_TIMEOUT_SECONDS="45"
$env:LLM_HTTP_RETRY_ATTEMPTS="2"
$env:LLM_SHADOW_EVAL="1"
$env:LLM_BACKEND="real"
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --backend real --drift --runs 20 --gate
```

结果：

- `run_count=20`
- `total_shadow_calls=60`
- `calls_per_run_min=3`
- `calls_per_run_max=3`
- `runs_with_schema_failure=0`
- `runs_with_director_block=0`
- `runs_with_missing_disclosure_claim=0`
- `runs_with_speech_world_info_touch=0`
- `runs_with_fallback=0`
- `runs_with_skips=0`
- `runs_with_state_pollution=0`
- `state_unchanged=true`

公开脱敏报告：

- `doc/case/mist_clock_manor/llm_shadow_drift_deepseek_20260618.json`
- `doc/case/mist_clock_manor/llm_shadow_drift_deepseek_20260618.md`

## 本轮修复

- `LLMDisclosureConstraint.safe_fact_refs` 中的普通证据 ref 不再被本地 contract 当作 safe fragment 引用。
- partial safe fragment claim 必须引用 fragment ref、fragment id 变体或 fragment source refs。
- 真实 LLM 投影层遇到“claim 已存在但 refs 只指向普通证据”的情况，会保留普通证据 ref，并追加唯一授权 safe fragment ref。
- 新增 `LLM_TIMEOUT_SECONDS`，默认 20 秒，真实长跑可按 provider 稳定性显式提高。
- DeepSeek 长跑使用 45 秒单次请求超时和 2 次瞬时错误重试。

## 当前第一版后端剩余门槛

暂不看前端时，第一版后端还不能只靠本次 20-run 宣称完成。还必须补齐：

1. 27-step real API 长跑：覆盖完整案件推进到 `resolved`，验证所有真实状态变化都有 `WorldEvent`，且无 LLM 直接写状态。
2. PostgreSQL runtime 验收：从 session 创建、动作处理、事件写入到 replay 全链路跑通，并覆盖幂等、版本冲突和恢复。
3. Raw text action intake：自然语言输入必须先稳定转成结构化 `PlayerAction`，歧义走 clarification/rejected，不允许猜。
4. 案件包 linter：world_info safe fragment、forbidden inference、NPC skill safe refs、solution claims、beats 条件必须机器校验。
5. 关键剧情集成测试：标准路径、偏离路径、错误指控、证据不足、重复提交都要有可预测结果。
6. 运行时观测闭环：每轮 action、Agent turn、Director block、Rule rejection、LLM fallback、token/context budget 必须能关联 session/action/event。
7. 失败恢复策略：真实 LLM provider 失败只能产生可审计 fallback 或错误响应，不能产生状态副作用。

当前最大进展是：真实 LLM shadow 20-run gate 已从阻塞项变成已通过项。下一块硬门槛是 27-step real API 长跑和生产 runtime 验收。
