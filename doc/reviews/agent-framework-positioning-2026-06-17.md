# Agent Framework Positioning Review

生成时间：2026-06-17

## 结论

这个项目的核心不是“多 NPC 接 LLM 聊天”，而是一个事件溯源的悬疑叙事运行时。LLM 只负责角色表达、推理姿态和候选意图；真正的世界状态、线索状态、关系、剧情阶段、角色认知和记忆都由后端规则链路写入 `WorldEvent`，并要求 replay 可还原。

最接近的外部范式是：

- Letta 的 stateful agent 和 memory 管理，但本项目把记忆写入权从 Agent 手里拿走，改为规则派生。
- Claude Code / Goose 的 agent runtime、skills、hooks / extensions、长期任务观测，但本项目不是通用工具执行器，而是剧情领域专用运行时。
- ReMe 的经验记忆生命周期思想，但本项目当前不做自我进化式 procedural memory，只做可审计、可回放、可裁决的叙事记忆。
- 如果把 nanolaw 理解为法律式约束 Agent，本项目更像“证据链 + 规则裁判 + 受限表达”的叙事法庭；但我没有找到明确、主流、可引用的 NanoLaw 框架入口，不建议强行对标。

一句话定位：这是 `event-sourced narrative agent runtime`，不是 LangChain/CrewAI 式 Agent 编排，也不是单纯 RAG 记忆机器人。

## 项目结构判断

当前结构已经形成清楚的生产边界：

- `app/domain/models.py`：领域模型中心，定义 Action、Intent、WorldEvent、Memory、NPC Skill、LLM contract、StateSummary。
- `app/runtime/service.py`：运行时主链路，串起玩家动作、AgentLoop、Director、RuleEngine、派生事件、memory snapshot 和 trace。
- `app/agents/*`：Agent 上下文构造、记忆检索、LLM 合同、真实/Mock Agent、NPC skill 选择和 turn plan。
- `app/director/*`：事实披露网关和 Narrative Director，负责 safe fragment、禁说事实、剧透拦截。
- `app/rules/*`：真实状态变更权威，包括 inspect、ask_about、present_clue、accuse、agent proposed action、trigger 推进。
- `app/runtime/derivations.py`、`memory_snapshots.py`、`replay.py`：事件派生、记忆归并和回放一致性。
- `cases/*`：案件包。这里不只是素材，而是剧情规则、事实图、线索、NPC skill、mock dialogue、solution claims 和标准场景。
- `tests/*`：已经不是简单单测，包含场景级、矩阵级、LLM shadow、memory、skill、Postgres 和 trace 维度。

主链路可以概括为：

```text
raw text / PlayerAction
  -> ActionRouter / RuleEngine precheck
  -> ActionService
  -> player.* WorldEvent
  -> MemoryArchivalSystem
  -> RetrievalPlanner + NpcSkillSelector
  -> MemoryRetriever
  -> AgentContext
  -> LLMAgentContractInput
  -> AgentGateway
  -> validate_llm_agent_output
  -> NarrativeDirector.validate
  -> npc.replied 或 director.blocked
  -> RuleEngine.apply_agent_intent
  -> DerivedEventSystem
  -> MemorySnapshotSystem
  -> RuleTriggerSystem
  -> RuntimeTrace
```

最关键的优点：LLM 后面至少有 Python 合同校验、Narrative Director 和 Rule Engine 三道门。这个方向是对的。

## Memory 体系

### 写入链路

记忆不是 LLM 自己写的。真实写入路径是：

```text
WorldEvent
  -> DerivedEventSystem
  -> memory_candidate.created
  -> MemorySnapshotSystem
  -> agent_memory_snapshot.updated
```

`MemoryCandidateState` 是候选，`AgentMemorySnapshot` 是稳定快照。每条记忆要求 `source_event_ids`、`rule_id`、scope、layer、type 和 metadata。这样记忆可以被 replay、审计和冲突裁决。

当前 memory 维度：

- type：`episodic`、`belief`、`relationship`、`strategy`
- scope：`case`、`session`、`npc_private`、`scene_shared`、`director_audit`
- layer：`core`、`working`、`archival`

这套设计比普通“向量库长期记忆”更适合悬疑游戏，因为它优先回答“谁因为什么事件知道了什么”，而不是“哪段文本最相似”。

### 读取链路

读取不是裸检索。实际是：

```text
MemoryProjectionSkill
  -> MemoryRetrievalPlan
  -> NPC Skill memory policy 收窄
  -> MemoryStore fetch
  -> hard filters
  -> scoring / rerank
  -> authority conflict resolution
  -> AgentContext.memory_snapshots
```

