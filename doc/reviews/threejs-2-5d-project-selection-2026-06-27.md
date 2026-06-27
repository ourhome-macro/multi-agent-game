# Three.js 2.5D 前端项目选型调研

调研日期：2026-06-27

## 结论

没有一个开源 Three.js 游戏项目适合直接“套壳”本项目。最优解是：用 Vite + React + TypeScript + `@react-three/fiber` 自建 `web/` 基底，把 Three.js 只作为 2.5D 场景层；参考少量房间/热点项目的场景组织方式，但不要复制它们的游戏状态、任务、背包或剧情规则。

根因很明确：本项目的权威状态在后端 Rule Engine、Narrative Director 和事件流，不在前端。任何带本地谜题状态、背包规则、剧情推进、NPC 行为逻辑的 escape room / adventure game 模板，都会和现有生产边界冲突。

## 适配目标

前端应满足：

- 正交或半固定相机的 2.5D 房间视角。
- 房间 GLB/低模几何 + hotspot 透明 mesh + hover/selected outline。
- NPC 位置、可点击对象和场景资产来自 `GET /cases/{case_id}` 公共投影。
- 可执行动作来自 `GET /sessions/{session_id}/affordances`，前端不重写 Rule Engine。
- 状态更新来自 `PublicActionResponse`、`PublicStateSummary` 和公开事件流。
- 对话、证据板、关系图、任务日志使用 React/HTML UI，不塞进 Three.js 场景逻辑。

## 推荐基底

### 1. 首选：自建 Vite + React + TypeScript + R3F

建议不要 fork 某个成品游戏仓库，而是新建：

- `vite`
- `react`
- `typescript`
- `three`
- `@react-three/fiber`
- `@react-three/drei`
- `@tanstack/react-query`
- `zustand`
- 后续资产链路加入 `gltfjsx` / `@gltf-transform/*`

这是最贴合项目约束的方案。代码从第一天就按公开 DTO、后端 affordances、事件流和 UI 状态边界组织，不需要先拆掉别人的本地游戏规则。

### 2. 可作为最小 R3F/Vite 参考：`wass08/r3f-vite-starter`

地址：https://github.com/wass08/r3f-vite-starter

调研结果：

- License：CC0-1.0。
- 技术栈：Vite、React 19、R3F 9、Drei 10、Three 0.173。
- 优点：极简、无业务包袱、适合看 Vite + R3F 的基础目录。
- 问题：不是 TypeScript，不含 API 层、UI 状态层、热点系统或场景数据投影。

判断：可参考，不建议直接 fork 后长期维护。真正落地时应按本项目目录重新 scaffold。

### 3. 如果前端明确改用 Next：`pmndrs/react-three-next`

地址：https://github.com/pmndrs/react-three-next

调研结果：

- License：MIT。
- Stars：约 2.8k。
- 技术栈：Next 14、React 18、R3F 8、Drei 9、Three 0.160。
- 优点：官方生态认可度高，重点解决 DOM/Canvas 共存和路由切换时 Canvas 持久化。
- 问题：当前项目文档推荐 Vite；Next 会引入 SSR/路由/部署约束，MVP 没必要先承受。

判断：仅在产品明确需要 Next 路由、SEO 或 Vercel SSR 时考虑。当前不作为首选。

## 可参考但不能作为生产基底

### `Themoltentungsten/Yashs-Room`

地址：https://github.com/Themoltentungsten/Yashs-Room

调研结果：

- License：MIT。
- 技术栈：Vite、React 18、R3F 8、Drei 9、Zustand、GSAP、styled-components。
- 有 `room.glb`、`objectData.js`、`Scene`、`Canvas`、`Overlay`、`Controls` 等房间式交互结构。
- 仓库包含音乐、图片、字体、个人作品资源，资产授权需要单独核查。

可借鉴：

- 房间 GLB + baked texture 的视觉路线。
- 场景组件、Canvas 包装、overlay UI 的拆分方式。
- `objectData` 类似热点配置的组织思路。

不能直接套：

- 它是作品集，不是规则驱动叙事客户端。
- JavaScript 项目，缺 TypeScript contract。
- 动画/音频/作品集交互过重，和本项目的证据、关系、事件流 UI 不同。

### `joncv/my-room-3D`

地址：https://github.com/joncv/my-room-3D

调研结果：

- License：MIT。
- 技术栈：Vite、React 18、R3F 8、Drei、postprocessing、Rapier。
- 有 `WorkRoom`、`Camera`、GLB room、baked texture。

