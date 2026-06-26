# Frontend 导读

当前前端尚未落地，只有规划文档。

优先阅读：

- [threejs-frontend-plan.md](threejs-frontend-plan.md)：Three.js 前端方案。
- [../planning/frontend-backend-mvp-cut-2026-06-18.md](../planning/frontend-backend-mvp-cut-2026-06-18.md)：前端接入前的后端 MVP 收口。

历史参考：

- [sillytavern-reference-review-2026-06-15.md](sillytavern-reference-review-2026-06-15.md)：SillyTavern 产品参考，不是当前实现方案。

## 原则

- 前端只消费公开 API，不读 YAML。
- Three.js 负责场景表现，不负责剧情规则。
- React overlay 负责对话、证据板、关系图、日志和错误反馈。
- 所有状态变化来自 `ActionResponse` / `StateSummary` / `WorldEvent`。