硬过滤顺序是正确的：先 scope、owner / visible、layer、source、phase、plan、forbidden content，再排序。这样不会因为 salience、recency 或关键词命中把其他 NPC 私有记忆泄进当前 NPC。

`MemoryRetriever` 还提供了 `retrieve_for_director`，允许 Director 看 `director_audit`；但这不等于把审计记忆注入 NPC。这一点边界很重要。

### 当前风险

记忆正文仍会进入 `WorldEvent` payload 和 replay 数据，这对剧情回放是必要的，但也是敏感数据面。trace 已做脱敏，数据库和日志权限也必须按“可还原剧情秘密”的级别处理，不能当普通 telemetry。

另一个风险是文档和代码存在轻微滞后。`doc/agents/npc-skill-implementation-2026-06-16.md` 仍说 skill selected/rejected 事件、输出合同约束、memory policy 合并未落地；但代码里 `EventType.NPC_SKILL_SELECTED` / `NPC_SKILL_REJECTED`、`ActionService._record_npc_skill_events(...)`、`turn_plan.py`、`final_retrieval_plan.py` 已经实现了相当一部分。后续需要清理旧文档，避免生产评审误判。

## 多 Agent 传播

本项目当前的多 Agent 传播不是“NPC 互相聊天”，而是事件传播。

已有传播路径：

- 玩家对某 NPC `ask_about` / `present_clue` / `accuse` 会派生该 NPC 的 `CharacterFactAwarenessState`。
- 私下展示线索产生 `npc_private` memory，只对目标 NPC 可见。
- 当众展示线索使用 `presentation_mode=scene_shared`，派生 `scene_shared` memory，并通过 `visible_to_character_ids` 限制场景内 NPC 可见。
- `character_impression.updated` 是某个 NPC 对玩家的私有画像，普通 AgentContext 过滤其他 NPC 的画像。
- `relationship.changed` 和 threshold 事件会进一步影响画像和可用策略。
- `director.blocked` 可派生 `director_audit` memory，但默认不进入 NPC。

这比“群聊广播”更适合悬疑，因为传播带来源、范围、时点和权限。

当前尚未完成的多 Agent 能力：

- 没有 NPC-NPC 自主社交回合。
- 没有 overhear、rumor、testimony、confrontation broadcast 等专门事件类型。
- scene_shared 只覆盖玩家当众展示证据，不等于完整公共知识系统。
- 没有基于事件的跨 NPC 认知冲突传播矩阵，例如 A 听说 B 的说法后形成 hearsay belief。

正确下一步不是直接接一个 multi-agent chat room，而是先定义传播事件：

```text
npc.spoke_publicly
npc.overheard
npc.testimony_shared
npc.rumor_received
character_fact_awareness.updated(source_type=npc_hearsay)
agent_memory_snapshot.updated(memory_scope=scene_shared/session, authority_source=npc_hearsay)
```

同时必须保留 `authority_source` 和 conflict resolution，避免 hearsay 压过玩家证据或系统规则。

## LLM 长跑回归

长跑回归已经有四层：

- 场景级 harness：`tests/utils/scenario_evaluation.py` 和 `tests/test_mist_clock_manor_scenario.py` 跑完整调查路径、deviation path、Director block、accuse、replay。
- P0 regression matrix：`app/evaluations/p0_regression_matrix.py` 锁 Memory、Director、Action Intake、Deduction 的关键边界。
- Memory retrieval matrix：锁定某 phase、某 action 下 expected / forbidden memory ids，防止检索策略漂移。
- LLM shadow eval：真实 LLM 只产候选 intent，不写世界事件，不污染状态，用来评估越权、剧透、schema 和 drift。

这套方向对生产是必要的。尤其是 shadow eval 的设计很清醒：真实 LLM 能跑，但不能进入权威链路；先看候选风险，再决定是否放开。

长跑层面还需要补三件事：

1. 给每个真实案件要求至少一条标准路径、若干 deviation path、若干 red-team spoiler probe。
2. 给真实 LLM 增加固定 seed 不可得时的统计门槛，例如 N 次 shadow 中越权率、fallback 率、Director block 率、invalid JSON 率。
3. 把 runtime trace 和 scenario report 对齐成同一套 release gate，而不是只靠 pytest 通过。

## Skill 设计

这里有两类 skill，不能混淆。

`MemoryProjectionSkill` 是检索投影 skill，位于 `app/agents/skills/memory_projection/*.md`。它决定某类 PlayerAction 下 memory type/scope/layer、max items、portrait summary、recent events 等。

