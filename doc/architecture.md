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
  -> RuleTriggerSystem.evaluate
  -> EventRecorder.append
  -> StateSummary
```

`inspect` does not call an agent. It validates the hotspot and lets Rule Engine
discover legal clues.

`talk` builds an `AgentContext` and calls `AgentGateway`. The gateway defaults to
`MockAgent`; `LLMAgentStub` is only a local placeholder and does not call an
external model.

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
- `app/runtime/replay.py`: rebuilds `SessionState` from `WorldEvent`.
- `app/storage/memory.py`: in-memory case/session stores and `StateSummary`.

## State Authority

Agents can only emit `AgentIntent`. They cannot mutate `SessionState`, world
facts, clues, relationships, narrative phase, or the event log.

`AgentIntent.proposed_actions` must pass the model whitelist and Rule Engine.
Illegal actions produce `rule.rejected` and must not pollute state.

Narrative phase changes are driven by `narrative_rules.yaml` and
`RuleTriggerSystem`, not by agent output.

## Agent Input Safety

Agents receive `AgentContext`, not raw `CasePackage` or `SessionState`.

`AgentContext` intentionally excludes character `secrets`, character `goals`,
internal character `knowledge`, clue `truth_status`, and forbidden fact text.
Forbidden fact scope is represented only by `blocked_fact_ids` and
`revealable_fact_ids`.

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
- event count
