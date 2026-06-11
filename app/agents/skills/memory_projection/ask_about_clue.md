---
id: ask_about_clue
description: Progressive clue-question projection for discovered evidence and phase-gated disclosure.
trigger:
  action_type: ask_about
  subject_type: clue
include:
  memory_types:
    - episodic
    - belief
  memory_scopes:
    - case
    - session
    - npc_private
    - scene_shared
  memory_layers:
    - core
    - working
forbid:
  memory_scopes:
    - director_audit
  memory_layers:
    - archival
projection:
  max_memory_items: 5
  portrait_summary: true
  recent_events: true
disclosure:
  level: clue_progressive
  progressive:
    - when:
        phase: opening
      include:
        memory_types:
          - episodic
        memory_scopes:
          - case
          - session
          - npc_private
          - scene_shared
        memory_layers:
          - core
          - working
      projection:
        max_memory_items: 2
        portrait_summary: true
        recent_events: true
      disclosure:
        level: low
    - when:
        phase_in:
          - reveal
          - expose
          - confrontation
          - reconstruction
          - resolved
      include:
        memory_types:
          - episodic
          - belief
          - relationship
          - strategy
      projection:
        max_memory_items: 8
      disclosure:
        level: deep
    - when:
        completed_beats_any:
          - hidden_meeting_connected
          - ledger_pattern_found
          - mechanism_exposed
          - motive_chain_exposed
      include:
        memory_types:
          - episodic
          - belief
          - relationship
          - strategy
      projection:
        max_memory_items: 8
      disclosure:
        level: beat_unlocked
    - when:
        subject_clue_discovered: false
      include:
        memory_types: []
      projection:
        max_memory_items: 0
        portrait_summary: false
        recent_events: false
      disclosure:
        level: blocked_unknown_clue
        handoff_to_director: true
---

Clue questions should reveal memory progressively. Unknown clue subjects should not project
memory into the NPC context; runtime validation normally rejects them before agent execution.
