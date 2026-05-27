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
  solution_claims.yaml
```

## Naming Rules

- Entity identity uses `id`.
- Player action targets use `target_id`.
- Relationship endpoints use `source_id` and `target_id`.
- Clue references use `clue_id`, `discover_clues`, `asked_subject_id`, or
  `presented_clue`.
- Accusation claims use `claim_id`.
- Legacy `source`, `target`, or generic player-action `target` fields are
  rejected.

## characters.yaml

Characters are authored as public/private role cards:

```yaml
- id: butler
  display_name: Han Butler
  public_role: House steward
  public_description: Long-serving steward with access to the study.
  speech:
    style: restrained and polite
    default_tone: formal
    catchphrases: []
    defensive_style: evasive
  personality:
    traits:
      - cautious
      - loyal
      - observant
    pressure_response: conceal
    trust_response: cautious_help
    fear_response: panic_conceal
  private:
    goals:
      - Avoid becoming the prime suspect.
    secrets:
      - Knows the study key moved.
    knowledge:
      - Saw someone approach the desk.
```

Allowed `defensive_style` values are `evasive`, `hostile`, `anxious`, and
`neutral`. Allowed response styles are `answer`, `conceal`, `deflect`, `refuse`,
`panic_conceal`, and `cautious_help`.

The loader still accepts legacy `name`, `role`, `personality`, `speech_style`,
`secrets`, `goals`, and `knowledge` fields and normalizes them into the new card
shape. New case packages should use the explicit public/private structure.

`private` is author-only data. It must not appear in `StateSummary`,
`AgentContext`, player journey Markdown, or runtime events.

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
- `trigger_event_type`
- `trigger_payload`
- `next_phase`

Only `RuleTriggerSystem` may complete beats or advance phase. Agent proposed
`narrative.phase.change` actions are accepted by schema for auditability but are
rejected by Rule Engine.

Event-triggered beats may use `trigger_event_type` and `trigger_payload`.
Example:

```yaml
- id: case_solved
  phase: reveal
  all_completed:
    - hidden_meeting_connected
  trigger_event_type: accusation.evaluated
  trigger_payload:
    target_id: butler
    claim_id: butler_moved_key
    result: correct
  next_phase: resolved
```

The trigger checks the exact event that caused `RuleTriggerSystem.evaluate` to
run. It does not replay derivations or scan arbitrary future events.

## solution_claims.yaml

`solution_claims.yaml` defines authored formal accusation claims. Rule Engine
uses these claims for `PlayerAction.accuse`; Agents and LLMs do not evaluate
accusation correctness.

Example:

```yaml
claims:
  - id: butler_moved_key
    target_id: butler
    required_evidence:
      - scratched_drawer
      - dustless_frame
      - torn_note
    allowed_phases:
      - reveal
    result: correct

  - id: niece_staged_meeting
    target_id: niece
    required_evidence:
      - torn_note
    allowed_phases:
      - reveal
    result: incorrect
```

Validation checks:

- claim ids are unique
- `target_id` references an existing character
- `required_evidence` references existing clues
- `allowed_phases` references declared narrative phases
- `result` is `correct` or `incorrect`

Claim configuration is internal case-author truth data and must not appear in
`StateSummary`.

## Validation

Run:

```powershell
py -3.12 -m app.cases.validate cases
```

Validation checks characters, scenes, clues, hotspots, relationships,
`mock_dialogues`, `forbidden_facts`, `narrative_rules`, `solution_claims`, and
clue reachability.

## Public Summary Safety

`StateSummary` must not return `secrets`, `goals`, internal `knowledge`,
`truth_status`, forbidden fact text, blocked terms, `forbidden_facts`, or
`solution_claims`.
