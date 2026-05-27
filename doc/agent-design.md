# Agent Design

The current runtime still does not call a real LLM. Agent behavior is routed
through a stable interface so MockAgent and a future LLMAgent can share the same
input and output contract.

## Entry Point

All agent implementations use the same protocol:

```python
generate(context: AgentContext) -> AgentIntent
```

`AgentGateway` is the only runtime entry point for agent generation. The default
backend is `MockAgent`. `LLMAgentStub` is present only as a schema-safe placeholder
and does not call external services.

Current talk flow:

```text
PlayerAction(talk)
  -> build_agent_context(case, session, action)
  -> AgentGateway.generate(context)
  -> AgentIntent
  -> NarrativeDirector.validate
  -> RuleEngine.apply_agent_intent
```

`ActionService` must not call `MockAgent` directly.

## AgentContext

`AgentContext` is the controlled view exposed to agents. It includes:

- `case_id`
- `session_id`
- `target_agent_id`
- `current_phase`
- `completed_beats`
- `discovered_clues`
- `player_knowledge`
- `relationship_to_player`
- `relationship_thresholds_crossed`
- `recent_events`
- `memory_candidates`
- `blocked_fact_ids`
- `revealable_fact_ids`

For the current mock implementation it also includes case-authored reply
configuration:

- `player_action`
- `target_profile`
- `default_speech`
- `default_intent`
- `reply_options`
- `fallback_relationship_delta`

`target_profile` is a public `AgentCharacterView`. It does not contain character
`secrets`, `goals`, or internal `knowledge`.

Case packages may still define `forbidden_test_speech` as a local fixture for
mock-only Director tests, but that field is not copied into `AgentContext`.

## Safety Boundary

`AgentContext` must not contain:

- character `secrets`
- character `goals`
- internal character `knowledge`
- clue `truth_status`
- `forbidden_facts` with original text or blocked terms

Forbidden fact visibility is represented only by IDs:

- `blocked_fact_ids`
- `revealable_fact_ids`

The original forbidden fact text remains in the case package and is only used by
`NarrativeDirector` for output validation.

## AgentIntent

Agent output must always be structured:

```json
{
  "speech": "natural language reply",
  "intent": "answer | conceal | lie | refuse | probe | panic",
  "emotional_shift": {},
  "proposed_actions": [],
  "memory_refs": []
}
```

`AgentIntent.proposed_actions` are not state changes. They are requests that must
pass the whitelist and Rule Engine validation before any real state can change.

Allowed proposed action types:

- `clue.discover`
- `relationship.change`
- `narrative.phase.change`

`narrative.phase.change` is intentionally accepted by the schema so it can be
audited, but Rule Engine rejects it. Narrative phase changes can only come from
`narrative_rules.yaml` through `RuleTriggerSystem`.

## Implementations

`MockAgent` consumes `AgentContext` and selects deterministic configured replies
from the case package. It can vary speech and proposed actions by phase,
discovered clues, and relationship metrics.

`LLMAgentStub` returns a valid `AgentIntent` without calling an external model and
without mutating `SessionState`. It exists to lock the future LLM integration
contract before adding real model calls.
