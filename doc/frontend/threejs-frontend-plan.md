# Three.js 前端方案

更新日期：2026-06-26

2026-06-27 补充：已按本文方向新增 `web/` 前端 MVP，产品名暂定 `agent剧本杀`，首个关卡为 `mist_clock_manor`（雾钟山庄）。最新实现已调整为全屏 WebGL 游戏舞台、黑幕白字开场、主角 `idle/walk/interact/talk` 运动状态机、入口式上楼/下楼/去画廊传送，并移除事件流、关系数值和后端连接状态类前端展示。实现细节与验证记录见 `doc/frontend/agent-jubensha-mvp-2026-06-27.md`。

## 结论

前端应做成 2.5D 悬疑场景客户端，而不是全自由 3D 小镇模拟。Three.js 负责空间表现、热点、NPC 位置、镜头和氛围；剧情状态、线索解锁、关系变化、记忆、Director 审计都仍由后端决定。

前端不得读取案件 YAML，也不得持有 solution claims、truth status、forbidden facts、NPC private memory 或规则逻辑。

## 推荐技术栈

- Vite
- React
- TypeScript
- Three.js
- `@react-three/fiber`
- `@react-three/drei`
- Zustand：本地 UI 状态
- TanStack Query：API 请求、缓存、轮询

暂不建议一开始引入复杂游戏引擎。当前目标是跑通一个可审计的悬疑交互闭环。

## 画面形态

推荐形态：

- 正交相机。
- 固定或半固定房间视角。
- 低多边形房间或手绘贴图平面。
- NPC 用 billboarding sprite、低模角色或立绘卡片。
- 热点用透明 mesh + hover outline。
- 对话、证据板、关系图、任务日志用 HTML overlay。

Three.js 渲染：

- 房间几何。
- 光照和氛围。
- NPC 位置。
- hotspot 区域。
- clue marker。
- hover / selected outline。
- 轻量镜头移动。

React/HTML 渲染：

- 对话面板。
- 行动按钮。
- 证据板。
- 关系面板。
- 事件日志。
- 错误和澄清 UI。

## 后端依赖 API

前端第一版不应直接对接内部模型，必须依赖公开投影：

```text
GET /cases
GET /cases/{case_id}
POST /sessions
GET /sessions/{session_id}/state
GET /sessions/{session_id}/affordances
POST /sessions/{session_id}/actions
POST /sessions/{session_id}/raw-actions
GET /sessions/{session_id}/events?after_count=N
```

其中 `GET /cases/{case_id}` 和 `GET /sessions/{session_id}/affordances` 还需要补。

## 前端数据模型

建议公开 scene DTO：

```ts
type PublicScene = {
  id: string;
  name: string;
  description: string;
  camera: {
    position: [number, number, number];
    target: [number, number, number];
  };
  hotspots: PublicHotspot[];
  characters: PublicCharacterPlacement[];
};

type PublicHotspot = {
  id: string;
  name: string;
  description: string;
  position: [number, number, number];
  size: [number, number, number];
  initiallyVisible: boolean;
};

type PublicCharacterPlacement = {
  id: string;
  displayName: string;
  publicRole: string;
  position: [number, number, number];
};
```

这些字段可以先由后端公共 case projection 生成。不要把 `truth_status`、`reveals_world_info`、`solution_claims` 或 character `private` 发给前端。

## 组件切分

建议目录：

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
```

核心原则：

- API state 交给 TanStack Query。
- 临时选择、hover、面板开关交给 Zustand。
- 不在前端复制 Rule Engine。
- 不在 Three.js object 上存剧情真相，只存公开 id。

## 交互流程

启动：

```text
GET /cases
GET /cases/{case_id}
POST /sessions
GET /sessions/{session_id}/state
GET /sessions/{session_id}/affordances
```

点击 hotspot：

```text
click HotspotMesh
  -> POST /sessions/{id}/actions { type: "inspect", target_id }
  -> render ActionResponse.speech if any
  -> update StateSummary
  -> append new_events
  -> refresh affordances
```

点击 NPC：

```text
click NpcActor
  -> open ActionMenu
  -> talk / ask_about / present_clue
  -> POST /sessions/{id}/actions
  -> render dialogue
  -> update evidence board / relationships / event log
```

自然语言输入：

```text
POST /sessions/{id}/raw-actions
  -> accepted: apply nested ActionResponse
  -> needs_clarification: show clarification UI
  -> rejected: show stable reason code
```

## 第一版验收

用 `mist_clock_manor` 标准路径做 smoke test：

1. 创建 session。
2. 进入书房场景。
3. 点击酒桌发现红酒线索。
4. 与 NPC 对话或询问线索。
5. 展示证据。
6. 检查门锁、录音机、烧毁信、药盒、电闸箱。
7. 进入 reconstruction。
8. 发起正式指控并进入 resolved。

验收标准：

- 前端不读 YAML。
- 前端不出现 hidden truth。
- 所有按钮来自 affordances 或公开 state。
- 所有状态变化来自 ActionResponse / StateSummary。
- Director block 和 rule rejection 都有可展示 reason。
