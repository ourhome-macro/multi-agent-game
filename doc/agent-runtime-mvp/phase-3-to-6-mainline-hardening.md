# Phase 3-6 Mainline Hardening

## Scope

This note records the follow-up hardening after the first phase 3-6 MVP skeleton.
The goal is to make the new runtime pieces participate in the NPC turn mainline,
instead of existing as isolated helper classes.

## Mainline Fixes

1. Retrieved memory now narrows the `AgentContext` passed to `AgentGateway.generate(...)`.
   The model no longer receives every `session.memory_snapshots` entry by default.

2. `CompressedHistoryContext` was added as an `AgentContext` projection.
   It is runtime-only context metadata, not a world fact, and it does not participate in replay.

3. `PromptBuilder` injects compressed history only through safe projection fields:
   `summary`, `important_event_ids`, `important_memory_ids`, `open_threads`, and `risk_notes`.
   It does not inject raw event payloads, raw memory content, private text, or solution claims.

4. `AgentLoop` now records a backend-controlled `search_memory` tool summary in trace.
   The summary contains only:
   `tool_name`, `status`, `duration_ms`, `error_category`, and `result_count`.

5. The real LLM still does not receive open-ended tool calling capability.
   Tool execution remains backend-controlled and read-only for this MVP.

## Tests Added

- `test_agent_loop_passes_retrieved_memory_context_to_gateway`
- `test_prompt_builder_receives_compressed_history_projection`
- `test_agent_loop_trace_includes_safe_tool_summaries`

These tests assert that memory retrieval, compression projection, and tool trace summaries
are part of the AgentLoop path rather than standalone utilities.

## Boundaries Kept

- No vector database.
- No real LLM tool calling.
- No autonomous background tick.
- No production database transaction layer.
- No change to Rule Engine, Director, or EventLog authority boundaries.

## Remaining Production Work

The MVP is runnable and test-covered, but it is not yet production persistence.
The production path still needs PostgreSQL-backed `world_events`, `sessions`,
`memory_snapshots`, and `agent_traces`, plus optimistic locking around a single
`PlayerAction` commit.
