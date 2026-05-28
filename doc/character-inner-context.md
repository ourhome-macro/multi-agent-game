# Character Inner Context

Character private data represents non-public information from the character's
own perspective. It is not hidden from the character itself.

The target NPC always knows its own `private.goals`, `private.secrets`, and
`private.knowledge`. Those fields are core character cognition. The runtime
restriction is about outward disclosure and authoritative state writes, not
about whether the NPC has access to its own perspective.

## Private Semantics

`private.goals` are internal motivations. They should influence behavior,
preference, avoidance, pressure response, and decision style. They should not be
quoted verbatim to players or other NPCs by default.

`private.secrets` are facts or claims the NPC has reason to hide. They are
non-public by default. They may become partially expressible only when narrative
phase, trust, player evidence, interaction pressure, and Narrative Director
checks allow it.

`private.knowledge` is what the NPC knows from its own perspective. It is not
the same as `forbidden_facts`, and it is not an absolute speech ban. It cannot
be automatically exposed to players, other NPCs, public summaries, or journey
artifacts.

## Current Runtime Status

Character Card v0 stores `private` in `CasePackage`, but raw private data is not
copied into `StateSummary`, `WorldEvent`, or `player_journey.md`.

That is a deliberate safety boundary for the current no-real-LLM runtime. It
does not mean the NPC is unaware of its own private data.

`AgentContext.inner_context` now contains a target-only controlled self view for
agent-backed `talk`, `ask_about`, and `present_clue` actions. `inspect` and
`accuse` do not need it; `accuse` still does not call `AgentGateway`.

## Character Inner Context v0

Agent-backed NPC generation uses two character views:

- `AgentCharacterView`: public role-card view, safe for current AgentContext and
  public summaries.
- `CharacterInnerContext`: target-only self view, safe only for the target NPC's
  generation step and never returned through public APIs.

Current shape:

```python
class CharacterInnerContext(BaseModel):
    character_id: str
    inner_goals: list[SelfKnowledgeItem]
    inner_secrets: list[SelfKnowledgeItem]
    inner_knowledge: list[SelfKnowledgeItem]
```

`CharacterInnerContext` is not authoritative state. It is a runtime-built input
view. It cannot write facts, clues, relationships, memories, or phase changes.
Any outward state change still has to be proposed through `AgentIntent` and
accepted by Rule Engine.

## SelfKnowledgeView

`SelfKnowledgeItem` is the target NPC's controlled self item. It contains
selected, typed private data for the target character only:

```python
class SelfKnowledgeItem(BaseModel):
    id: str
    kind: Literal["goal", "secret", "knowledge"]
    summary: str
    priority: Literal["low", "medium", "high"]
    related_clue_ids: list[str]
    tags: list[str]
    disclosure_policy: DisclosurePolicy
    source: Literal["character_card"]
```

Production case packages should move private entries from plain strings to
stable authored ids. The loader still normalizes legacy strings to ordered ids
such as `goal_001`, `secret_001`, and `knowledge_001`.

## DisclosurePolicy

`DisclosurePolicy` controls expression, not cognition. It decides whether a
self-known item can be used in outward speech and at what granularity:

```python
class DisclosurePolicy(BaseModel):
    item_id: str
    allowed_modes: list[Literal["none", "evade", "hint", "partial", "full"]]
    min_phase: str | None
    required_player_knowledge: list[str]
    required_relationship_thresholds: list[str]
    min_interaction_pressure: float | None
    forbidden_fact_refs: list[str]
    allow_verbatim: bool = False
```

The safe default is `allowed_modes=["none", "evade"]` and
`allow_verbatim=false`.

Disclosure policy must be evaluated before generation and after generation:

- pre-generation: build only the inner items and disclosure modes the target NPC
  may reason over for this action
- post-generation: Narrative Director verifies the produced speech does not
  exceed allowed disclosure, does not reveal locked forbidden facts, and does
  not contradict case anchors

## Runtime Flow

```text
PlayerAction(talk | ask_about | present_clue)
  -> build public AgentContext
  -> build target-only CharacterInnerContext
  -> AgentGateway.generate(context)
  -> AgentIntent
  -> NarrativeDirector validates outward speech and disclosure
  -> RuleEngine validates proposed_actions
  -> WorldEvent writes only accepted public/runtime facts
```

Only the target NPC receives its own inner context. Other NPCs do not receive
that data unless it has been externalized through allowed speech, memory, or
WorldEvent records.

## MockAgent Fallback

Configured `mock_dialogues.yaml` replies still have priority. Inner context is
only used when no configured reply matches.

Current fallback behavior is deliberately small:

- a high-priority goal tagged `avoid_suspicion` can shift fallback intent toward
  `conceal`
- a asked or presented clue matching `inner_secrets.related_clue_ids` can shift
  fallback intent toward `conceal`
- if `direct_reveal_allowed=false`, fallback speech must not quote the secret
  summary directly

## Non-Leak Requirements

Raw `private` data must not appear in:

- `StateSummary`
- `player_journey.md`
- public API responses
- `WorldEvent` payloads
- other NPCs' contexts
- memory snapshots unless explicitly produced from an allowed public event

`AgentContext.inner_context` may include target self summaries, but it must not
include another NPC's private data and must not be serialized into public
runtime artifacts.

When an NPC is allowed to reveal something, the event log should contain the
allowed outward expression, not the raw private config item.

## Boundary With Rule Engine

Private data can influence `AgentIntent.speech`, `intent`, `emotional_shift`,
and `proposed_actions`. It cannot mutate world state directly.

Rule Engine remains the authority for:

- clue discovery
- relationship changes
- player knowledge
- memory candidates and snapshots through runtime systems
- narrative phase changes through Rule Trigger System
- accusation evaluation

Narrative Director remains the authority for whether outward speech is safe to
emit.
