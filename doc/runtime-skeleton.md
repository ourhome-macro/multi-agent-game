# Runtime Skeleton

The runtime is still intentionally small: no real LLM, no frontend, no database,
and no vector memory. Its purpose is to prove the backend contract for narrative
state, rule execution, event logging, and replay.

## Implemented Scope

- Scans `cases/*` and loads every case package containing `case.yaml`.
- Supports `cases/fake_case_001` and `cases/fake_case_002`.
- Validates case YAML with Pydantic v2 and cross-reference checks.
- Loads public/private character cards, exposes public character views, and
  builds target-only `CharacterInnerContext` for agent-backed NPC actions.
- Creates in-memory sessions.
- Processes `inspect`, `talk`, `ask_about`, `present_clue`, and `accuse` player
  actions.
- Unlocks clues through Rule Engine.
- Generates deterministic NPC intents through `AgentGateway` and `MockAgent`.
- Provides `LLMAgentStub` as a non-network placeholder.
- Blocks forbidden NPC output through Narrative Director.
- Applies legal relationship changes with metric clamping.
- Emits `relationship.threshold.crossed` once per threshold per session.
- Derives `player_knowledge.updated` and `memory_candidate.created`.
- Reduces `memory_candidate.created` into `agent_memory_snapshot.updated` and
  `session.memory_snapshots`.
- Evaluates structured formal accusations through Rule Engine using
  `solution_claims.yaml`.
- Resolves `fake_case_001` through a `case_solved` beat when
  `accusation.evaluated(result=correct)` is observed by `RuleTriggerSystem`.
- Completes beats and advances phases through `RuleTriggerSystem`.
- Replays event logs with `replay_events(case, events)`.
- Returns public `StateSummary`.

## Runtime Chain

```text
Case Package
  -> Create Session
  -> PlayerAction
  -> Load SessionState / WorldState
  -> Build AgentContext
  -> AgentGateway.generate(context)
  -> AgentIntent
  -> Narrative Director validates narrative boundary
  -> Rule Engine applies legal state changes
  -> Derived Event System derives public knowledge and memory candidates
  -> Memory Snapshot System updates stable runtime memory snapshots
  -> Rule Trigger System evaluates narrative rules
  -> Write WorldEvent
  -> Return StateSummary
```

`inspect` skips agent generation. `talk` uses `AgentGateway.generate(context)`.
`ask_about` validates a clue, character, or scene subject, writes
`player.asked_about`, and then uses the same AgentGateway path. `present_clue`
first passes Rule Engine evidence validation, writes `player.presented_clue`, and
then uses the same AgentGateway path as `talk`.

`accuse` does not use AgentGateway. Rule Engine validates the structured claim
and player-known evidence, writes `player.accused` and `accusation.evaluated`,
then the normal derived-memory and trigger systems run. Accuse v0 does not
directly advance phase or run an ending system.

Narrative resolution v0 is intentionally small: the resolved phase is reached
only by a `narrative_rules.yaml` beat reacting to `accusation.evaluated`, not by
accuse code.

## Public API

- `GET /health`
- `GET /cases`
- `POST /sessions`
- `POST /sessions/{session_id}/actions`
- `GET /sessions/{session_id}/state`
- `GET /sessions/{session_id}/events`

`PlayerAction` target fields are fixed as `target_id`. Relationship endpoints are
fixed as `source_id` and `target_id`.

Unknown inspect targets and unknown talk NPCs return business errors and do not
write player action events. Invalid `ask_about`, `present_clue`, and `accuse`
attempts write `rule.rejected` and return `accepted=false`.

## Agent Boundary

`ActionService` depends on `AgentGateway`, not `MockAgent` directly.

`AgentGateway` currently supports:

- `mock`: default deterministic backend.
- `llm_stub`: local stub that returns a valid `AgentIntent` without model calls.

`AgentContext` is the only input shape exposed to current agents. It must not
include raw `CasePackage`, raw `SessionState`, another NPC's private data, clue
truth status, or forbidden fact text.

`AgentContext.target_profile` is a safe `AgentCharacterView` derived from the
public side of the character card. MockAgent uses it only as fallback behavior
input when no configured `mock_dialogues.yaml` reply matches.

Character `private` is the NPC's own non-public knowledge. Current v0 exposes a
target-only `CharacterInnerContext` to the target NPC through `AgentContext`.
Public speech is still checked by Narrative Director and proposed state changes
by Rule Engine. `inner_context` must not appear in state summaries, event
payloads, player journey Markdown, or other NPC contexts.

`AgentContext.memory_snapshots` contains only safe player-scoped structured
snapshots produced by the runtime. It is not vector memory, RAG, a database, or a
real LLM integration point.

`accuse` is outside the agent boundary in v0. Agents do not judge accusation
correctness and cannot write `player.accused` or `accusation.evaluated`.

## Replay Requirement

The runtime scenario smoke tests record stable event snapshots for
`fake_case_001` and `fake_case_002` and verify that replaying those events
rebuilds equivalent key state. This protects the rule chain, derived state,
Director blocking, Rule Engine rejection, accusation evaluation, narrative
resolution, and phase progression from accidental drift.

The same scenarios also render player journey Markdown files from the actual
`WorldEvent` lists. The Markdown is for human review and must obey the same
public-summary leak boundary.

Replay rebuilds `memory_candidates` and `memory_snapshots` from persisted events.
It does not re-run memory derivation or snapshot aggregation, preserving event
count and preventing recursive memory events.
