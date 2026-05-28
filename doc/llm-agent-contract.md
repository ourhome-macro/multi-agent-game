# LLM Agent Contract

This runtime still does not call a real LLM. The LLM Agent Contract defines the
safe input and output protocol for a future real LLM backend.

## Goal

The contract allows a future LLM agent to read the same controlled runtime view
as other agents, including target-only inner context, while preserving these
boundaries:

- no direct world-state mutation
- no direct narrative phase change
- no raw private text in public output
- no forbidden fact text or blocked terms in public output
- every `AgentIntent` is checked by Narrative Director
- every `proposed_actions` entry is checked by Rule Engine

## Input

The contract input is `LLMAgentContractInput`:

```python
class LLMAgentContractInput(BaseModel):
    agent_context: AgentContext
    disclosure_constraints: list[LLMDisclosureConstraint]
    required_output_schema: Literal["AgentIntent"] = "AgentIntent"
```

`agent_context` includes:

- current `PlayerAction`
- target public profile
- target-only `CharacterInnerContext`
- `memory_snapshots`
- `relationship_to_player`
- player knowledge
- recent events
- blocked and revealable forbidden fact ids
- action pressure and sensitivity metadata

It must not include raw `CasePackage`, raw `SessionState`, another NPC's private
data, clue `truth_status`, forbidden fact text, blocked terms, or solution
claims.

## Disclosure Constraints

`LLMDisclosureConstraint` is derived from target self-knowledge items and
blocked forbidden fact ids:

```python
class LLMDisclosureConstraint(BaseModel):
    item_id: str
    item_kind: Literal["goal", "secret", "knowledge", "forbidden_fact"]
    allowed_modes: list[DisclosureMode]
    direct_reveal_allowed: bool
    direct_quote_allowed: bool
    related_clue_ids: list[str]
    blocked: bool
```

These constraints control expression, not cognition. A target NPC may know its
own private data, but the LLM must obey the allowed disclosure mode.

## Output

The required output is strict JSON matching `AgentIntent`:

```json
{
  "speech": "natural language reply",
  "intent": "answer | conceal | lie | refuse | probe | panic",
  "emotional_shift": {},
  "proposed_actions": [],
  "memory_refs": []
}
```

Allowed proposed action types remain limited by the runtime model. The LLM
contract is stricter than the generic `AgentIntent` model: it rejects direct
`narrative.phase.change` proposals. Phase progression belongs to
`RuleTriggerSystem`.

## Stub

`LLMAgentStub` now builds `LLMAgentContractInput`, emits a deterministic JSON
payload, and validates it back into `AgentIntent`.

The stub does not call an external model, does not mutate `SessionState`, and
does not reveal target private text.

## Runtime Review Chain

```text
AgentContext + CharacterInnerContext
  -> build_llm_agent_input
  -> LLM or LLMAgentStub emits JSON
  -> validate_llm_agent_output
  -> AgentIntent
  -> NarrativeDirector.validate
  -> RuleEngine.apply_agent_intent
  -> WorldEvent only for accepted runtime changes
```

`accuse` stays outside the agent path. It does not call `AgentGateway`, a real
LLM, or `LLMAgentStub`.

## Test Requirements

The contract must keep these invariants:

- `LLMAgentContractInput` includes the target NPC's own `inner_context`
- it excludes other NPCs' private data
- `LLMAgentStub` returns a valid `AgentIntent`
- LLM output proposing phase changes is rejected before Rule Engine
- StateSummary, WorldEvent payloads, snapshots, and player journey Markdown do
  not expose raw private data
- existing full scenario JSON snapshots and player journey Markdown remain
  stable
