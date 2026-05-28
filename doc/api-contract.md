# API Contract

The current API covers the in-memory backend narrative runtime. It does not call
real LLMs and does not persist sessions to a database.

## Endpoints

- `GET /health`
- `GET /cases`
- `POST /sessions`
- `POST /sessions/{session_id}/actions`
- `GET /sessions/{session_id}/state`
- `GET /sessions/{session_id}/events`

## Create Session

Default case:

```json
{}
```

Specific case:

```json
{ "case_id": "fake_case_002" }
```

The response contains `session_id` and a public `StateSummary`.

## PlayerAction

All player action targets use `target_id`. A payload using `target` is rejected
with 422.

### inspect

```json
{
  "type": "inspect",
  "target_id": "desk"
}
```

`target_id` must be a known scene hotspot. Unknown inspect targets return 404 and
do not write `player.inspected`.

### talk

```json
{
  "type": "talk",
  "target_id": "butler",
  "text": "Where were you?"
}
```

`target_id` must be a known character. Unknown talk targets return 404 and do not
write `player.talked`.

### ask_about

```json
{
  "type": "ask_about",
  "target_id": "butler",
  "subject_type": "clue",
  "subject_id": "scratched_drawer",
  "text": "What about the drawer?"
}
```

`subject_type` must be one of `clue`, `character`, or `scene`.

Rule Engine validates:

- `target_id` is a known character
- clue subjects exist and have been discovered or exist in player knowledge
- character subjects are known characters
- scene subjects are known scenes

If validation succeeds, the runtime writes `player.asked_about` with:

```json
{
  "target_id": "butler",
  "subject_type": "clue",
  "subject_id": "scratched_drawer",
  "text": "What about the drawer?",
  "interaction_pressure": 0.6,
  "knowledge_id": "player_knowledge.scratched_drawer"
}
```

If validation fails, the response returns `accepted=false`, writes
`rule.rejected`, and does not produce `npc.replied` or relationship changes.

### present_clue

```json
{
  "type": "present_clue",
  "target_id": "butler",
  "clue_id": "scratched_drawer",
  "text": "What about these scratch marks?"
}
```

`present_clue` means the player is pressuring or testing an NPC with a known
clue. It does not mean the clue proves the NPC is guilty, and it does not
directly advance the truth or phase.

Rule Engine validates:

- `target_id` is a known character
- `clue_id` exists in the case package
- `clue_id` has already been discovered
- `player_knowledge.{clue_id}` exists

If validation fails, the response returns `accepted=false`, writes
`rule.rejected`, and does not produce `npc.replied` or relationship changes.

If validation succeeds, the runtime writes `player.presented_clue` with payload:

```json
{
  "target_id": "butler",
  "clue_id": "scratched_drawer",
  "knowledge_id": "player_knowledge.scratched_drawer",
  "text": "What about these scratch marks?",
  "interaction_pressure": 0.9
}
```

Then the action enters `AgentGateway -> NarrativeDirector -> RuleEngine`.

### accuse

```json
{
  "type": "accuse",
  "target_id": "butler",
  "claim_id": "butler_moved_key",
  "evidence_clue_ids": [
    "scratched_drawer",
    "dustless_frame",
    "torn_note"
  ],
  "text": "You moved the key and staged the study entry."
}
```

`accuse` is a structured formal accusation. It does not call `AgentGateway`, does
not use an LLM, and does not let an NPC decide whether the accusation is correct.
Rule Engine evaluates the action against `solution_claims.yaml`.

Rule Engine validates:

- `target_id` is a known character
- `claim_id` exists
- claim `target_id` matches action `target_id`
- current narrative phase is allowed by the claim
- `evidence_clue_ids` is not empty
- all submitted evidence ids exist in the case package
- all submitted evidence clues have been discovered
- all submitted evidence clues are present in `player_knowledge`
- submitted evidence covers the claim's `required_evidence`

If validation fails, the response returns `accepted=false`, writes
`rule.rejected`, and does not produce `player.accused`,
`accusation.evaluated`, `npc.replied`, relationship changes, or memory snapshot
pollution.

If validation succeeds, the runtime writes `player.accused`, then
`accusation.evaluated`. The result comes from case-authored configuration, not
natural-language reasoning. `accuse` does not directly change narrative phase.
If `narrative_rules.yaml` defines a matching event-triggered beat, the later
`RuleTriggerSystem` step may write `narrative.beat.completed` and
`narrative.phase.changed`.

## Interaction Pressure

The backend calculates `interaction_pressure`:

- `talk`: base `0.1`
- `ask_about`: base `0.3`
- `present_clue`: base `0.6`
- associated subject or clue targets the NPC: `+0.2`
- key clue: `+0.1`
- final value is clamped to `0.0 .. 1.0`

## Events

Important event types include:

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
- `character_impression.updated`
- `narrative.beat.completed`
- `narrative.phase.changed`

`relationship.changed.payload.current` always contains clamped relationship
metrics in the `-1.0 .. 1.0` range.

`memory_candidate.created` is a candidate memory event derived from important
runtime events. `agent_memory_snapshot.updated` is a runtime-derived update to
stable `session.memory_snapshots`; its actor is `memory_snapshot_system`, and its
payload includes `memory_id`, `subject_id`, `source_event_ids`, `salience`,
`visibility`, and `operation`.

`character_impression.updated` records runtime-derived private NPC -> player
impressions. It includes `observer_id`, `target_id`, subjective impression
fields, confidence, source event ids, and `last_updated_event_id`. It is not
generated directly by Agent or LLM output. See `doc/character-portrait.md` for
details.

## StateSummary

`StateSummary` is the public state view. It may include discovered clues,
completed beats, public relationship metrics, and player knowledge summaries.
It does not expose memory snapshots or private character impressions in v0. It
also does not expose `solution_claims` or accusation truth configuration.

Character `private` data is the NPC's own non-public perspective, not data that
is hidden from that NPC. The API boundary is different: raw private data must
not be returned to players, other NPCs, public summaries, or journey artifacts.
`AgentContext.inner_context` is not part of any public API response.
`LLMAgentContractInput` is internal agent input and is also not part of any
public API response.

Character summaries expose only public role-card fields:

- `id`
- `display_name`
- `public_role`
- `public_description`

It must not expose:

- character `secrets`
- character `goals`
- internal character `knowledge`
- private character impressions
- character-card `private`
- `inner_context`
- clue `truth_status`
- forbidden fact text or blocked terms
- `forbidden_facts`
- `solution_claims`

## Errors

- Unknown `case_id`: 404
- Unknown `session_id`: 404
- Unknown inspect target: 404
- Unknown talk target: 404
- Invalid request schema: 422
- Invalid `ask_about`, `present_clue`, or `accuse` evidence state: 200 with
  `accepted=false` and
  `rule.rejected`
