---
id: talk
description: Default NPC turn projection for talk, present_clue, and non-clue ask_about actions.
trigger:
  action_type:
    - talk
    - present_clue
    - ask_about
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
  max_memory_items: 8
  portrait_summary: true
  recent_events: true
disclosure:
  level: normal
  progressive: []
---

Default dialogue retrieval. This skill may expose only already projected memory ids and safe
portrait summary. It must not override Director forbidden facts or memory scope boundaries.
