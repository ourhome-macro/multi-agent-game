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
- `events`

`StateSummary` is a public projection of this state. It is not the authority.
The first runtime memory snapshot version is intentionally not exposed through
`StateSummary`.

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

## Leak Boundary

Public summaries must not expose character `secrets`, character `goals`,
internal character `knowledge`, clue `truth_status`, forbidden fact text, blocked
terms, `forbidden_facts`, or `solution_claims`.
