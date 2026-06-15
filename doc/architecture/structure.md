# 项目目标结构

本文档描述当前项目从空仓库起步时的目标结构。核心原则是先建立稳定、可测试、可回放的叙事状态系统，再逐步扩展 Agent 自主性和前端表现力。

## 一句话结构

项目应拆成五个核心闭环：客户端交互、后端世界状态、规则引擎、Agent 生成层、叙事导演层。

```text
玩家行为
  -> Web 客户端采集交互
  -> API 转换为 PlayerAction
  -> 后端读取世界状态和角色状态
  -> Agent 生成 NPC 表达与行为意图
  -> Narrative Director 做剧透和一致性检查
  -> Rule Engine 校验并执行真实状态变化
  -> Event Log 记录全过程
  -> 客户端刷新场景、对话、线索板和关系图
```

## 推荐目录结构

```text
agent/
  AGENTS.md
  README.md
  docker-compose.yml
  .env.example

  doc/
    agent.md
    structure.md
    architecture.md
    world-state.md
    narrative-director.md
    api-contract.md

  apps/
    web/
      src/
        app/
        game/
        components/
        stores/
        api/

  services/
    api/
      app/
        main.py
        config.py
        api/
        domain/
        rules/
        agents/
        director/
        memory/
        persistence/
        realtime/
        tests/

  packages/
    shared/
      types/
      schemas/

  infra/
    docker/
    migrations/
    observability/
```

## 模块职责

### `apps/web`

前端游戏客户端。Next.js 和 React 承载 UI，Phaser 或 PixiJS 承载 2D 场景。

- `game`：地图、角色、碰撞、交互热点、场景切换。
- `components`：对话框、线索板、关系图、任务日志、调查面板。
- `stores`：Zustand 客户端状态，只缓存展示状态，不做权威判断。
- `api`：HTTP、WebSocket 或 SSE 客户端封装。

### `services/api`

后端权威服务。FastAPI 承载接口、实时连接、游戏会话和 Agent 调度。

- `api`：路由层，只做协议转换和权限校验。
- `domain`：角色、关系、记忆、线索、事件、剧情阶段等核心模型。
- `rules`：动作合法性、关系变化、线索释放、剧情推进。
- `agents`：NPC Agent、prompt 组装、记忆检索、结构化意图生成。
- `director`：悬疑节奏、剧透防护、剧情一致性检查。
- `memory`：短期记忆、长期记忆、向量检索和记忆写入策略。
- `persistence`：PostgreSQL、pgvector、事件日志、事务边界。
- `realtime`：WebSocket/SSE 推送事件和 UI 更新。

### `packages/shared`

跨前后端共享类型和协议定义。优先放稳定的 DTO、枚举、事件名称和 API schema。

### `infra`

基础设施和部署配置。包括 Docker、数据库迁移、日志、追踪和监控配置。

## 核心领域对象

- `PlayerAction`：玩家输入、移动、调查、询问、质询、选择。
- `AgentIntent`：NPC 由 LLM 生成的结构化行为意图。
- `WorldEvent`：所有可回放的玩家行为、NPC 行为和状态变化。
- `Character`：身份、性格、目标、秘密、认知、情绪和说话风格。
- `Relationship`：信任、怀疑、恐惧、亲密、敌意等关系维度。
- `Memory`：来源事件、可见角色、重要性、时间戳、向量索引。
- `Clue`：线索内容、发现条件、真假状态、关联人物和关联事件。
- `NarrativeState`：剧情阶段、已释放线索、禁说事实和真相锚点。

## 第一阶段 MVP 边界

第一阶段不要做开放世界，也不要做过度自主的 NPC 社会模拟。先做单案件闭环。

- 1 个案件。
- 1 张主要地图。
- 3 到 5 个 NPC。
- 20 到 40 条核心线索。
- 关系状态先做有限维度，不做复杂社会传播。
- 记忆系统先保证来源可追溯，再优化向量检索效果。
- LLM 只输出结构化意图和对话，不能直接改世界状态。

## 最小可运行闭环

```text
玩家点击 NPC
  -> 前端发送 start_dialogue
  -> 后端加载角色、关系、剧情阶段和相关记忆
  -> Director 生成可说范围
  -> NPC Agent 输出 speech 和 proposed_actions
  -> Director 检查剧透
  -> Rule Engine 校验 proposed_actions
  -> 写入 WorldEvent、Memory、RelationshipDelta
  -> 前端展示回复并刷新线索板/关系图
```

## 关键风险

- 如果没有事件日志，后续剧情无法调试。
- 如果规则藏在 prompt 里，生产环境必然不可控。
- 如果 NPC 能访问全局真相，悬疑会提前崩坏。
- 如果前端承担权威状态判断，多端一致性会失控。
- 如果一开始做开放世界，项目会被复杂度拖死。

