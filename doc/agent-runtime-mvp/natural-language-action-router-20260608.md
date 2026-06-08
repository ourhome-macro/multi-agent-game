# Natural Language Action Router - 2026-06-08

## Purpose

Translate simple player natural language into backend-approved `PlayerAction` objects.

This is an input routing layer. It is not an NPC Agent decision layer, not Director logic,
and not Rule Engine authority.

## Implemented Scope

The router supports:

- checking or investigating an object/place -> `inspect`
- talking to a character -> `talk`
- asking a character about a clue/character/scene -> `ask_about`
- showing a clue to a character -> `present_clue`
- accusing a character -> `accuse`

Examples:

```text
我检查药盒
  -> inspect medicine_box

我和江医生说话，问他刚才为什么回避
  -> talk jiang_yanhui

我问江医生关于空胶囊的事情
  -> ask_about jiang_yanhui clue empty_capsules

把空胶囊给江医生看
  -> present_clue jiang_yanhui empty_capsules

我指控江医生造成了共同死亡链
  -> accuse jiang_yanhui shared_death_chain
```

## Implementation

New module:

- `app/runtime/action_router.py`

Terminal integration:

- `scripts/run_terminal_mvp.py`

Existing explicit commands still take precedence:

```text
ask jiang_yanhui clue empty_capsules
present jiang_yanhui empty_capsules
```

If the input is not a known terminal command and the parser has a loaded case package, it
tries natural language routing.

## Routing Strategy

The first version is deterministic:

- action trigger phrases;
- case character display names, roles, IDs, and common title aliases;
- case clue titles, IDs, and curated clue aliases;
- scene hotspot names, IDs, and curated hotspot aliases;
- solution claim IDs and curated claim aliases.

It does not call an LLM. This keeps routing testable and prevents the input layer from
becoming a black box.

## Clarification

The router does not invent missing entities.

Examples:

```text
我问空胶囊的事
  -> needs clarification: target

把线索给江医生看
  -> needs clarification: clue
```

The terminal currently prints a compact clarification error. A richer UI can later turn
`missing_slots` into candidate choices.

## Boundaries

- Router determines intended action and entity IDs.
- Rule Engine still validates legality, phase, discovered clues, evidence, and claims.
- Director still checks narrative safety and disclosure boundaries.
- NPC Agent still receives only structured `PlayerAction`.

Director should not perform intent recognition. It may precheck a routed action later,
but the current MVP keeps Director unchanged.

## Hardened Contract Tests

The initial smoke test file was replaced by layered router contract tests:

- `tests/test_action_classifier.py`
- `tests/test_entity_resolver.py`
- `tests/test_router_pipeline.py`
- `tests/test_router_clarification.py`
- `tests/test_router_director_precheck.py`
- `tests/test_router_trace.py`

The first batch now covers 140+ router assertions across:

- normal recognition;
- synonymous Chinese expressions;
- `talk` / `ask_about` / `present_clue` boundaries;
- character alias resolution;
- clue and hotspot alias resolution;
- ambiguous input clarification;
- unknown entity rejection;
- multi-action rejection;
- negated accusation handling;
- safe `RouterTrace` summaries.

## Layered Runtime Objects

`ActionRouter` now composes smaller testable objects:

```text
ActionClassifier
  -> ClassifiedAction

EntityResolver
  -> EntityResolveResult

ActionRouter
  -> RouteResult(PlayerAction | clarification | unknown)

RouterTrace
  -> safe observability summary
```

The classifier only determines action type. The resolver only maps aliases to case entity IDs.
The router combines those results into backend `PlayerAction` objects.

This keeps the input layer deterministic and prevents it from silently becoming a planner.

## Multiple Actions

The router does not split or plan compound player input.

Examples:

```text
我先检查药盒，再去问江医生空胶囊
  -> needs_clarification reason=multiple_actions_detected

我检查配电箱，然后把空胶囊给江医生看
  -> needs_clarification reason=multiple_actions_detected
```

The MVP rule is: one player turn maps to one backend action.

## Negation

Accusation markers are not enough to trigger `accuse` when negated.

Examples:

```text
我不觉得江医生是凶手
  -> talk jiang_yanhui

我不指控江医生
  -> unknown
```

This is a hard safety boundary because false-positive accusations can advance or poison the
case state.

## RouterTrace

`RouterTrace` records only safe summaries:

```json
{
  "raw_text_hash": "sha256:...",
  "raw_text_length": 13,
  "recognized_action": "ask_about",
  "target_candidates": ["jiang_yanhui"],
  "subject_candidates": ["empty_capsules"],
  "confidence": 0.82,
  "resolver_strategy": "alias_exact",
  "director_precheck_result": null,
  "reason": null
}
```

It must not record raw player text. The hash is stable for debugging repeated failures without
leaking the original input.

## Director Precheck

`NarrativeDirector.precheck_player_action(...)` was added as a pure decision helper.

It checks player action safety before full execution, including:

- undiscovered clue asked through `ask_about`;
- undiscovered clue shown through `present_clue`;
- claim unavailable in the current narrative phase;
- empty or undiscovered accusation evidence.

The precheck does not write events and does not replace Rule Engine authority. Existing
`ActionService.handle(...)` still lets Rule Engine produce authoritative `rule.rejected`
events for illegal state transitions.
