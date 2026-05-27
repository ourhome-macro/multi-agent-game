# Runtime Skeleton

The runtime is still intentionally small: no real LLM, no frontend, no database,
and no vector memory. Its purpose is to prove the backend contract for narrative
state, rule execution, event logging, and replay.

## Implemented Scope

- Scans `cases/*` and loads every case package containing `case.yaml`.
- Supports `cases/fake_case_001` and `cases/fake_case_002`.
- Validates case YAML with Pydantic v2 and cross-reference checks.
- Creates in-memory sessions.
- Processes `inspect`, `talk`, `ask_about`, and `present_clue` player actions.
- Unlocks clues through Rule Engine.
- Generates deterministic NPC intents through `AgentGateway` and `MockAgent`.
- Provides `LLMAgentStub` as a non-network placeholder.
- Blocks forbidden NPC output through Narrative Director.
- Applies legal relationship changes with metric clamping.
- Emits `relationship.threshold.crossed` once per threshold per session.
- Derives `player_knowledge.updated` and `memory_candidate.created`.
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
  -> Rule Trigger System evaluates narrative rules
  -> Write WorldEvent
  -> Return StateSummary
```

`inspect` skips agent generation. `talk` uses `AgentGateway.generate(context)`.
`ask_about` validates a clue, character, or scene subject, writes
`player.asked_about`, and then uses the same AgentGateway path. `present_clue`
first passes Rule Engine evidence validation, writes `player.presented_clue`, and
then uses the same AgentGateway path as `talk`.

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
write player action events. Invalid `ask_about` and `present_clue` attempts write
`rule.rejected` and return `accepted=false`.

## Agent Boundary

`ActionService` depends on `AgentGateway`, not `MockAgent` directly.

`AgentGateway` currently supports:

- `mock`: default deterministic backend.
- `llm_stub`: local stub that returns a valid `AgentIntent` without model calls.

`AgentContext` is the only input shape exposed to agents. It must not include raw
`CasePackage`, raw `SessionState`, character secrets, goals, internal knowledge,
clue truth status, or forbidden fact text.

## Replay Requirement

The runtime scenario smoke test records a stable event snapshot and verifies that
replaying those events rebuilds equivalent key state. This protects the rule
chain, derived state, Director blocking, Rule Engine rejection, and phase
progression from accidental drift.
