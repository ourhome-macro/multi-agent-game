# Provider Token Budget

## 问题

旧版 `ContextBudgetManager` 只用 `len(text) // 4` 估算 prompt token，并把 `context_limit_tokens` 当作完整输入预算。这在真实 provider 上不成立：

- provider 的 context window 同时容纳输入和输出。
- 不同 provider / model 的 context limit、预留输出、服务端安全余量不同。
- 没有 tokenizer / estimator 注入点时，生产只能靠粗估，真实 LLM 仍可能在 provider 侧超限失败。

## 当前实现

`app/runtime/budget.py` 新增 `TokenBudgetProfile`：

- `provider`
- `model`
- `context_limit_tokens`
- `reserved_output_tokens`
- `safety_margin_tokens`
- `conservative_multiplier`

实际输入预算为：

```text
available_input_tokens =
  context_limit_tokens
  - reserved_output_tokens
  - safety_margin_tokens
```

`ContextBudgetManager` 的 `context_budget_ratio` 使用 `available_input_tokens`，不是裸 `context_limit_tokens`。

## Estimator 边界

`TokenEstimator` 是可注入协议：

```python
estimate(text, *, profile=None) -> TokenEstimate | int
```

生产可接真实 tokenizer，本地和 CI 默认使用 `ConservativeTokenEstimator`，不下载依赖、不调用网络。默认估算取字符数、UTF-8 字节数和词数的保守上界，再由 profile 的 `conservative_multiplier` 放大。

`estimate_tokens(text)` 仍保留兼容入口，但内部已走同一 estimator/profile 逻辑。

## Trace

`context_layer_budget` 只记录安全元数据：

- hard / soft token estimate
- `hard_context_over_limit`
- `fallback_reason`
- provider / model
- context limit / available input / reserved output / safety margin
- conservative multiplier
- estimator method

trace 不记录 prompt 文本、memory content、private 原文、safe fragment summary 或玩家原文。

## 非目标

本次只提供 provider/model budget profile、tokenizer/estimator 抽象和 manager 输出信号。真正的 hard context 超限阻断由 AgentLoop / runtime fallback 链路执行，不在该模块里直接调用 LLM fallback，也不改变 Rule Engine、Narrative Director 或世界状态写入权威。
