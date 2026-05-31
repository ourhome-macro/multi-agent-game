# World State

`SessionState` is the in-memory authoritative runtime state. Static case content
lives in `CasePackage`.

## SessionState

Current session state includes:

- `id`
- `case_id`
- `narrative.phase`
- `narrative.discovered_clues`
- `narrative.completed_beats`
- `relationships`
- `relationship_thresholds_crossed`
- `discovered_clues`
- `player_knowledge`
- `memory_candidates`
- `memory_snapshots`
- `character_impressions`
- `events`

`StateSummary` is a public projection of this state. It is not the authority.
Runtime memory snapshots and private character impressions are intentionally not
exposed through `StateSummary`.

## Character Cards

Static character data is split into public role-card data and private character
perspective data:

- public: `display_name`, `public_role`, `public_description`, `speech`,
  visible personality traits, and response styles
- private: goals, secrets, and internal character knowledge

`private` is not hidden from the NPC itself. The target NPC always knows its own
private goals, secrets, knowledge, and impressions. The restriction is about
public projection, other NPC visibility, outward expression, and state authority.

`AgentContext.target_profile` is derived from the public layer only. Runtime
memory content may use public display names for readability, but it must not
copy private goals, secrets, or internal knowledge into `WorldEvent`,
`StateSummary`, `AgentContext`, or player journey output.

Character Inner Context v0 copies only the target NPC's controlled self view
into `AgentContext.inner_context`. It does not copy another NPC's private data,
and it does not expose the raw `CharacterPrivateConfig` object. Each inner item
carries a `DisclosurePolicy` so fallback agent behavior can use the knowledge
without automatically revealing it.

`private.goals` means what the NPC wants. `private.secrets` means what the NPC
is hiding. `private.knowledge` means what facts the NPC knows from its own
perspective. Runtime `inner_portraits` means how the NPC sees someone else.

Private data is character cognition; it is not an automatic public fact and not
a direct state mutation channel.

## Player Knowledge

`clue.discovered` derives `player_knowledge.updated`. A player can only
`present_clue` when both are true:

- the clue is present in `session.discovered_clues`
- `player_knowledge.{clue_id}` exists in `session.player_knowledge`

This prevents the UI or a future Agent from using a clue that exists in the case
package but has not entered the player's public knowledge.

## Present Clue

`ask_about` writes `player.asked_about` after Rule Engine validates the subject:

- `target_id`
- `subject_type`
- `subject_id`
- `text`
- `interaction_pressure`
- `knowledge_id` when the subject is a known player clue

`ask_about` is lower-pressure than `present_clue`, but it can still make an NPC
guarded when the subject is sensitive.

Valid `present_clue` writes `player.presented_clue`:

- `target_id`
- `clue_id`
- `knowledge_id`
- `text`
- `interaction_pressure`

The event itself does not mutate clue state. It is an auditable player pressure
or probing action that can influence `AgentContext`, MockAgent reply selection,
Director checking, and Rule Engine application of any proposed actions. It does
not mean the clue proves the target NPC is guilty.

Invalid `ask_about` or `present_clue` writes `rule.rejected` and does not produce
NPC replies or relationship changes.

## Accuse

`accuse` is a formal structured accusation. It contains a `claim_id`, target
character, submitted evidence clue ids, and optional player text. It is evaluated
only by Rule Engine against case-authored `solution_claims.yaml`.

Valid accuse writes:

- `player.accused`
- `accusation.evaluated`

Invalid accuse writes only `rule.rejected`. It does not call AgentGateway, does
not produce `npc.replied`, does not mutate relationships, and does not directly
change `narrative.phase`.

`accusation.evaluated` may contain the configured result, but `StateSummary` must
not expose solution claim configuration or internal truth data.

Narrative resolution v0 is event-driven:

```text
accusation.evaluated(result=correct)
  -> narrative.beat.completed(case_solved)
  -> narrative.phase.changed(reveal -> resolved)
```

The phase transition is still owned by `RuleTriggerSystem` and
`narrative_rules.yaml`.

## Interaction Pressure

`interaction_pressure` is calculated by the backend:

- `talk`: `0.1`
- `ask_about`: `0.3`
- `present_clue`: `0.6`
- associated subject or clue targets the NPC: `+0.2`
- key clue: `+0.1`
- clamp to `0.0 .. 1.0`

`subject_is_sensitive` is true when the subject is associated with the target NPC
or is a key clue.

## Runtime Memory

`memory_candidate.created` is a derived candidate event. It records that a source
event may matter for future agent context, but it is not the stable memory state.

`AgentMemorySnapshot` is the runtime-owned structured memory state reduced from
candidate events. Version 0 only supports `subject_id="player"` and stores:

- `memory_id`
- `subject_id`
- `content`
- `source_event_ids`
- `salience`
- `visibility`
- `last_updated_event_id`
- `created_at`
- `updated_at`

`MemorySnapshotSystem` consumes only `memory_candidate.created`, updates
`session.memory_snapshots`, and writes `agent_memory_snapshot.updated`. Agents,
LLMs, and `AgentIntent.proposed_actions` cannot write memory snapshots.

Runtime-generated memory ids are semantic and stable enough for case-authored
mock dialogue conditions, for example
`memory.player.clue_discovered.scratched_drawer` or
`memory.player.presented_clue.butler.scratched_drawer`. They must not depend on
runtime UUIDs.

