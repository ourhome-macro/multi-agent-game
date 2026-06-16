from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.director.narrative_director import SAFE_SPEECH
from app.domain.models import (
    ActionResponse,
    CasePackage,
    EventType,
    PlayerAction,
    SessionState,
    WorldEvent,
)
from app.runtime.service import ActionService
from app.runtime.tracing import RuntimeTraceBuffer
from app.storage.memory import InMemoryCaseStore, build_state_summary
from app.storage.postgres import (
    ConnectionLike,
    PostgresEventStore,
    PostgresSessionStore,
    StoredWorldEvent,
)


@dataclass(frozen=True)
class PostgresActionRuntime:
    """Replay, handle and persist one action against the database event stream.

    This wrapper keeps the existing ActionService pure over SessionState while making
    the production persistence boundary explicit. It loads the latest committed event
    stream, derives a fresh SessionState, handles the action, then appends only the new
    events with an expected sequence check.
    """

    event_store: PostgresEventStore
    action_service: ActionService
    trace_buffer: RuntimeTraceBuffer | None = None

    def handle(
        self,
        *,
        case: CasePackage,
        session_id: str,
        action: PlayerAction,
        idempotency_key: str | None = None,
    ) -> ActionResponse:
        from app.runtime.replay import replay_events

        request_hash = request_hash_for_action(action)
        if idempotency_key is not None:
            replayed = self.event_store.load_idempotent_response(
                session_id=session_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            if replayed is not None:
                return _response_from_replayed_events(
                    case=case,
                    session_id=session_id,
                    response_events=replayed,
                    all_events=self.event_store.load_stored(session_id),
                )

        stored_before = self.event_store.load_stored(session_id)
        if not stored_before:
            raise KeyError(f"Unknown session_id: {session_id}")
        session = replay_events(case, [item.event for item in stored_before])
        expected_sequence = stored_before[-1].sequence

        if self.trace_buffer is not None:
            self.trace_buffer.clear()
        try:
            response = self.action_service.handle(session=session, action=action)
        except Exception:
            if self.trace_buffer is not None:
                self.trace_buffer.clear()
            raise
        runtime_traces = self.trace_buffer.drain() if self.trace_buffer is not None else []
        if response.new_events:
            stored = self.event_store.append(
                session,
                response.new_events,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                expected_current_sequence=expected_sequence,
                runtime_traces=runtime_traces,
            )
            stored_event_ids = [item.event.id for item in stored]
            response_event_ids = [event.id for event in response.new_events]
            if idempotency_key is not None and stored_event_ids != response_event_ids:
                return _response_from_replayed_events(
                    case=case,
                    session_id=session_id,
                    response_events=stored,
                    all_events=self.event_store.load_stored(session_id),
                )
        elif self.trace_buffer is not None:
            self.trace_buffer.clear()
        return response.model_copy(
            update={
                "state": build_state_summary(case, session),
            }
        )


@dataclass(frozen=True)
class PostgresRuntimeBackend:
    """Route-facing runtime backend backed by PostgreSQL event streams."""

    case_store: InMemoryCaseStore
    session_store: PostgresSessionStore
    event_store: PostgresEventStore
    action_runtime: PostgresActionRuntime
    connection: ConnectionLike | None = None

    def create_session(self, case: CasePackage) -> SessionState:
        return self.session_store.create(case)

    def get_session(self, session_id: str) -> SessionState:
        case = self._case_for_session(session_id)
        return self.session_store.get(session_id, case)

    def handle_action(
        self,
        *,
        session_id: str,
        action: PlayerAction,
        idempotency_key: str | None = None,
    ) -> ActionResponse:
        case = self._case_for_session(session_id)
        return self.action_runtime.handle(
            case=case,
            session_id=session_id,
            action=action,
            idempotency_key=idempotency_key,
        )

    def get_events(self, session_id: str) -> list[WorldEvent]:
        self.get_session(session_id)
        return self.event_store.load(session_id)

    def close(self) -> None:
        close = getattr(self.connection, "close", None)
        if callable(close):
            close()

    def _case_for_session(self, session_id: str) -> CasePackage:
        case_id = self.session_store.get_case_id(session_id)
        return self.case_store.get(case_id)


def request_hash_for_action(action: PlayerAction) -> str:
    payload = action.model_dump(mode="json")
    serialized = json.dumps(
        {"action": payload, "version": 1},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _response_from_replayed_events(
    *,
    case: CasePackage,
    session_id: str,
    response_events: list[StoredWorldEvent],
    all_events: list[StoredWorldEvent],
) -> ActionResponse:
    from app.runtime.replay import replay_events

    response_event_ids = {item.event.id for item in response_events}
    last_sequence = max(item.sequence for item in response_events)
    events_to_state = [item.event for item in all_events if item.sequence <= last_sequence]
    session = replay_events(case, events_to_state)
    new_events = [item.event for item in response_events if item.event.id in response_event_ids]
    accepted = True
    speech: str | None = None
    director_blocked = False
    director_reason: str | None = None

    for event in new_events:
        if event.type == EventType.NPC_REPLIED:
            raw_speech = event.payload.get("speech")
            speech = str(raw_speech) if raw_speech is not None else speech
        elif event.type == EventType.DIRECTOR_BLOCKED:
            accepted = False
            director_blocked = True
            raw_reason = event.payload.get("reason")
            director_reason = str(raw_reason) if raw_reason is not None else None
            raw_speech = event.payload.get("safe_speech")
            speech = str(raw_speech) if raw_speech is not None else SAFE_SPEECH
        elif event.type == EventType.RULE_REJECTED:
            accepted = False

    return ActionResponse(
        session_id=session_id,
        accepted=accepted,
        speech=speech,
        director_blocked=director_blocked,
        director_reason=director_reason,
        new_events=new_events,
        state=build_state_summary(case, session),
    )
