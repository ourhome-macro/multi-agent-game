# LLM Agent Contract

The runtime uses `MockAgent` by default. The LLM Agent Contract defines the safe
input and output protocol used by `LLMAgentStub` and by the disabled-by-default
real LLM adapter.

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
- target-only `inner_portraits`
- `memory_snapshots`
- `relationship_to_player`
- player knowledge
- recent events
- blocked and revealable forbidden fact ids
- action pressure and sensitivity metadata

It must not include raw `CasePackage`, raw `SessionState`, another NPC's private
data, another NPC's impressions, clue `truth_status`, forbidden fact text,
blocked terms, or solution claims.

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

When `validate_llm_agent_output` receives the originating
`LLMAgentContractInput`, it also rejects output that quotes raw target private
text for self-knowledge items whose `DisclosurePolicy.direct_quote_allowed` is
false. The validation error does not include the private text.

The same validator rejects exact quotation of target `inner_portraits` text such
as `personality_impression`, `perceived_motive`, or `trust_boundary`. The LLM may
use impressions to choose a safer intent, but it must not publish the private
portrait verbatim.

## Stub

`LLMAgentStub` now builds `LLMAgentContractInput`, emits a deterministic JSON
payload, and validates it back into `AgentIntent`.

The stub does not call an external model, does not mutate `SessionState`, and
does not reveal target private text.

## Real Adapter v0

`OpenAILLMAgent` is available but disabled by default. It is selected only by
environment:

```text
LLM_BACKEND=real
OPENAI_API_KEY=...
```

Optional:

```text
OPENAI_MODEL=...
```

If `LLM_BACKEND=real` is present without `OPENAI_API_KEY`, `AgentGateway` remains
on `MockAgent`. CI, local tests, and full scenario snapshots therefore continue
to run on `mock` unless explicitly configured otherwise.

The adapter flow is:

```text
AgentContext
  -> build_llm_agent_input
  -> OpenAI Responses API strict JSON request
  -> parse model JSON
  -> validate_llm_agent_output(contract_input)
  -> AgentIntent or safe fallback
```

The strict JSON schema allows only these proposed action families for the real
adapter:

- `clue.discover`
- `relationship.change`

It intentionally does not allow `narrative.phase.change`. The Python validator
still rejects phase changes as a second line of defense.

All adapter failures return a safe refusal intent with empty `proposed_actions`
and no `memory_refs`. Failure includes:

- missing API key when the adapter is constructed directly
- HTTP or transport errors
- malformed response JSON
- schema validation failures
- raw private-text echo
- attempted narrative phase changes

The adapter never writes `WorldEvent`, never mutates `SessionState`, never calls
Rule Engine directly, and never bypasses Narrative Director.

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
- it includes the target NPC's own `inner_portraits`
- it excludes other NPCs' private data and other NPCs' impressions
- `LLMAgentStub` returns a valid `AgentIntent`
- `OpenAILLMAgent` is disabled by default and env-gated
- real adapter failures fall back to a safe `AgentIntent`
- LLM output proposing phase changes is rejected before Rule Engine
- LLM output quoting raw private text is rejected before public output
- StateSummary, WorldEvent payloads, snapshots, and player journey Markdown do
  not expose raw private data
- existing full scenario JSON snapshots and player journey Markdown remain
  stable