判断：适合看“一个 room GLB 如何进入 R3F 场景”，但工程较旧，且 Rapier/物理不是当前 MVP 必需。

### `az9713/pirate-adventure`

地址：https://github.com/az9713/pirate-adventure

调研结果：

- License：无。
- 技术栈：Vite、TypeScript、Three.js、`three-pathfinding`。
- 目录里有 `HotspotManager`、`DialogueSystem`、`InventoryUI`、`ClickToMove`、`NavMesh`、`LevelManager`。

判断：这是最接近“点选冒险/热点/对话/物品栏”的结构参考，但无 license，不能复制代码进生产项目。最多作为模块命名和边界划分参考。

### `mahender-reddy85/3d-detective-room`

地址：https://github.com/mahender-reddy85/3d-detective-room

调研结果：

- License：无。
- 技术栈：Vite、TypeScript、React 19、R3F 9、Drei 10。
- 目录较小：`ThreeScene.tsx`、`Workroom.tsx`。

判断：题材接近 detective room，但无 license、无社区验证、仓库很新。不能作为代码来源。

## 明确不建议套用

### `silent-sea1119/Escape-room-three.js-React`

地址：https://github.com/silent-sea1119/Escape-room-three.js-React

问题：

- 无 license。
- Create React App。
- 偏原生 Three.js，不是 R3F。
- README 仍是 CRA 默认内容，工程治理弱。

### `pmndrs/racing-game`

地址：https://github.com/pmndrs/racing-game

问题：

- 赛车游戏，物理、HUD、多人/排行等方向和悬疑叙事完全不同。
- 可学习 R3F 大型组件组织，但不能作为本项目基底。

### `pmndrs/ecctrl`

地址：https://github.com/pmndrs/ecctrl

问题：

- 物理角色/车辆/无人机控制器工具包。
- 当前 MVP 不应引入物理角色控制。2.5D 点击热点比自由移动更稳。

### MIT 但工程质量不适合作为基底的 escape room

- `Kwanele-Jaca/EscapeRoom`：MIT，但仓库含 `node_modules`，根目录无标准 `package.json`。
- `emanuelghdev/the-dim-room`：MIT，但更像原生资产/课程项目，缺少现代 React/R3F 前端结构。

## 推荐落地方式

第一阶段只做场景客户端，不做完整游戏引擎：

```text
web/src/
  api/
    client.ts
    cases.ts
    sessions.ts
  game/
    GameApp.tsx
    GameCanvas.tsx
    SceneRenderer.tsx
    RoomScene.tsx
    HotspotMesh.tsx
    NpcActor.tsx
    SelectionOutline.tsx
  ui/
    DialoguePanel.tsx
    EvidenceBoard.tsx
    RelationshipPanel.tsx
    EventLog.tsx
    ActionMenu.tsx
  state/
    uiStore.ts
    selectionStore.ts
  types/
    public-api.ts
```

关键实现原则：

- `RoomScene` 只消费 `PublicScene`、`PublicHotspot`、`PublicCharacterPlacement`。
- `HotspotMesh` 只提交 `target_id`，不携带 clue truth 或本地谜题状态。
- `ActionMenu` 的按钮只来自 `affordances`。
- `EvidenceBoard` 只展示 `PublicStateSummary.evidence_assets`。
- `EventLog` 只拉公开 `events?after_count=N`，不能读取内部 `WorldEvent`。
- Three.js object 的 `userData` 只允许存公开 id 和 UI metadata。

## 最终建议

不要找一个完整 Three.js 逃脱游戏来改。它会把前端变成第二套规则系统，后续一定和后端事件流、Director 审计、线索释放节奏冲突。

建议执行：

1. 用 Vite + React + TypeScript 自建 `web/`。
2. 参考 `wass08/r3f-vite-starter` 的最小 R3F/Vite 配置。
3. 参考 `Yashs-Room` / `my-room-3D` 的房间 GLB、相机和 overlay 组织。
4. 只借鉴 `pirate-adventure` 的 `HotspotManager` / `DialogueSystem` / `InventoryUI` 这种模块边界，不复制代码。
5. 暂不引入 Rapier、Ecctrl、自由移动 NavMesh 或完整本地 inventory rules。

验收标准应是：前端能用公开 API 渲染 `mist_clock_manor` 一个房间，点击热点触发 `inspect`，点击 NPC 打开后端 affordance 生成的操作菜单，提交 action 后只根据公开 response/state/events 更新 UI。
