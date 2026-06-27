# Runtime Trace Schema v2

## Why This Exists

Trace v1 proved that the runtime could be replayed at the metadata level, but it did
not make the real LLM contribution visible enough. Seeing only `agent_backend=real`
and `duration_ms` is insufficient when debugging NPC dialogue quality.

Trace v2 adds the final player-visible NPC speech and the selected model name.

## New Fields

Trace records now use:

```json
{
  "schema_version": 2,
  "model": "deepseek-v4-flash",
  "public_speech": "I can answer only what I know directly.",
  "public_speech_source": "npc"
}
```

`public_speech_source` is one of:

- `npc`: Director accepted the NPC intent, and `public_speech` is the final NPC speech
  shown to the player.
- `director_safe_fallback`: Director blocked the NPC intent, and `public_speech` is the
  safe fallback shown to the player.
- `null`: no player-visible NPC speech was produced for that traced turn.

## Safety Rule

Trace v2 records only final public speech. It must not record:

- raw provider response text;
- rejected speech before Director review;
- player free text;
- prompt content;
- private NPC card text outside the acting NPC projection;
- forbidden fact text;
- solution claim text;
- full tool arguments or full tool results.

This means a blocked LLM leak should appear as:

```json
{
  "director_allowed": false,
  "public_speech": "I cannot discuss that right now.",
  "public_speech_source": "director_safe_fallback"
}
```

The original rejected speech must not be present in JSONL or readable `.log`.

## Readable Log

The `.log` renderer now includes:

```text
backend=real model=deepseek-v4-flash ... speech_source=npc speech=...
```

Readable logs keep one trace record per line. If the public speech contains line breaks,
the renderer escapes them as `\n` or `\r`.

## Privacy Impact

This is no longer metadata-only trace once `public_speech` is enabled. It still avoids
raw player text and rejected private leakage, but it does store generated dialogue that
was shown to the player. Production should eventually add retention controls and an
environment switch for public dialogue logging.

## LLM Visibility Checklist

A real API turn should now be identifiable by:

- `agent_backend = real`
- `model = <provider model name>`
- `duration_ms > 0`
- `intent_type`
- `public_speech`
- `public_speech_source`
- Director allow/block outcome

## Schema v5 LLM Error Fields

Runtime trace schema v5 records sanitized real LLM fallback metadata and the
safe `npc_skill_projection` summary:

- `llm_fallback_used`
- `llm_error_type`
- `llm_error_message_sanitized`
- `schema_validation_errors`
- `npc_skill_projection`

These fields must not contain raw provider response text, full prompt content,
player free text, forbidden facts, safe fragment summary, skill body, memory
content, or private NPC card text. They are only operational diagnostics for
failed real LLM turns and selected NPC skill boundaries.
