# Mist Clock Manor Real API Full Run - 2026-06-18

## 结论

`mist_clock_manor` 已用 DeepSeek `deepseek-v4-flash` 跑完整 27-step real API 长链路，并推进到 `resolved`。

这次不是 shadow drift。脚本执行了真实 runtime 链路：玩家动作写入、Agent turn、Director 后置审计、Rule Engine 状态变化、事件日志、错误指控和正确结案指控。

## 最终通过数据

命令参数：

```powershell
$env:OPENAI_BASE_URL="https://api.deepseek.com"
$env:OPENAI_MODEL="deepseek-v4-flash"
$env:LLM_API_STYLE="chat_completions"
$env:LLM_TIMEOUT_SECONDS="45"
$env:LLM_HTTP_RETRY_ATTEMPTS="2"
py -3.12 scripts\run_mist_clock_manor_real_api.py --model deepseek-v4-flash --api-style chat_completions --timeout-seconds 45 --schema-repair-attempts 1
```

结果摘要：

- `FINAL_PHASE=resolved`
- 总步骤：27
- 实际 Agent turns：19
- `director_blocked=0`
- `llm_fallback_used=0`
- `schema_error=0`
- trace status：`ok=19`
- inspect steps：6
- accuse steps：2
- 所有 27 步都有事件输出，`empty_event_lines=0`
- `EVENT_COUNT=175`
- completed beats：`sedative_found`, `mechanism_exposed`, `motive_chain_exposed`, `case_solved`
- discovered clues：`bitter_wine`, `burned_confession`, `cut_power_trace`, `delayed_lock_marks`, `echo_tape`, `empty_capsules`, `ruolan_voice_tape`

日志位置：

- `logs/mist_clock_manor_real_api_20260618_deepseek_full_run_after_director_skill_only.jsonl`
- `logs/mist_clock_manor_real_api_20260618_deepseek_full_run_after_director_skill_only.log`
- `tmp/mist_clock_manor_real_api_20260618_deepseek_full_run_after_director_skill_only.out`

这些日志包含真实 NPC speech，仅作为本地调试产物，不复制进公开报告正文。

## 长跑暴露并修复的问题

第一次完整长跑能结案，但中途有 6 个 Director block，不能算 v1 稳定性通过。暴露的问题是长链路上下文累计后的授权口径不一致：

- `jiang_lock_boundary` 把已解锁锁痕 safe fragment 压成 `hint`，真实模型容易直接说出“有延时/改动痕迹”这一证据片段，Director 会按 direct claim 拦截。
- `jiang_ruolan_recording_exists` 和 `heart_medicine_replaced` 的 safe fragment 缺中文 alias/pattern，中文输出命中了 world_info alias，却没有命中 safe fragment projection，导致漏补 `disclosure_claim`。
- reconstruction 阶段的沈照夜 skill 通过 `director_safe_fragments` 授权了跨事实链条片段，但 LLM contract 和 Director validate 原本只为角色自身 `FactDisclosureStrategy` 生成 allowed constraint，skill-only fragment 会出现“有 fragment、无 world_info constraint”的错位。

本轮修复：

- 为若岚旧录音和空胶囊 safe fragment 补中文 alias/pattern。
- 将江雁回锁痕/胶囊证据 skill 的 `max_mode` 提到 `partial`，仍不允许 `full`。
- 新增 `jiang_ruolan_tape_boundary`，让江雁回在玩家已发现若岚录音后可以有限讨论该片段。
- 新增 `shen_reconstruction_chain_boundary`，只在 reconstruction 且关键证据齐备后，允许沈照夜有限串联镇静剂、门锁、录音、空胶囊和断电的 safe fragments。
- `build_llm_agent_input(...)` 为 skill-only safe fragments 生成受限 `LLMDisclosureConstraint`。
- `NarrativeDirector.validate(...)` 后置审计也为 skill-only safe fragments 构造同等受限约束视图。

## 口径说明

用户原始门槛提到“21 个 Agent turn”。当前 `scripts/run_mist_clock_manor_real_api.py` 实际包含：

- 27 个总步骤
- 6 个 `inspect`
- 2 个 `accuse`
- 19 个 `talk/ask_about/present_clue` dialogue steps

因此当前脚本的真实 Agent turn 数是 19，不是 21。若 v1 门槛必须严格要求 21 个 Agent turn，需要先扩展脚本步骤；以当前脚本为准，本次 19/19 Agent turns 全部合法。

## 当前判断

按当前脚本口径，v1 的 LLM 稳定性门槛已经通过：

- drift 20-run 已通过。
- 完整 real API 长链路已到 `resolved`。
- 全部真实 Agent turns 无 schema error、无 fallback、无 Director block。
- inspect、accuse、phase change、clue/player knowledge 更新和结案都产生了事件输出。

下一块不属于 LLM 稳定性本身，而是生产 runtime 验收：PostgreSQL 持久化、replay、幂等、并发版本冲突和失败恢复。
