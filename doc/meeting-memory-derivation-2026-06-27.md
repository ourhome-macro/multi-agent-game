# Meeting Memory Derivation 2026-06-27

This slice derives meeting events into memory candidates only. It does not change
meeting projection state, clue unlock state, narrative phase, or verdict rules.

## Rules

- `meeting.message.posted`
  - Player speech and public evidence messages derive `scene_shared/working`
    episodic memory.
  - `MemoryScope` currently has no `meeting_shared`, so `scene_shared` is the
    safest existing scope. Visibility is constrained to
    `SessionState.meeting.participant_ids`.
  - Public evidence messages include `clue_id/world_info_id` metadata only when
    the player already discovered or knows that clue.
- NPC `meeting.message.posted`
  - NPC speech derives that NPC's own `npc_private/working` episodic memory.
  - `owner_character_id` and `visible_to_character_ids` both stay on the
    speaking NPC.
- `meeting.vote.cast`
  - Votes derive `scene_shared/working` belief memory.
  - The model has no `meeting_vote` authority source, so the derivation uses the
    existing `npc_hearsay` source.
  - The memory is `authority=non_authoritative` with `confidence=0.45`, never
    above `0.5`.

## State Boundary

The only write path is:

```text
meeting.* WorldEvent
  -> DerivedEventSystem
  -> memory_candidate.created
  -> MemorySnapshotSystem
  -> agent_memory_snapshot.updated
```

This path never writes:

- `clue.discovered`
- `player_knowledge.updated`
- `narrative.phase.changed`
- `meeting.verdict.*`
- extra `SessionState.meeting` fields

## Metadata Boundary

`MemoryCandidateState.metadata` does not allow meeting-specific keys such as
`meeting_id`, `speaker_id`, `message_kind`, `voter_id`, or `choice`. Those
retrieval anchors are stored in `topic_tags` instead.

Vote memory never copies `clue_id`, `world_info_id`, `phase_id`, or `phase_ids`
from the source payload. A vote cannot bypass the evidence chain or phase rules.
