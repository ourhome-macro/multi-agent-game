# agent剧本杀前端视觉与会议面板修正

更新日期：2026-06-27

## 本次修正

- 修复会议面板无法直接输入的问题：会议面板打开后即进入可讨论状态，不再依赖前端本地的“先发起会议”禁用态。
- 会议面板统一使用公开 `caseDetail`、公开 `state.evidence_assets` 与后端公开 `affordances.accuse`，不展示 NPC 内部状态、规则引擎状态或未解锁真相。
- 会议面板支持本地群聊式讨论记录；最终判决按钮仍通过公开 `accuse` affordance 提交给后端规则系统。
- 修复角色贴图在 WebGL 中偏糊的问题：禁用贴图 mipmap 模糊，提升 Canvas DPR，并放大角色与头顶姓名显示。
- 角色头顶姓名改为无底框文字描边，不再使用方框包名字。
- 主角左右朝向已反转，修正 WASD 横向移动图标方向错误。

## 边界说明

会议群聊当前是前端 MVP 交互层，只负责承载公开讨论、已知证据展示和判决入口。案件推进、投票是否成立、最终裁决是否通过，仍必须由后端 Rule Engine / Narrative Director 根据公开 action 和世界状态判断。

## 验证

已执行：

```powershell
cd web
npm run build
```

结果：TypeScript 与 Vite production build 通过，仅保留 Three.js 首包超过 500 kB 的 MVP 阶段预期 warning。

已用 Edge + Playwright 验证：

- 会议按钮可点击打开。
- 会议输入框不再 disabled。
- 输入并发送后出现玩家会议消息。
- 会议面板可关闭。
- 页面无 console error / pageerror。
- 角色与头顶姓名已按 2x DPR 渲染复查。

验证截图：

- `E:\tmp\agent-meeting-click-fixed-2.png`
- `E:\tmp\agent-scene-clarity-fixed-2.png`
