# 真实 LLM 长跑修复跟进 - 2026-06-18

## 当前结论

本轮没有把真实 LLM 长跑伪装成通过。代码侧已经修复真实 shadow 启用、safe fragment 合同投影、NPC Skill 安全片段白名单和 transient HTTP retry；但当前真实 provider 返回 `402 Payment Required`，阻断继续跑 `--runs 20 --gate` 和 27 步端到端长跑。

已验证：

- `py -3.12 -m pytest tests\test_real_llm_observability.py tests\test_npc_skills.py tests\test_director_generation_gateway.py tests\test_llm_shadow_eval.py -q`
- 结果：`48 passed`
- `py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --backend stub --suite --runs 2 --gate --summary-dir tmp\verify_stub_suite_final_20260618`
- 结果：suite passed

真实 Step 7 在 provider 402 前的改进信号：

- `deflect` 触碰 safe fragment 的模式错误已消失。
- 已出现自动补 `disclosure_claim` 的成功变体。
- 剩余真实验证被 `402 Payment Required` 阻断，不能继续用真实 API 得出稳定性结论。

## 本轮修复

- `LLM_SHADOW_EVAL_ENABLE_REAL` 作为旧真实 shadow 开关兼容读取；显式 `LLM_SHADOW_EVAL` 优先。
- 显式 `--backend real` 但真实 shadow 未启用时 fail fast，避免“看起来跑 real、实际全 skipped”的假验证。
- 增加 `--suite` 汇总 standard、redteam、safety benchmark、drift gate。
- 标准 drift 排除 `force_forbidden=true` 的对抗动作，对抗动作归 redteam/safety。
- `SafeFactFragmentProjection` 增加 `aliases` 和 `claim_patterns`。
- Narrative Director 允许已选中 NPC Skill 显式授权的 unlocked safe fragment 进入生成合同，但只开放白名单 fragment，不开放整条 `WorldInfo`。
- LLM contract 将授权 safe fragment 的 allowed modes 合并进对应 world_info 约束，并继续禁止 `full`。
- 真实 LLM 本地投影会为命中 safe fragment 的 speech 补 `disclosure_claim`，并把过低 mode 升级到 fragment 允许的 `partial` 或 `hint`。
- `mist_clock_manor` 补充了锁痕和红酒安全片段的中文 alias/pattern。
- OpenAI-compatible 请求对 408/429/5xx、timeout、transport error 做有限重试；402/400/422 不重试。

## 恢复真实 API 后必须跑

先不要直接跑 27 步长跑。恢复额度后按顺序执行：

```powershell
$env:LLM_SHADOW_EVAL="1"
$env:LLM_BACKEND="real"
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --backend real --drift --runs 3 --step 7 --gate
py -3.12 -m app.evaluations.llm_shadow_eval --case mist_clock_manor --backend real --drift --runs 20 --gate
py -3.12 scripts\run_mist_clock_manor_real_api.py
```

通过标准：

- drift 20-run：schema/provider fallback/director block/missing claim/state pollution 都为 0。
- 27 步真实长跑：能到 `resolved`，所有状态变化都有 `WorldEvent`，无 LLM 直接写状态，无未授权剧透。

## 第一版后端还差什么

暂不看前端时，第一版不是“能聊天”，而是后端能稳定支撑一个可回放悬疑案件。

必须完成：

1. 真实 LLM 20-run drift gate 和 27-step real API 长跑恢复通过，并把报告落入 `doc/case/mist_clock_manor/`。
2. PostgreSQL runtime 做一次从 session 创建到事件 replay 的完整验收，覆盖幂等冲突、并发版本冲突和事件投影恢复。
3. Raw text action intake 接入生产路径，保证自然语言先变成结构化 `PlayerAction`，歧义必须 clarification/rejected，不能猜。
4. 案件作者质量门槛固化：world_info safe fragment、forbidden inference、NPC skill safe refs、solution claims、narrative beats 全部进入 linter。
5. 关键剧情路径集成测试覆盖 `mist_clock_manor` 标准路径、偏离路径、错误指控、证据不足和重复提交。
6. 运行时观测闭环：每轮 Agent turn trace、Director block、Rule rejection、LLM fallback、token/context budget 都能关联 session/action/event。
7. 失败恢复策略明确：真实 LLM provider 失败只能安全 fallback 或返回可审计错误，不能产生状态副作用。

可以后置但不能遗忘：

- 多案件加载与迁移策略。
- 长期记忆检索质量评测。
- 后台管理/作者工具。
- 更完整的 redteam prompt injection 样本库。
- 性能压测和成本预算。

当前第一版最大阻塞不是前端，而是真实 LLM 稳定性门槛和生产 runtime 验收。真实 API 额度恢复前，不能宣称 real long-run 已解决。
