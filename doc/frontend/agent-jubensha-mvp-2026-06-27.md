# agent剧本杀前端 MVP

更新日期：2026-06-27

## 当前实现

已新增 `web/` 前端 MVP，首个关卡固定为 `mist_clock_manor`（雾钟山庄）。当前版本已从早期后台面板式原型修正为全屏 WebGL 2.5D 游戏舞台：

- 开场黑幕白字引入故事前提，明确说明陆澜生召集众人的理由：公布《回声钟》最终署名、山庄与剧场股份信托安排，以及一封牵涉十年前江若岚坠湖旧案的信。
- 正交相机渲染书房、钟楼、画廊。
- 主角以 `idle`、`walk`、`interact`、`talk` 运动状态机驱动移动和姿态。
- 支持 WASD 连续移动：A/D 横向移动，W/S 在舞台纵深内移动。
- 点击热点、NPC、传送入口前，主角会先移动到对应位置。
- 镜头随主角水平位置轻微跟随。
- 地点切换通过“上楼 / 下楼 / 去画廊 / 回书房”入口完成，不再使用场景 tab。
- 手记是可开关抽屉，默认打开“目前知晓的剧情”，只展示公开前提、当前调查目标、案件记录和已发现证据。
- 前端不展示“后端已连接”、事件流、关系数值、NPC 内部状态或规则系统状态。

技术栈：

- Vite
- React
- TypeScript
- Three.js
- `@react-three/fiber`
- TanStack Query
- Zustand
- Lucide React

本次没有使用 `@react-three/drei`。当前 MVP 直接使用 R3F + Three 原生能力实现正交相机、场景几何、热点、NPC、传送入口和主角运动，依赖面更小。

## 边界

前端只消费公开 API：

- `GET /cases/{case_id}`
- `POST /sessions`
- `GET /sessions/{session_id}/state`
- `GET /sessions/{session_id}/affordances`
- `POST /sessions/{session_id}/actions`
- `POST /sessions/{session_id}/raw-actions`

前端不读取 YAML，不持有 solution claims、truth status、forbidden facts、NPC private memory 或规则逻辑。

`web/src/game/layout.ts` 只做展示层 deterministic layout：根据公开 scene/hotspot/character id 生成 2.5D 位置、传送入口和主角移动目标。该布局不能作为规则、线索或剧情状态来源。

## 交互能力

已支持：

- 自动创建雾钟山庄 session。
- 黑幕白字开场，使用 `doc/case/sample.md` 的公开开局信息强化前情提要。
- 全屏 Three.js 2.5D 舞台。
- 书房、钟楼、画廊三类场景视觉区分。
- 主角移动、交互、对话姿态切换。
- WASD 键盘移动会中断当前点击移动目标，并收起当前交互选择。
- 热点默认只显示场景物件和微光，悬停或选中才显示文字，避免遮挡场景。
- 点击 hotspot 后移动并提交 `inspect`。
- 点击 NPC 后移动并打开对话行动菜单。
- 手记中的“目前知晓的剧情”展示召集理由、邀请函、案发现场、当前目标，并把已发现公开线索追加为“调查新增”。
- `talk`、`ask_about`、`present_clue` 按后端 affordances 生成按钮。
- 后端返回可指认 affordance 时显示“指认”，不显示调试式禁用状态。
- 本地自然语言行动输入。
- 基础合成音效：hover、click、inspect、clue、dialogue、phase、error。
- 本地 BGM 文件选择与播放；BGM 文件由使用者自行提供，不进入仓库。

音效采用 Web Audio 合成，不引入音频素材授权风险。页面初始自动建会话时不主动创建 `AudioContext`，避免浏览器自动播放限制 warning；音效会在用户交互后播放。

## 已知缺口

当前美术仍是程序化占位资产，不是最终立绘或手绘场景。它的目标是验证 WebGL 交互、角色移动、场景切换和前后端边界，不是最终视觉质量。

正式指控仍依赖后端公开 affordance 的安全契约。如果后端内部仍要求 `claim_id`，前端不能内置该值；生产版本应由后端提供公开 `accuse_token`、`accuse_option_id` 或专门的安全指控 DTO。

## 运行方式

后端建议本地验证使用内存 runtime：

```powershell
set AGENT_RUNTIME=memory
py -3.12 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端：

```powershell
cd web
npm install
npm run dev -- --port 5173
```

访问：

```text
http://127.0.0.1:5173
```

`web/vite.config.ts` 将 `/api/*` 代理到 `http://127.0.0.1:8000/*`。

如果需要连其他后端地址，可以设置：

```text
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## 验证记录

已执行：

```powershell
cd web
npm run build
```

结果：TypeScript + Vite production build 通过。当前 bundle 有 Three.js 首包超过 500 kB 的 warning，这是 MVP 直接引入 WebGL 渲染栈的预期现象，后续可用 route/chunk split 优化。

已用系统 Edge + Playwright Core 做浏览器检查：

- 页面加载成功。
- 无 Vite error overlay。
- 黑幕白字开场可进入。
- 开场文本说明陆澜生为什么召集众人、今晚原本要公布什么、十一点十七分为何重要。
- 点击顶部手记按钮可打开“目前知晓的剧情”面板。
- Three.js canvas 非空。
- WASD 键盘移动可用，移动后主角位置变化且镜头跟随。
- 页面不包含“后端”“已连接”“状态”“安全标识”“自然语言”等露馅文案。
- 页面无 `pageerror`，console error 为空。
- 点击“上楼”可切换到钟楼场景。

验证截图：

- `E:\tmp\agent-jubensha-redesign.png`
- `E:\tmp\agent-jubensha-clocktower.png`
- `E:\tmp\agent-jubensha-wasd.png`
- `E:\tmp\agent-jubensha-intro-brief.png`
- `E:\tmp\agent-jubensha-known-story.png`

## 后续建议

1. 给 `PublicScene` 增加公开 presentation 字段：camera、hotspot position/size、character placement、asset refs。
2. 增加公开安全指控 DTO，不让前端知道内部 `claim_id`。
3. 引入真实手绘场景图、角色立绘或精灵序列，替换当前程序化占位资产。
4. 为主角和 NPC 增加 sprite sheet 动画资源，继续沿用 `idle/walk/interact/talk` 状态机。
5. 补前端 smoke test：创建 session、检查红酒杯、询问林栖迟、展示酒液线索、上楼到钟楼。
