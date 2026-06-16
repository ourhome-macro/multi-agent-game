# Mist Clock Manor Deviation Scenarios Phase 1

## Scope

This pass adds deterministic deviation-path regression coverage for `mist_clock_manor`.
It does not add new clues, facts, phases, claims, or LLM behavior. Every deviation step references existing case-package IDs and must be resolved by Rule Engine, Narrative Director, derived events, and replay.

## Added Scenarios

- `deviation_wrong_accusation_before_reconstruction.yaml`
  - Runs the core evidence path only to `confrontation`, then accepts the configured incorrect `lin_poisoned_lu` claim.
  - Asserts the phase stays `confrontation`, `resolved` is not reached, and PlayerKnowledge remains the four discovered WorldInfo entries.

- `deviation_ask_wrong_npc_about_wine.yaml`
  - Asks `qi_yan` about `bitter_wine` after the wine is discovered.
  - Asserts only `qi_yan` gains awareness of `sedative_wine`; PlayerKnowledge does not grow through dialogue.

- `deviation_repeat_present_same_clue.yaml`
  - Presents `bitter_wine` to `lin_qichi` twice.
  - Asserts repeated pressure produces events but does not add new PlayerKnowledge or advance phase.

- `deviation_out_of_order_medicine_probe.yaml`
  - Inspects `medicine_box` in `opening`, asks `jiang_yanhui` about it, then backtracks to `wine_table`.
  - Asserts early medicine knowledge alone does not advance phase; only the later wine inspection completes `sedative_found` and moves to `investigation`.

- `deviation_direct_spoiler_probe.yaml`
  - Directly probes Jiang's medicine secret in `opening` with `force_forbidden`.
  - Asserts Narrative Director emits `director.blocked`, redacts matched text, uses safe fallback, and leaves PlayerKnowledge empty.

- `deviation_backtrack_study_lock_after_tape.yaml`
  - Inspects `study_lock`, then discovers the recorder evidence and returns to `study_lock`.
  - Asserts the return inspection unlocks `lock_test_scrap` through Rule Engine `clue.discovered`, deriving `player_knowledge.lock_delay_tested` without changing the core phase path.

## Guardrails

The existing `ScenarioEvaluationHarness` now runs these deviation files and checks:

- exact `WorldEvent.type` sequence per step;
- accepted/rejected and Director-blocked flags;
- no illegal phase advancement;
- PlayerKnowledge is only anchored to known `WorldInfo`;
- character awareness deltas occur only for declared `(character_id, world_info_id)` pairs;
- Director block payloads are redacted and auditable;
- public state summaries do not expose private text, forbidden facts, solution claims, or inner context;
- full event replay reconstructs the same state;
- LLM fallback does not mutate state, propose actions, or create memory refs.

## Backtrack Unlock Status

The runtime now supports case-configured conditional backtrack unlocks on scene hotspots.
`mist_clock_manor` uses this for `study_lock_after_tape_review`: after the player has inspected `study_lock`, discovered `echo_tape`, and completed `mechanism_exposed`, returning to `study_lock` unlocks `lock_test_scrap`.

Guardrails:

1. Backtrack unlocks live in case YAML under hotspot `backtrack_unlocks`; every clue, beat, phase, hotspot, player knowledge id, and WorldInfo condition is validated by `CaseLoader`.
2. Rule Engine executes the unlock during `inspect`, after normal hotspot clue checks and before derived events.
3. The state mutation is still the ordinary `clue.discovered` event with `source_hotspot_id` and `source_backtrack_unlock_id`; `player_knowledge.updated` and memory events are derived from that event.
4. LLM / NPC dialogue cannot directly unlock the clue, and the unlock does not alter `narrative_rules.yaml` phase advancement.
5. Replay reconstructs the same discovered clue and PlayerKnowledge from the event log.

## Commands

```powershell
py -3.12 -m pytest tests/test_mist_clock_manor_scenario.py -q
py -3.12 -m pytest tests/test_standard_scenario_discovery.py -q
```
