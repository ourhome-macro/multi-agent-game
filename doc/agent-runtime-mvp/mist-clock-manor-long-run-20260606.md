# Mist Clock Manor Long Run - 2026-06-06

## Purpose

Run the `mist_clock_manor` case after the phase 3 Agent Runtime work, with a longer
player-like investigation path. The run exercises:

- NPC AgentLoop turns
- memory retrieval
- context budget compression
- safe tool trace summaries
- Director blocking
- Rule Engine phase advancement
- final accusation and replayable event chain

## Runtime

- Case: `mist_clock_manor`
- Backend: `mock`
- Trace JSONL: `logs/mist_clock_manor_long_run_20260606_173316.jsonl`
- Readable log: `logs/mist_clock_manor_long_run_20260606_173316.log`
- Session: `2a760e8d-2966-4a61-a4d6-7edd2ea7320a`
- Player steps: 27
- Agent trace turns: 21

## Result

- Final phase: `resolved`
- Completed beats:
  - `sedative_found`
  - `mechanism_exposed`
  - `motive_chain_exposed`
  - `case_solved`
- Event count: 187
- Memory snapshot count: 27
- Character fact awareness count: 17

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

## Notable Director Blocks

1. Jiang Yanhui forbidden probe during `confrontation`.
   The mock output tried to expose `jiang_yanhui_mechanism`; Director blocked it and
   returned safe fallback speech.

2. Jiang Yanhui lock-related responses during `investigation`.
   The mock speech touched `timed_lock_modified` without a disclosure claim, so Director
   blocked the reply. This is contract enforcement, but the mock reply data should be
   improved with auditable disclosure claims if that answer is meant to be allowed.

3. Shen Zhaoye reconstruction replies.
   The mock speech touched `heart_medicine_replaced` without a disclosure claim, so Director
   blocked the reply. This exposed a useful authoring gap in `mock_dialogues.yaml`.

## Trace Observations

Every Agent turn wrote:

- `schema_version`
- `timestamp`
- `turn_id`
- safe `player_text_hash` and `player_text_length`
- `memory_ids_used`
- context budget fields
- `compression_used`
- safe `tool_calls`

The run used compression on the long context path. Tool calls only recorded safe summaries:

```json
{
  "tool_name": "search_memory",
  "status": "ok",
  "duration_ms": 0,
  "error_category": null,
  "result_count": 8
}
```

No raw player text, raw prompt, raw provider response, private text, forbidden fact text,
or solution claims were written to trace.

## Follow-Up

The runtime path is working and can finish the case. The main issue is not runtime failure;
it is content-contract quality:

- mock replies that mention world info need matching `disclosure_claims`, or they should be
  rewritten to avoid touching protected facts.
- Director behavior is strict enough to catch these authoring mismatches.
- The next practical improvement should be a case authoring lint that checks mock/NPC reply
  text against world info claim patterns before runtime.
