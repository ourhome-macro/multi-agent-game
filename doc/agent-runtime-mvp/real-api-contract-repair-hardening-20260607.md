# Real API Contract Repair Hardening - 2026-06-07

## Trigger

A real `mist_clock_manor` API run stopped mid-case because the provider returned:

```json
{
  "intent": "deflect"
}
```

`deflect` is valid only as `disclosure_claims[].mode`. It is not a valid top-level
`AgentIntent.intent`.

Allowed top-level intents remain:

- `answer`
- `conceal`
- `lie`
- `refuse`
- `probe`
- `panic`

## Root Cause

The model mixed two nearby contract concepts:

- NPC behavior intent: `answer`, `conceal`, `lie`, `refuse`, `probe`, `panic`
- disclosure mode: `none`, `deny`, `deflect`, `hint`, `partial`, `full`

The runtime correctly rejected the output rather than silently mapping `deflect` to
`conceal`.

## Change

`OpenAILLMAgent` schema repair instructions now explicitly include:

- allowed top-level intent values;
- disclosure mode values;
- a warning that `deflect` is never the top-level intent;
- guidance to preserve safe speech meaning while choosing the nearest valid intent.

This remains repair-by-model, not backend field stripping or silent coercion.

The strict generator also routes JSON parse failures through bounded repair. If a provider
returns a JSON object followed by explanatory text, the runtime asks the model to rewrite
the turn as exactly one `AgentIntent` JSON object. The repaired response still must pass
JSON parsing, Pydantic validation, contract checks, Director review, and Rule Engine.

Repair instructions now include a per-`world_info_id` disclosure mode matrix. This is
needed because a disclosure mode can be globally valid while still forbidden for the
specific NPC, phase, or world fact in the current turn. If the model cannot choose an
allowed mode for that exact `world_info_id`, it must delete the `disclosure_claim`.

## Test Coverage

Added:

- `test_real_llm_agent_repair_prompt_distinguishes_intent_from_disclosure_mode`
- `test_real_llm_agent_repair_prompt_uses_contract_projection_without_extra_keys`
- `test_real_llm_agent_repair_prompt_lists_allowed_disclosure_modes_by_world_info`
- `test_real_llm_agent_repairs_unparseable_json_output_once`

The test simulates a first response with `intent=deflect`, verifies that the repair prompt
contains the disambiguation, and accepts the corrected `intent=conceal`.
