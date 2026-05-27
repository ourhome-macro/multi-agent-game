# Case Package Protocol

Case packages are YAML directories under `cases/{case_id}`. The runtime scans
`cases/*` and loads every directory that contains `case.yaml`.

## Files

```text
cases/{case_id}/
  case.yaml
  characters.yaml
  scenes.yaml
  clues.yaml
  relationships.yaml
  forbidden_facts.yaml
  mock_dialogues.yaml
  narrative_rules.yaml
```

## Naming Rules

- Entity identity uses `id`.
- Player action targets use `target_id`.
- Relationship endpoints use `source_id` and `target_id`.
- Clue references use `clue_id`, `discover_clues`, `asked_subject_id`, or
  `presented_clue`.
- Legacy `source`, `target`, or generic player-action `target` fields are
  rejected.

## mock_dialogues.yaml

Each dialogue block is keyed by `character_id`. Replies can be selected by:

- `phase`
- `asked_subject_type`
- `asked_subject_id`
- `presented_clue`
- `min_interaction_pressure`
- `max_interaction_pressure`
- `requires_subject_sensitive`
- `requires_discovered`
- `missing_discovered`
- `requires_memory`
- `missing_memory`
- `min_relationship`
- `max_relationship`

Example:

```yaml
- character_id: butler
  default_speech: I do not know what you mean.
  default_intent: conceal
  relationship_delta_on_talk:
    suspicion: 1
  replies:
    - phase: investigation
      asked_subject_type: clue
      asked_subject_id: scratched_drawer
      min_interaction_pressure: 0.6
      requires_subject_sensitive: true
      speech: Are you asking whether I opened it?
      intent: probe
    - phase: investigation
      requires_memory:
        - memory.player.clue_discovered.scratched_drawer
      missing_memory:
        - memory.player.presented_clue.butler.scratched_drawer
      speech: You already found the drawer marks.
      intent: probe
    - phase: investigation
      presented_clue: scratched_drawer
      requires_discovered:
        - scratched_drawer
      speech: Those scratch marks mean someone forced the drawer.
      intent: probe
      proposed_actions:
        - type: relationship.change
          source_id: butler
          target_id: player
          deltas:
            suspicion: 0.7
```

`asked_subject_id` must reference an existing clue, character, or scene according
to `asked_subject_type`. `presented_clue` must reference an existing clue.

`requires_memory` and `missing_memory` match stable
`AgentMemorySnapshot.memory_id` values exposed through `AgentContext`. These
conditions are deterministic MockAgent selection rules only. They are not vector
memory, RAG, LLM summarization, or a way for agents to mutate memory.

## narrative_rules.yaml

Supported fields:

- `phases`
- `beats`
- `all_completed`
- `min_completed`
- `all_discovered`
- `next_phase`

Only `RuleTriggerSystem` may complete beats or advance phase. Agent proposed
`narrative.phase.change` actions are accepted by schema for auditability but are
rejected by Rule Engine.

## Validation

Run:

```powershell
py -3.12 -m app.cases.validate cases
```

Validation checks characters, scenes, clues, hotspots, relationships,
`mock_dialogues`, `forbidden_facts`, `narrative_rules`, and clue reachability.

## Public Summary Safety

`StateSummary` must not return `secrets`, `goals`, internal `knowledge`,
`truth_status`, forbidden fact text, blocked terms, or `forbidden_facts`.
