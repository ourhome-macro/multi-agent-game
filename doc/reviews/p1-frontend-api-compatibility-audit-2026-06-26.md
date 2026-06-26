# P1 Frontend API Compatibility Audit - 2026-06-26

Worker F scope: compatibility and regression audit only. This pass did not edit
`app/api/routes.py`, `app/domain/models.py`, or `app/api/projections.py`.

## Bottom Line

P1 should treat public API DTOs as a route-bound projection layer, not as a
mutation of the internal runtime models. The sharpest risk is
`ActionResponse.new_events`: runtime, Postgres persistence, idempotent replay,
and many backend tests still rely on it being full internal `WorldEvent`
objects. If P1 changes that field in place, it will break event append/replay
before it improves the frontend contract.

## Search Findings

### `/sessions/{id}/events` legacy bare array dependencies

Current route behavior is the P0 envelope:
`PublicEventStreamResponse { session_id, case_id, after_count, next_after_count, has_more, events }`.
There are still old tests and docs that read the endpoint as a raw list:

- `tests/test_runtime.py:238`, `:283`, `:477`, `:3499` iterate directly over
  `events_response.json()`.
- `tests/test_runtime.py:3817` validates each item as a full `WorldEvent`,
  which conflicts with public redaction and the envelope.
- `tests/test_postgres_integration.py:63` and `:97` read `events.json()` as a
  list.
- Older planning docs still mention `GET /sessions/{id}/events` generically,
  while `doc/api-contract.md` already documents the envelope and redaction.

Main-thread action: migrate old tests to `payload["events"]` or keep them on an
internal event-store/replay API when they need full `WorldEvent` fidelity.

### `ActionResponse.new_events` dependencies

Internal dependencies are real and should not be treated as frontend-only:

- `app/runtime/service.py` constructs `ActionResponse(new_events=list[WorldEvent])`.
- `app/runtime/postgres_runtime.py` appends `response.new_events` to the event
  store and reconstructs idempotent responses from stored `WorldEvent`s.
- `tests/test_runtime.py` has many backend assertions over `response.new_events`
  as typed events and full payloads.
- `tests/test_api_runtime_backend.py:88` and
  `tests/test_postgres_integration.py:94`, `:95`, `:276` inspect API-level
  `new_events`.

Current public API still returns `ActionResponse`, so action responses can leak
full event payloads even though `/events` is redacted. Examples include
`player_knowledge.updated.payload.world_info_id` and
`director.blocked.payload.world_info_id` in old tests.

Main-thread action: keep internal `ActionResponse` intact. Add or wire a route
projection such as `PublicActionResponse` at the FastAPI boundary. If the public
field remains named `new_events`, its item type must be `PublicEventStreamItem`,
not `WorldEvent`. If a new field such as `event_stream` or `events` is chosen,
keep a documented deprecation window for frontend clients.

### `StateSummary.world_info_id` exposure

Current internal/public state is still the same `StateSummary`:

- `PlayerKnowledgeSummary.world_info_id` is included in
  `StateSummary.player_knowledge`.
- `EvidenceSummary` inherits `EvidenceAsset.world_info_id`.
- `app/storage/memory.py::build_state_summary` copies these fields directly.
- `PublicStateSummary` and `PublicPlayerKnowledgeSummary` already exist in
  `app/domain/models.py`, but the route layer is not yet using them.

Main-thread action: decide whether `world_info_id` is frontend-safe state. If
not, wire `PublicStateSummary` through route projection and keep the internal
`StateSummary` available for runtime, replay, scenario tests, and admin/debug
surfaces.

### `HTTPException.detail` string dependencies

Current routes mostly emit `detail=str(exc)` or `detail=exc.message`.
Existing tests still bind to string detail:

- `tests/test_runtime.py:236` expects `"Unknown inspect target_id: unknown"`.
- `tests/test_runtime.py:3497` expects `"Unknown talk target_id: ghost"`.
- `tests/test_postgres_integration.py:122` searches for `"different request"`
  in `detail`.

Main-thread action: introduce a structured error object with stable `code` and
human `message`, but keep a compatibility helper or transitional contract for
legacy string `detail` consumers. Do not let raw `KeyError.__str__` formatting
become the public message source.

## Added Low-Conflict Tests

Added `tests/test_frontend_api_p1_regression.py` with compatibility-oriented
scaffold:

- locks `/sessions/{session_id}/events` to the envelope shape;
- reads action response events from either current `new_events` or a future
  projected shape;
- ensures state `world_info_id` keys, if present, stay limited to player
  knowledge/evidence surfaces;
- normalizes both legacy string `detail` and future structured detail.

These tests avoid requiring P1 implementation to already exist, but they give
P1 a guardrail against regressing the P0 public event stream or breaking
frontend error parsing.

## Recommended P1 Merge Order

1. Add projection functions for public action response and public state without
   modifying internal runtime models.
2. Switch only the FastAPI route `response_model`s to public DTOs.
3. Update legacy endpoint tests that consume `/events` as a raw array.
4. Introduce structured errors and update tests to assert `code` plus
   `message`, not exact legacy strings.
5. Run API contract tests, runtime unit tests, and Postgres integration tests
   separately because they validate different layers.
