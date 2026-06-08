# Mist Clock Manor Real API Run - 2026-06-06

## Purpose

Run `mist_clock_manor` with the real OpenAI-compatible API backend instead of mock.
This was requested after confirming `.env` contains a usable API key and Xiaomi Mimo
base URL.

## Configuration

- Backend: `real`
- Base URL: `https://api.xiaomimimo.com/v1`
- Model: `mimo-v2.5`
- API style: `chat_completions`
- Runner: `scripts/run_mist_clock_manor_real_api.py`
- Strict mode: enabled
- Silent fallback: disabled for this runner
- Schema repair attempts: `3`

The runner uses `OpenAILLMAgent.generate_strict(...)`. If provider calls, JSON parsing,
schema validation, contract validation, or Director checks fail, the failure is surfaced
instead of being silently converted into a fallback NPC reply.

## First Real Run Finding

The first real API flow did not complete. It failed at the Lin Qichi wine question because
the model returned extra fields inside `disclosure_claims`.

Examples of rejected extra fields:

- `claimed_fact`
- `is_lie`
- `related_clue_ids`
- `content`
- `confidence`

This is a real contract failure, not a network failure and not a Rule Engine failure.
The Python `AgentIntent` schema correctly rejected the output.

## Repair Added

`OpenAILLMAgent.generate_strict(...)` now supports bounded schema repair:

1. Call real provider.
2. Parse JSON.
3. Validate against `AgentIntent` and LLM contract.
4. If schema or contract validation fails, send one repair prompt containing:
   - safe validation error summary
   - invalid output JSON
   - instruction to return only corrected `AgentIntent`
5. Revalidate the repaired output.

The runner used `--schema-repair-attempts 3`.

This is not field stripping. The runtime does not silently delete illegal model output.
The model must produce a valid corrected `AgentIntent`, and the corrected result still goes
through Director and Rule Engine.

## Completed Real API Run

- Session: `09208a5e-572d-4e89-b3e6-0d1ef53d6a9e`
- Trace JSONL: `logs/mist_clock_manor_real_api_latest.jsonl`
- Readable log: `logs/mist_clock_manor_real_api_latest.log`
- Player steps: 27
- Real Agent turns in final session: 21
- Final phase: `resolved`
- Event count: 168
- Memory snapshot count: 26
- Character awareness count: 17

Completed beats:

- `sedative_found`
- `mechanism_exposed`
- `motive_chain_exposed`
- `case_solved`

Discovered clues:

- `bitter_wine`
- `delayed_lock_marks`
- `echo_tape`
- `ruolan_voice_tape`
- `burned_confession`
- `empty_capsules`
- `cut_power_trace`

Player world info:

- `sedative_wine`
- `timed_lock_modified`
- `recording_tape_swapped`
- `jiang_ruolan_recording_exists`
- `fake_confession_plan`
- `heart_medicine_replaced`
- `power_cut_by_shen`

## Director Blocks

The final real API session had 21 Agent turns:

- Allowed by Director: 17
- Blocked by Director: 4

Block reasons:

- `speech_touched_world_info_'timed_lock_modified'_without_a_disclosure_claim`: 1
- `speech_directness_'direct_claim'_exceeds_disclosure_mode_'deflect'`: 1
- `speech_touched_world_info_'heart_medicine_replaced'_without_a_disclosure_claim`: 2

This is the expected safety behavior: the model can produce dialogue, but it cannot bypass
DisclosurePolicy, Director, or Rule Engine authority.

## Trace Result

For the final session, all 21 Agent trace records used:

- `agent_backend = real`
- safe player text hash and length only
- safe `tool_calls` summary only
- `compression_used = true`

Safe tool summary shape:

```json
{
  "tool_name": "search_memory",
  "status": "ok",
  "duration_ms": 0,
  "error_category": null,
  "result_count": 8
}
```

## Problems Exposed

1. Real model schema obedience is not stable enough without repair.
   It repeatedly added extra `disclosure_claims` fields despite strict schema.

2. Context budget is still not truly controlling prompt size.
   The run reported `compression_used=true`, but context ratios remained above 1.0.
   This is known technical debt from phase 3.

3. Director blocks are doing useful work.
   Some real responses touched world info without matching claims or exceeded permitted
   directness. These were blocked rather than leaking into accepted world state.

4. Latest trace files previously appended multiple sessions.
   `scripts/run_mist_clock_manor_real_api.py` now clears explicit trace paths by default
   unless `--no-clear-trace` is passed.

## Judgment

The real API path is now proven to run a full case to resolution, but it is not clean enough
to call production-ready. The most urgent hardening work is:

- make schema repair observable in trace;
- expose provider failure categories in trace;
- implement actual context trimming below the 80 percent budget threshold;
- strengthen prompt/output contract so real models stop inventing `disclosure_claims` fields;
- add a real shadow eval report that separates schema failure, repair success, Director block,
  and Rule Engine outcome.
