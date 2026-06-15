# 真实 LLM 可观测性

日期：2026-06-15

## 目标

真实 LLM 失败不能静默 fallback。生产链路必须区分网络错误、超时、JSON 错误、schema 错误、策略违规和 private 泄漏，并让 trace/API 返回脱敏摘要。

## 当前实现

`OpenAILLMAgent.generate(...)` 会把失败转换为安全 `AgentIntent`：

- `speech`：安全拒答
- `proposed_actions`：空
- `llm_error`：机器可读错误摘要

错误类型：

- `network_error`
- `timeout`
- `invalid_json`
- `schema_error`
- `policy_violation`
- `private_leak_detected`
- `configuration_error`
- `unknown_error`

`RuntimeTracer` 写入：

- `llm_fallback_used`
- `llm_error_type`
- `llm_error_message_sanitized`
- `schema_validation_errors`

`ActionResponse` 返回：

- `llm_fallback_used`
- `llm_error`

## 边界

这些字段只用于观测，不改变状态权威。即使 LLM fallback，状态变化仍只能来自 Rule Engine 接受的结构化事件；fallback intent 默认不携带 `proposed_actions`。
