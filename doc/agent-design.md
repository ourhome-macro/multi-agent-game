# Agent Design

The current runtime still uses `MockAgent` by default. Agent behavior is routed
through a stable interface so deterministic mock, local stub, and opt-in real
LLM adapters share the same input and output contract.

## Entry Point

All agent implementations use the same protocol:

```python
generate(context: AgentContext) -> AgentIntent
```

`AgentGateway` is the only runtime entry point for agent generation. The default
backend is `MockAgent`. `LLMAgentStub` is present only as a schema-safe
placeholder and does not call external services. `OpenAILLMAgent` exists as a
disabled-by-default adapter.

Current agent-backed player action flow:

```text
PlayerAction(talk | ask_about | present_clue)
  -> build_agent_context(case, session, action)
  -> AgentGateway.generate(context)
  -> AgentIntent
  -> NarrativeDirector.validate
  -> RuleEngine.apply_agent_intent
```

`ActionService` must not call `MockAgent` directly.

`accuse` is intentionally not agent-backed in v0. It is a structured Rule Engine
action; Agents and LLMs do not decide whether an accusation is correct.

Backend selection is environment-gated:

```text
default -> mock
LLM_BACKEND=llm_stub -> LLMAgentStub
LLM_BACKEND=real + OPENAI_API_KEY=... -> OpenAILLMAgent
```

`LLM_BACKEND=real` without an API key falls back to `mock` at gateway creation so
CI and default local scenario runs cannot accidentally drift into safe refusal
snapshots.

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
- `memory_snapshots`
- `blocked_fact_ids`
- `revealable_fact_ids`
- `asked_subject_type`
- `asked_subject_id`
- `interaction_pressure`
- `subject_is_sensitive`
- `presented_clue_id`
- `presented_knowledge_id`
- `inner_context`

For the current mock implementation it also includes case-authored reply
configuration:

- `player_action`
- `target_profile`
- `default_speech`
- `default_intent`
- `reply_options`
- `fallback_relationship_delta`

`target_profile` is a public `AgentCharacterView`. It does not contain raw
character `private`, `secrets`, `goals`, or internal `knowledge`.

`inner_context` is a target-only `CharacterInnerContext` for the current NPC.
It contains a controlled self view derived from that NPC's own private goals,
secrets, and knowledge. It is never built for another NPC and is not returned
through public APIs.

`AgentCharacterView` currently contains only safe role-card fields:

- `id`
- `display_name`
- `public_role`
- `public_description`
- `speech_style`
- `default_tone`
- `catchphrases`
- `visible_traits`
- `defensive_style`
- `pressure_response`
- `trust_response`
- `fear_response`

`memory_candidates` are raw runtime candidates. `memory_snapshots` are the stable
runtime aggregation produced from those candidates. The current version only
passes player-scoped snapshots (`subject_id="player"`) and does not perform
vector retrieval, RAG, or LLM summarization.

Case packages may still define `forbidden_test_speech` as a local fixture for
mock-only Director tests, but that field is not copied into `AgentContext`.

## Character Inner Context

Character `private` data is the NPC's own non-public perspective. It is not
hidden from the target NPC. A target NPC should know its own goals, secrets, and
knowledge. Runtime-derived private impressions are also part of character
cognition. The runtime limits disclosure and state mutation, not cognition.

Character Inner Context v0 keeps the raw `CharacterPrivateConfig` object out of
public output and exposes only a target-only self view inside `AgentContext`:

```text
CharacterInnerContext
  -> SelfKnowledgeView
  -> DisclosurePolicy
```

`SelfKnowledgeView` / `inner_context` contains only the target NPC's own selected
goals, secrets, knowledge, and `inner_portraits`. It must not contain another
NPC's private data or another NPC's impressions.

`inner_portraits` contains `CharacterImpression` records for how the target NPC
currently sees the player. V0 only supports NPC -> player impressions. A
portrait is not character truth and not public profile data; it is subjective
private cognition that can influence later speech, caution, cooperation, threat
assessment, and branch conditions.

