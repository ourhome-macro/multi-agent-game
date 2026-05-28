# Runtime Architecture

This project is a case-agnostic backend narrative runtime. It loads case
packages, creates in-memory sessions, processes player actions, produces
auditable world events, and returns public state summaries. It still does not
call a real LLM by default, use database persistence, use vector memory, or ship
a frontend.

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

Character config now loads as a public/private character card. Public fields
describe the NPC identity and visible behavior. Private goals, secrets, and
internal knowledge are the NPC's own non-public perspective. They are not hidden
from that NPC. Current v0 does not copy the raw private config into public state;
it exposes only a controlled target-only `CharacterInnerContext` inside
`AgentContext`.

Private Character Impression v0 adds runtime-derived NPC -> player portraits to
that private cognition layer. These impressions are subjective observer state,
not character-card truth and not public StateSummary data.

`AgentGateway.from_env()` keeps `mock` as the default backend. An opt-in
real OpenAI adapter can be selected only when both environment variables
are present:

```text
LLM_BACKEND=real
OPENAI_API_KEY=...
```

Without both variables, startup remains on `MockAgent`. `LLM_BACKEND=llm_stub`
selects the local contract stub without any network call.

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
external model. `OpenAILLMAgent` is registered as an opt-in adapter and remains
outside default tests and scenario snapshots.

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
In v0, `accusation.evaluated(result=correct)` can complete a case-resolution beat
declared in `narrative_rules.yaml`.

## Core Modules

- `app/domain/models.py`: Pydantic v2 domain models and API DTOs.
- `app/cases/loader.py`: YAML loading and case package validation.
- `app/agents/context.py`: builds the safe `AgentContext`.
- `app/agents/protocol.py`: defines `AgentProtocol`.
- `app/agents/gateway.py`: single runtime entry point for agent generation.
- `app/agents/mock_agent.py`: deterministic mock implementation.
- `app/agents/llm_contract.py`: future LLM input/output safety contract.
- `app/agents/llm_stub.py`: schema-safe placeholder for future LLM integration.
- `app/agents/real_llm_agent.py`: disabled-by-default OpenAI adapter that emits
  only validated `AgentIntent` or a safe fallback.
- `app/director/narrative_director.py`: blocks forbidden facts from NPC output.
- `app/rules/engine.py`: only authority for real state changes.
- `app/rules/triggers.py`: completes beats and advances phases from events.
- `app/runtime/derivations.py`: derives player knowledge, memory candidates, and
  private character impressions.
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
Rule Engine also does not directly set a resolved phase; it only emits
`accusation.evaluated`, which can be consumed by `RuleTriggerSystem`.

## Agent Input Safety

Agents receive `AgentContext`, not raw `CasePackage` or `SessionState`.

`AgentContext` intentionally excludes character `secrets`, character `goals`,
internal character `knowledge`, clue `truth_status`, and forbidden fact text.
Forbidden fact scope is represented only by `blocked_fact_ids` and
`revealable_fact_ids`. Asked subjects are represented by `asked_subject_type` and
`asked_subject_id`. Presented evidence is represented by `presented_clue_id` and
`presented_knowledge_id`. Interaction pressure is a backend-calculated scalar in
the `0.0 .. 1.0` range.

`AgentContext.target_profile` is built from `AgentCharacterView`, not raw
`CharacterConfig`. It may include public identity, public description,
speech style, visible traits, defensive style, and pressure/trust/fear response
styles. It must not include `private`, goals, secrets, internal knowledge, truth
status, forbidden fact text, or solution claims.

`AgentContext.inner_context` is a target-only `CharacterInnerContext`. It
contains controlled self-knowledge items for the target NPC and disclosure
policy metadata. It must not contain another NPC's private data, must not be
returned through public APIs, and must not be copied into `WorldEvent`.

The inner context represents what the target NPC knows about itself, while
Narrative Director still controls outward speech and Rule Engine still controls
all accepted state changes.

`CharacterInnerContext.inner_portraits` contains only the current target NPC's
own `CharacterImpression` records. V0 supports NPC -> player impressions only.
`AgentContext.recent_events` filters out `character_impression.updated` events so
private portraits do not leak from one NPC context to another.

`memory_candidate.created` is only a candidate memory event. The runtime-owned
`MemorySnapshotSystem` consumes it and emits `agent_memory_snapshot.updated`,
which updates `session.memory_snapshots`. Agents may read safe player-scoped
memory snapshots through `AgentContext.memory_snapshots`, but they cannot create
or mutate snapshots directly.

`character_impression.updated` is a runtime-derived private cognition event.
It is created from safe event signals such as `player.asked_about`,
`player.presented_clue`, `player.accused`, `relationship.threshold.crossed`,
`director.blocked`, and `accusation.evaluated`. LLMs can consume the current
target NPC's impression view, but they cannot directly write impression state.

`LLMAgentContractInput` wraps `AgentContext` with explicit disclosure
constraints for future real LLM use. `validate_llm_agent_output` requires strict
`AgentIntent` JSON and rejects LLM-proposed narrative phase changes before Rule
Engine.

When the real adapter is enabled, it sends `LLMAgentContractInput`, requests
strict JSON, validates the returned payload with `validate_llm_agent_output`, and
falls back to a safe refusal on API errors, malformed JSON, validation failures,
phase-change proposals, or raw private-text echo. The adapter does not write
events and does not bypass Narrative Director or Rule Engine.

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
- private character impressions
- event count

Replay applies persisted `agent_memory_snapshot.updated` events explicitly. It
does not re-run derivation or snapshot aggregation, so replay preserves event
count and cannot create recursive memory events.

Replay also applies persisted `character_impression.updated` events explicitly.
It does not re-run impression derivation.
