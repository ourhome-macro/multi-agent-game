# 当前状态与下一步

更新日期：2026-06-26

## 当前判断

后端主架构是成立的：`PlayerAction`、Rule Engine、Narrative Director、Agent Loop、记忆检索、事件日志和 replay 边界已经分开。当前最大的生产风险不是 NPC 不够自由，而是：

- 前端缺少稳定的公开投影 API。
- 真实 LLM payload 太宽，token 成本明显偏高。
- 部分运行时模块已经过大，后续维护和审计成本上升。
- 文档历史记录太多，当前有效结论需要集中入口。

## 已具备能力

- 案件包加载、schema 校验、引用校验。
- 创建 session、提交结构化 action、raw text intake。
- `inspect`、`talk`、`ask_about`、`present_clue`、`accuse` 主链路。
- Rule Engine 负责真实状态变化。
- Narrative Director 负责 safe fragment 和后置剧透审计。
- Agent 默认 mock，真实 LLM 可选启用。
- 记忆检索支持 scope/layer/type、typed memory、scene_shared、case_thread、diagnostics。
- PostgreSQL event stream runtime 已有基础路径。
- `mist_clock_manor` 已有标准路径和 deviation scenarios。

## 当前主要缺口

1. 前端 API 不完整
   - 缺 `GET /cases/{case_id}` 公共 case detail / scene graph。
   - 缺 `GET /sessions/{session_id}/affordances`。
   - 缺稳定 error DTO 和 reason code。
   - `events` 仍偏全量读取。

2. LLM token 成本偏高
   - reconstruction 示例里完整 `LLMAgentContractInput` 约 13.6k tokens。
   - 最大开销来自完整 `AgentContext`、完整 `AgentMemorySnapshot`、recent events、inner context、safe fragments。
   - 需要 provider 专用 compact DTO，而不是把审计对象原样发给模型。

3. 模块过大
   - `app/runtime/derivations.py` 聚合了太多派生规则。
   - `app/agents/real_llm_agent.py` 同时负责 request、schema、repair、本地投影、错误分类。
   - 建议在行为稳定后做机械拆分，不先做语义重写。

4. 前端尚未落地
   - 目前只有规划文档，没有实际客户端。
   - 应优先做 2.5D Three.js 场景客户端，不做小镇式自由模拟。

## 推荐执行顺序

1. 补公开 case detail endpoint。
2. 补 session affordances endpoint。
3. 统一 API error code / reason DTO。
4. 新增 compact LLM provider payload，保留本地完整合同校验。
5. 新增 LLM memory projection，禁止把完整 snapshot 发给 provider。
6. Scaffold `web/`：Vite + React + TypeScript + Three.js。
7. 用 `mist_clock_manor` 标准路径做前后端 smoke test。
8. 稳定后拆分 `derivations.py` 和 `real_llm_agent.py`。

## 当前不建议做

- 不要先做 NPC 自主 tick。
- 不要先做 NPC-NPC 大规模社交传播。
- 不要让前端读取 YAML 或 solution config。
- 不要把真实 LLM 设成默认运行路径。
- 不要引入向量库作为当前召回问题的第一解。
- 不要把 token 优化做成丢安全上下文；应做 provider payload 投影。
