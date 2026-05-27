# Runtime Architecture

This project is a case-agnostic backend narrative runtime. It loads case
packages, creates in-memory sessions, processes player actions, produces
auditable world events, and returns public state summaries. It still does not use
a real LLM, database persistence, vector memory, or a frontend.

## Startup

```text
FastAPI app
  -> scan cases/*
  -> CaseLoader.load(each directory with case.yaml)
  -> create_runtime(case packages)
  -> InMemoryCaseStore / InMemorySessionStore
  -> API routes
```

Startup fails with `CaseLoadError` when YAML schema validation or cross-reference
validation fails.

## Action Flow

```text
POST /sessions/{id}/actions
  -> PlayerAction
  -> SessionState
  -> build AgentContext
  -> AgentGateway.generate(context)
  -> AgentIntent
  -> NarrativeDirector.validate
  -> RuleEngine.apply_*
  -> DerivedEventSystem.derive
  -> MemorySnapshotSystem.apply
  -> RuleTriggerSystem.evaluate
  -> EventRecorder.append
  -> StateSummary
```

`inspect` does not call an agent. It validates the hotspot and lets Rule Engine
discover legal clues.

`talk` builds an `AgentContext` and calls `AgentGateway`. The gateway defaults to
`MockAgent`; `LLMAgentStub` is only a local placeholder and does not call an
external model.

`ask_about` is a structured inquiry action. Rule Engine validates the subject
reference, writes `player.asked_about`, and then follows the same AgentGateway ->
Director -> Rule Engine path as `talk`.

`present_clue` is the player-facing evidence pressure action. Rule Engine first
validates that `target_id` is a known character, `clue_id` exists, the clue has
been discovered, and the clue has a corresponding `player_knowledge` entry. A
valid action writes `player.presented_clue`, then follows the same agent-backed
path. An invalid `ask_about` or `present_clue` writes `rule.rejected` and does
not produce an NPC reply or relationship change.

`present_clue` is not treated as proof. It only means the player is applying
pressure or testing the NPC with a clue. Narrative truth still advances only
through events and `RuleTriggerSystem`.

`accuse` is the structured formal accusation action. It does not call
`AgentGateway`; Rule Engine validates the authored `claim_id`, current phase, and
player-known evidence, writes `player.accused`, then writes
`accusation.evaluated`. It does not directly mutate narrative phase. Any future
ending or phase transition must be driven by events through `RuleTriggerSystem`.

## Core Modules

- `app/domain/models.py`: Pydantic v2 domain models and API DTOs.
- `app/cases/loader.py`: YAML loading and case package validation.
- `app/agents/context.py`: builds the safe `AgentContext`.
- `app/agents/protocol.py`: defines `AgentProtocol`.
- `app/agents/gateway.py`: single runtime entry point for agent generation.
- `app/agents/mock_agent.py`: deterministic mock implementation.
- `app/agents/llm_stub.py`: schema-safe placeholder for future LLM integration.
- `app/director/narrative_director.py`: blocks forbidden facts from NPC output.
- `app/rules/engine.py`: only authority for real state changes.
- `app/rules/triggers.py`: completes beats and advances phases from events.
- `app/runtime/derivations.py`: derives player knowledge and memory candidates.
- `app/runtime/memory_snapshots.py`: reduces memory candidates into stable
  agent memory snapshots.
- `app/runtime/replay.py`: rebuilds `SessionState` from `WorldEvent`.
- `app/storage/memory.py`: in-memory case/session stores and `StateSummary`.

## State Authority

Agents can only emit `AgentIntent`. They cannot mutate `SessionState`, world
facts, clues, relationships, narrative phase, or the event log.

`AgentIntent.proposed_actions` must pass the model whitelist and Rule Engine.
Illegal actions produce `rule.rejected` and must not pollute state.

Narrative phase changes are driven by `narrative_rules.yaml` and
`RuleTriggerSystem`, not by agent output.

Accusation correctness is authored in `solution_claims.yaml` and evaluated by
Rule Engine. Agents and LLMs do not decide whether a formal accusation is correct.

## Agent Input Safety

Agents receive `AgentContext`, not raw `CasePackage` or `SessionState`.

`AgentContext` intentionally excludes character `secrets`, character `goals`,
internal character `knowledge`, clue `truth_status`, and forbidden fact text.
Forbidden fact scope is represented only by `blocked_fact_ids` and
`revealable_fact_ids`. Asked subjects are represented by `asked_subject_type` and
`asked_subject_id`. Presented evidence is represented by `presented_clue_id` and
`presented_knowledge_id`. Interaction pressure is a backend-calculated scalar in
the `0.0 .. 1.0` range.

`memory_candidate.created` is only a candidate memory event. The runtime-owned
`MemorySnapshotSystem` consumes it and emits `agent_memory_snapshot.updated`,
which updates `session.memory_snapshots`. Agents may read safe player-scoped
memory snapshots through `AgentContext.memory_snapshots`, but they cannot create
or mutate snapshots directly.

## Event Replay

All real state changes and derived runtime facts must be represented as
`WorldEvent`. `replay_events(case, events)` must rebuild equivalent key state:

- case id
- narrative phase
- completed beats
- discovered clues
- relationships
- player knowledge
- memory candidates
- agent memory snapshots
- event count

Replay applies persisted `agent_memory_snapshot.updated` events explicitly. It
does not re-run derivation or snapshot aggregation, so replay preserves event
count and cannot create recursive memory events.
