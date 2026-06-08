# Mist Clock Manor Real API Branch Runs - 2026-06-07

## Purpose

Run `mist_clock_manor` through the real API backend and confirm that the LLM is actually
participating in NPC turns.

All runs used:

- Backend: `real`
- Model: `mimo-v2.5`
- API style: `chat_completions`
- Trace schema: `2`
- Strict generation: enabled
- Schema/JSON repair attempts: `3`

## Output Hardening Exposed During Runs

The real provider surfaced three non-mock output failures:

1. Top-level `intent` used `deflect`, which is only valid as `disclosure_claims[].mode`.
2. `disclosure_claims` included extra keys such as `confidence` and `source_event_id`.
3. A response returned JSON plus trailing explanatory text.

The runtime now handles these with bounded repair prompts. It still does not silently
coerce fields or accept dirty output. Every repaired output must pass JSON parsing,
Pydantic validation, LLM contract validation, Director review, and Rule Engine.

## Branch A: Correct Resolution

- Trace JSONL: `logs/mist_clock_manor_real_api_success_v2_20260607.jsonl`
- Readable log: `logs/mist_clock_manor_real_api_success_v2_20260607.log`
- Agent turns: `21`
- Director allowed: `16`
- Director blocked: `5`
- Final phase: `resolved`
- Completed beats:
  - `sedative_found`
  - `mechanism_exposed`
  - `motive_chain_exposed`
  - `case_solved`

Representative public LLM speech:

- Lin: `陆澜生今晚说过会给所有人一个结局，可他的结局从来只对他自己有利。`
- Qi: `你以为我不会生气？陆澜生把我写的每一个好句子都当成他自己的血肉，再把壳子留给我。你们当然不懂。`
- Jiang: `从事实层面说，现在任何结论都还太早。`

## Branch B: Wrong Accusation At Reconstruction

- Trace JSONL: `logs/mist_clock_manor_real_api_wrong_line_v2_20260607.jsonl`
- Readable log: `logs/mist_clock_manor_real_api_wrong_line_v2_20260607.log`
- Agent turns: `6`
- Director allowed: `5`
- Director blocked: `1`
- Final phase: `reconstruction`
- Accusation result: `incorrect`
- Completed beats:
  - `sedative_found`
  - `mechanism_exposed`
  - `motive_chain_exposed`

This branch proves that a wrong accusation does not resolve the case even after the major
evidence chain is discovered.

Representative public LLM speech:

- Qi: `你这么快就怀疑我了？我换带子的事…我是做了，但那是为了让他出丑，不是为了杀人。`
- Shen: `配电箱的痕迹说明停电不是天气造成的。别急着问是谁，先问它改变了什么。`

## Branch C: Premature Accusation Rejected

- Trace JSONL: `logs/mist_clock_manor_real_api_premature_accuse_v2_20260607.jsonl`
- Readable log: `logs/mist_clock_manor_real_api_premature_accuse_v2_20260607.log`
- Agent turns: `2`
- Director allowed: `2`
- Director blocked: `0`
- Final phase: `investigation`
- Rule rejection: `claim is not allowed in current narrative phase`
- Completed beats:
  - `sedative_found`

This branch proves that Rule Engine authority still blocks premature accusation. No NPC
Agent turn is created for the rejected accusation.

Representative public LLM speech:

- Qi: `我对他有意见，这很奇怪吗？你来这里，就是为了听我抱怨老板？`
- Lin: `那杯酒原本不是给他的。你可以说我懦弱，但别急着把懦弱写成谋杀。`

## LLM Visibility In Trace

Each real Agent turn now includes:

- `schema_version = 2`
- `agent_backend = real`
- `model = mimo-v2.5`
- `public_speech`
- `public_speech_source`
- Director allow/block outcome

Blocked turns record only Director fallback speech:

```json
{
  "director_allowed": false,
  "public_speech": "I cannot discuss that right now.",
  "public_speech_source": "director_safe_fallback"
}
```

Rejected raw LLM speech is not written into JSONL or readable `.log`.