`NpcSkillConfig` 是游戏领域 skill，来自 `cases/<case_id>/npc_skills.yaml`。它不是 prompt 标签，而是后端授权：

- 哪个 NPC 拥有。
- 哪些 action / clue / topic 可触发。
- 哪些 phase、beat、player knowledge、world_info、pressure 条件解锁。
- 最多允许哪些 safe fragment refs 和 disclosure mode。
- 可用哪些 rhetoric tactics。
- 能否提出 relationship.change 等 proposed action。
- memory policy 如何进一步收窄检索。

当前设计正确点：

- LLM 不能选择、伪造、升级 skill。
- `AgentContext` 只拿 `NpcSkillProjection`，不拿 skill 正文和隐藏剧情。
- skill 的 safe fragment refs 还要和 Director 当前放行 safe fragments 取交集。
- selected skill 会收窄 `LLMAgentOutputContract`，生成前 schema 和生成后 Python 校验用同一套合同。
- 没有 selected skill 时，默认不允许主动 proposed action。

还缺的部分：

- cooldown 目前没有真实状态和 replay 恢复。
- `used_skill_ids` 还没有进入 `AgentIntent`，所以只能知道“后端本轮授权了什么”，不能知道“模型声称用了什么”。
- skill counter / weakness 还没有变成玩家可观察的公共投影。
- 缺少 `npc_skill.used` / `npc_skill.failed` 对最终结果做归因；现在 selected/rejected 已可审计，但还不是完整 skill lifecycle。

最优路线：不要先做更多 skill 类型，先把 skill lifecycle 事件补齐，并建立 skill matrix。否则 skill 会膨胀成另一层 prompt 配置。

## 外部框架类比

### Claude Code

相似点：都有 project instructions、memory、skills、hooks / tools、长任务、多个 agent 并行和 trace / review 的思想。Claude Code 官方文档把它定位为能读代码、改文件、运行命令并接入开发工具的 agentic coding tool。

差异点：Claude Code 的核心是软件工程任务执行器；本项目的核心是叙事状态机和证据规则。Claude Code 的 skill 更像工作流封装，本项目的 NPC Skill 是剧情权限和表达上限。

### Goose

相似点：Goose 是本机运行的通用可扩展 AI agent，支持 CLI、桌面、API、多 provider 和 MCP extensions。本项目如果以后做工具插件、案件 authoring 工具、自动评测 runner，可以借鉴 Goose 的 extension/provider 思路。

差异点：Goose 以工具执行和开放扩展为中心；本项目以 Rule Engine、Director 和 WorldEvent 为中心。这里不能让扩展绕过叙事权威。

### Letta

相似度最高。Letta 的 stateful agent 把 memory、messages、tools 和 agent state 持久化，memory block 可注入上下文，也可跨 agent 共享。

关键差异：Letta 允许 agent 通过 memory tools 修改自身记忆；本项目明确禁止 LLM 写 memory。记忆只能由事件和规则派生。这个差异是本项目的生产优势，因为悬疑游戏需要真相稳定、来源可查、传播可控。

### ReMe

ReMe 关注 procedural memory，从经验中提炼成功模式、失败触发和可复用策略，并做上下文适配和 utility-based refinement。

本项目和 ReMe 的共同点是都拒绝静态 append-only memory；都有 lifecycle、过滤、复用和淘汰。但本项目当前没有“自我提炼经验并改写策略库”的闭环，更多是规则化 typed memory + archival + authority conflict。

### NanoLaw

没有找到稳定的主流框架定义。若用户指的是法律/合规式小型 Agent 框架，本项目可类比于“证据法庭式 Agent”：事实、证据、指控、披露边界、角色认知和裁判权分离。但在没有明确框架来源前，不建议把 NanoLaw 当作正式技术对标。

## 下一步优先级

1. 修正文档滞后：更新 NPC Skill implementation note，标明 selected/rejected、output contract、memory policy merge 已落地，cooldown / used / failed 未落地。
2. 做 skill matrix：每个 phase/action/player knowledge 下 expected selected skill ids 和 forbidden skill ids。
3. 扩展多 Agent 传播事件，而不是接聊天总线。
4. 把 real LLM shadow long-run 做成 release gate，记录越权率、fallback 率、Director block 率、invalid JSON 率。
5. 做 UTF-8 / mojibake 检查。当前部分 PowerShell 默认输出会乱码，代码用 `Get-Content -Encoding UTF8` 看是正常的，但生产叙事素材必须有编码守门。

