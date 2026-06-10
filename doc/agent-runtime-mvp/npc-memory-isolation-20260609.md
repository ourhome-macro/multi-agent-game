# NPC Memory Isolation - 2026-06-09

## Scope

This change hardens runtime memory visibility for multi-NPC Agent turns.

It does not add vector memory, LLM reflection, cross-session persistence, social rumor
propagation, or automatic NPC-to-NPC memory sharing.

## Fields

`MemoryCandidateState` and `AgentMemorySnapshot` now carry:

- `owner_character_id`
- `visible_to_character_ids`

These fields are written into `memory_candidate.created` and
`agent_memory_snapshot.updated`, so replay preserves memory isolation.

## Visibility Rules

Player-to-NPC interaction memories are private to the target NPC:

```text
player.asked_about target=jiang_yanhui subject=empty_capsules
  -> owner_character_id=jiang_yanhui
  -> visible_to_character_ids=[jiang_yanhui]

player.presented_clue target=jiang_yanhui clue=empty_capsules
  -> owner_character_id=jiang_yanhui
  -> visible_to_character_ids=[jiang_yanhui]
```

Relationship threshold memories, Director block memories, accusations, and accusation
evaluation memories are also bound to the target/source NPC.

Clue discovery memories remain broadly visible to case NPCs because they represent safe
player-known exploration state, not a private conversation with one NPC.

## Retrieval

`MemoryRetriever.retrieve(...)` now filters by `action.target_id`.

An NPC can retrieve a memory only when:

- the memory has no owner and no explicit visibility list; or
- `owner_character_id == action.target_id`; or
- `action.target_id` appears in `visible_to_character_ids`.

`MemoryRetriever.retrieve_for_director(...)` bypasses NPC visibility for audit. This is a
Director-level view of safe memory summaries, not an NPC context view and not a state write.

## Acceptance Tests

Added `tests/test_npc_memory_isolation.py` with positive and negative coverage:

- Jiang can retrieve a memory created by showing Jiang the empty capsules.
- Shen cannot retrieve Jiang's private interaction memory.
- Director can retrieve that memory for audit.
- Jiang ask-about memory does not appear in Shen's `AgentContext`.
- Shen ask-about memory does not appear in Jiang's `AgentContext`.
- The owning NPC receives its own memory on later turns.
- Tool trace counts respect target visibility.
- Runtime trace `memory_ids_used` excludes another NPC's private memory.
- Replay preserves `owner_character_id` and `visible_to_character_ids`.

## Boundary

This change extends the existing `character_id` isolation idea from character awareness and
inner context into runtime memory snapshots.

The system still does not support true long-term NPC memory persistence. Current memory remains
in-session, event-derived, and replayable.
