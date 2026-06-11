---
id: accuse
description: Formal accusation projection with broad but still bounded player-scoped memory.
trigger:
  action_type: accuse
include:
  memory_types:
    - episodic
    - belief
    - relationship
    - strategy
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
  max_memory_items: 10
  portrait_summary: true
  recent_events: true
disclosure:
  level: accusation
  progressive:
    - when:
        phase: opening
      projection:
        max_memory_items: 4
      disclosure:
        level: premature_accusation
    - when:
        phase_in:
          - reveal
          - expose
          - confrontation
          - reconstruction
          - resolved
      projection:
        max_memory_items: 10
      disclosure:
        level: formal_resolution
---

Accusation retrieval can use more player-scoped memory than casual dialogue, but it still cannot
inject director_audit, archival memory, forbidden facts, or other NPC private state.
