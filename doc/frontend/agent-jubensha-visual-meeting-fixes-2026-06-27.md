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

## 追加修复：会议群聊点击无反馈

根因不是单纯的 CSS 点击穿透，而是会议聊天输入区被绑定到后端公开 `meeting.active`。当前 MVP 会话未真正激活会议时，面板会落入“召集会议”分支；继续点击发送时，`meeting_speak` 会被规则接口返回 422，玩家看到的结果就是“面板能开但点不了/发不出去”。同时，空证据数组在每次 render 中重新创建，触发过 React maximum update depth warning，使问题更像页面卡死。

本次处理：

- 前端会议面板打开后直接进入讨论态，不再让“召集会议”分支挡住聊天输入。
- 增加 `backendMeetingActive` 边界：只有后端公开会议已激活时，会议动作才提交给规则系统；未激活时只进入前端本地会议记录，不改写世界状态、线索状态、关系状态或剧情阶段。
- 增加本地会议记录 `localMessages`，让纯聊天、点名、证据展示和投票 UI 在 MVP 阶段可操作可见。
- 增加本地投票目标 `localVoteTargetId`，避免未激活后端会议时“开票”按钮没有任何反馈。
- 移除会导致无限更新的空证据过滤 effect，保留名单选择同步 effect。

复查结果：

- `npm run build` 通过。
- Playwright 真实页面验证通过：会议按钮可打开，输入框可编辑，发送后出现玩家消息，投票区可展开，面板可关闭。
- 本次复查无 422、无 console error、无 React maximum update depth warning。
- 最新截图：`E:\tmp\agent-meeting-click-final-local.png`。

## 追加修复：点击线索 / NPC 的移动节奏

原问题：点击远处线索、NPC 或传送点后，主角自动移动使用高阻尼 `damp`，初段速度过快；交互触发使用固定 `setTimeout`，没有等待主角实际走到目标点，远距离点击会显得像冲刺或瞬移。

本次处理：

- 主角点击移动改为固定速度 `clickWalkSpeed`，按每帧距离匀速靠近目标，不再使用高阻尼指数追踪。
- 线索检查、NPC 谈话姿态、传送切场景改为“到达目标点附近后触发”，不再用固定毫秒数猜测。
- WASD 输入会取消当前点击移动的待触发交互，避免玩家手动移动时仍然自动触发旧目标。
- 操作面板的检查、对话、问线索、示证、指认按钮增加距离判定，主角没走近前不会直接提交后端动作。

复查结果：

- `npm run build` 通过。
- Playwright 真实页面验证通过：点击远处线索后主角逐步移动；行走中“检查”按钮禁用，到达附近后可用；无 console error。
- 验证截图：`E:\tmp\agent-walk-before-click.png`、`E:\tmp\agent-walk-after-160ms.png`、`E:\tmp\agent-walk-after-1410ms.png`、`E:\tmp\agent-walk-button-during.png`、`E:\tmp\agent-walk-button-arrival.png`。