Successful accusations also enter this memory path with ids such as
`memory.player.accused.butler.butler_moved_key` and
`memory.player.accusation_evaluated.butler.butler_moved_key.correct`.

This is not vector memory, RAG, an LLM summary, or database persistence. Snapshot
state must remain replayable from `WorldEvent`.

## Private Character Impressions

`CharacterImpression` is private cognition owned by an observer character. It is
not a character-card truth and not a public profile. It records how one NPC sees
the player:

- personality impression
- perceived motive
- suspected knowledge refs
- suspicious points
- trust boundary
- alliance potential
- threat level
- manipulation risk
- usefulness
- tags and confidence

V0 only supports NPC -> player impressions, stored as:

```text
session.character_impressions[npc_id]["player"]
```

Impressions are derived by runtime code from safe event signals:

- `player.asked_about`
- `player.presented_clue`
- `player.accused`
- `relationship.threshold.crossed`
- `director.blocked`
- `accusation.evaluated`

Each change writes `character_impression.updated`. Agents and LLMs may consume
the current target NPC's impressions through `CharacterInnerContext`, but they
cannot directly write or mutate impression state.

Impressions also influence effective disclosure modes inside
`CharacterInnerContext`: high threat or dangerous topics narrow expression,
alliance can allow hints, and relevant evidence can allow partial disclosure for
matching self-knowledge. This projection does not mutate `SessionState` and does
not grant full reveal.

Replay applies `character_impression.updated` directly. It must not re-run
impression derivation.

## WorldEvent Types

- `session.created`
- `player.inspected`
- `player.talked`
- `player.asked_about`
- `player.presented_clue`
- `player.accused`
- `accusation.evaluated`
- `npc.replied`
- `director.blocked`
- `rule.rejected`
- `clue.discovered`
- `relationship.changed`
- `relationship.threshold.crossed`
- `player_knowledge.updated`
- `memory_candidate.created`
- `agent_memory_snapshot.updated`
- `character_impression.updated`
- `narrative.beat.completed`
- `narrative.phase.changed`

## Rule Engine Principles

- Repeated clue discovery is idempotent and does not duplicate
  `clue.discovered`.
- Relationship metrics are clamped to `-1.0 .. 1.0`.
- Relationship threshold crossings are emitted once per session per threshold.
- Agent-proposed phase changes are rejected.
- Accusation result evaluation belongs to Rule Engine, not Agent or LLM output.
- `accuse` does not directly mutate narrative phase.
- All accepted state changes must be represented by `WorldEvent`.
- `replay_events(case, events)` must rebuild equivalent key state and preserve
  event count.
- `agent_memory_snapshot.updated` is replayed from the event log; replay does not
  re-run memory derivation.
- `character_impression.updated` is replayed from the event log; replay does not
  re-run impression derivation.

## Leak Boundary

Public summaries must not expose character `secrets`, character `goals`,
internal character `knowledge`, private character impressions, the
character-card `private` object, clue `truth_status`, forbidden fact text,
blocked terms, `forbidden_facts`, or `solution_claims`.

`StateSummary`, `WorldEvent` payloads, and `player_journey.md` must also not
expose `inner_context` or raw private summaries.
# WorldInfo 事实锚点收束

当前运行时将 `WorldInfo` 作为核心事实锚点使用。`WorldInfo` 不是替代线索、记忆或关系，而是为“可被发现、隐藏、禁说、推断、指控”的事实提供稳定 ID。

## 边界

- `Clue` 是证据，负责描述玩家在场景中发现了什么。
- `WorldInfo` 是事实锚点，负责描述这条证据指向哪个世界事实。
- `PlayerKnowledge` 是玩家已知账本，负责记录玩家通过哪个线索掌握了哪个 `WorldInfo`。
- `ForbiddenFact` 是叙事禁说规则，负责把禁说词和剧情阶段绑定到某个 `WorldInfo`。
- `SolutionClaim` 是正式指控规则，负责声明成立一个指控需要哪些证据和事实锚点。

## 当前链路

```text
inspect hotspot
  -> clue.discovered
  -> clue.reveals_world_info
  -> player_knowledge.updated(world_info_id)
  -> StateSummary.player_knowledge
  -> replay restores same PlayerKnowledge
```

如果某个旧线索没有配置 `reveals_world_info`，运行时会回退到 `player_knowledge.<clue_id>`，用于兼容历史案件包。新案件应显式配置 `reveals_world_info`。

## 配置要求

- `world_info.yaml` 定义稳定事实 ID。
- `clues.yaml` 通过 `reveals_world_info` 引用事实锚点。
- `forbidden_facts.yaml` 通过 `world_info_id` 绑定禁说事实。
- `solution_claims.yaml` 通过 `required_world_info` 绑定指控所需事实。
- Loader 会校验所有引用，悬空引用会导致服务启动失败。

## 设计原则

- 不允许 LLM 创造新的 `WorldInfo`。
- 玩家发现线索不等于掌握全部真相，只能获得线索所揭示的事实锚点。
- 指控必须同时满足证据条件和事实锚点条件。
- 事件日志必须记录 `world_info_id`，保证 replay 后玩家已知账本一致。
