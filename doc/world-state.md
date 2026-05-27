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
- `events`

`StateSummary` is a public projection of this state. It is not the authority.

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

## WorldEvent Types

- `session.created`
- `player.inspected`
- `player.talked`
- `player.asked_about`
- `player.presented_clue`
- `npc.replied`
- `director.blocked`
- `rule.rejected`
- `clue.discovered`
- `relationship.changed`
- `relationship.threshold.crossed`
- `player_knowledge.updated`
- `memory_candidate.created`
- `narrative.beat.completed`
- `narrative.phase.changed`

## Rule Engine Principles

- Repeated clue discovery is idempotent and does not duplicate
  `clue.discovered`.
- Relationship metrics are clamped to `-1.0 .. 1.0`.
- Relationship threshold crossings are emitted once per session per threshold.
- Agent-proposed phase changes are rejected.
- All accepted state changes must be represented by `WorldEvent`.
- `replay_events(case, events)` must rebuild equivalent key state and preserve
  event count.

## Leak Boundary

Public summaries must not expose character `secrets`, character `goals`,
internal character `knowledge`, clue `truth_status`, forbidden fact text, blocked
terms, or `forbidden_facts`.