`DisclosurePolicy` decides whether each self-known item can be used as:

- no disclosure
- evasion
- hint
- partial disclosure
- full disclosure

The effective policy considers narrative phase, player-known evidence,
relationship thresholds, interaction pressure, forbidden fact references,
whether verbatim disclosure is allowed, and the target NPC's private impression
of the player. Raw private strings should not become public speech by default.

Impression-aware disclosure v0 applies only inside `CharacterInnerContext`:

- high threat narrows allowed modes toward `deny` and `deflect`
- high alliance potential may allow `hint`
- `has_relevant_evidence` may allow `partial` for matching related clues
- `dangerous_topic_triggered` narrows allowed modes to `deny` and `deflect`
- impressions never grant `full` disclosure or direct quotation

Even with `CharacterInnerContext`, outward speech remains governed by Narrative
Director, and `proposed_actions` remain governed by Rule Engine. Private
knowledge can shape intent; it cannot directly write `WorldEvent`.

`AgentContext.recent_events` filters out `character_impression.updated` events so
one NPC cannot learn another NPC's private portrait through the recent-event
feed. The current target NPC receives its own portraits only through
`inner_context.inner_portraits`.

## Safety Boundary

`AgentContext` must not contain:

- raw `CharacterPrivateConfig`
- another NPC's `secrets`, `goals`, or internal `knowledge`
- another NPC's private impressions
- clue `truth_status`
- `forbidden_facts` with original text or blocked terms
- character secrets, goals, or internal knowledge through memory snapshots
- raw private character-card data in `WorldEvent` payloads

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
Agent intents cannot create `memory_candidate.created` or
`agent_memory_snapshot.updated`; both remain runtime-owned derived events. Agent
intents also cannot create or update `character_impression.updated`; impressions
are derived by runtime systems from accepted events.

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
discovered clues, asked subject, presented clue, interaction pressure, subject
sensitivity, memory snapshots, relationship metrics, and target-owned
`inner_portraits`.

Configured `mock_dialogues.yaml` replies still take priority. When no configured
reply matches, MockAgent falls back to the safe character card:

- `defensive_style=evasive` produces a conceal-style fallback.
- `defensive_style=hostile` produces a refusal fallback.
- `defensive_style=anxious` produces a panic fallback.
- `pressure_response` can force refusal or panic-style concealment.
- `speech_style` and `default_tone` may shape the fallback wording.
- a high-threat `inner_portraits` entry can make fallback speech more guarded
  without quoting portrait text
- `has_relevant_evidence` plus an effective `partial` mode can produce a
  partial-truth style answer without full reveal
- high alliance plus an effective `hint` mode can produce a cautious hint
- `dangerous_topic_triggered` can force refusal or deflection

`mock_dialogues.yaml` reply conditions currently support:

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

`present_clue` does not mean the clue proves the NPC is guilty. It means the
player is using a known clue to pressure, test, or confront the NPC. Truth
progression still belongs to Rule Trigger System and narrative rules.

`LLMAgentStub` returns a valid `AgentIntent` without calling an external model and
without mutating `SessionState`. It builds `LLMAgentContractInput`, emits a
deterministic JSON payload, and validates that payload back into `AgentIntent`.
It exists to lock the future LLM integration contract before adding real model
calls.

`OpenAILLMAgent` is a minimal real backend adapter. It builds
`LLMAgentContractInput`, sends it to the OpenAI Responses API, requests strict
JSON matching `AgentIntent`, runs `validate_llm_agent_output`, and returns the
validated intent. Any failure returns a safe refusal intent with no
`proposed_actions`. Failure includes missing API key, HTTP errors, malformed
JSON, invalid schema, raw private-text echo, and direct narrative phase-change
proposals.

The real adapter does not change the state authority model. Its output still
goes through Narrative Director, and any `proposed_actions` still go through Rule
Engine. It is not used by the full scenario snapshots unless explicitly enabled
through the environment.

See `doc/llm-agent-contract.md` for the full input/output contract.
