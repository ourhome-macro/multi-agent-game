# NPC Observation and Hearsay Derived Memory

Date: 2026-06-27

## Scope

This slice extends `DerivedEventSystem` so NPC perception events can create
`memory_candidate.created` events without letting LLM output write memory or
world state directly.

## Event Interfaces

Expected upstream event types:

- `npc.observed`
  - Required payload: `observer_id`, `observed_event_id`
  - Optional payload: `summary` or `content`, `scene_id`, `salience`
  - Produces an episodic `npc_private` working memory candidate for the observer.
  - `source_event_ids` must include both the observation event id and the
    observed world event id.

- `npc.hearsay.received`
  - Required payload: `receiver_id`
  - Optional payload: `speaker_id`, `belief_subject`, `belief_polarity`,
    `summary` or `content`, `confidence`, `salience`
  - Produces a low-authority `belief` memory candidate for the receiver.
  - Confidence is capped at `0.5`.
  - Metadata is forced to `authority_source=npc_hearsay`,
    `authority=non_authoritative`, and `non_authoritative=true`.

## State Boundary

Both paths emit only `memory_candidate.created`. The existing
`MemorySnapshotSystem` remains responsible for generating
`agent_memory_snapshot.updated`.

`npc.hearsay.received` intentionally does not copy clue or phase metadata from
the source payload and does not mutate discovered clues, player knowledge,
character fact awareness, or narrative phase. Hearsay can influence NPC context
as weak private belief only; it cannot unlock clues or advance the case.

## Integration Note

`EventType` does not yet define `npc.observed` or `npc.hearsay.received` in this
workspace. The derivation layer therefore matches these event types by string
value and the tests construct those source events through the expected interface.
The model slice should later add formal enum members with the same string
values.
