from __future__ import annotations

from pathlib import Path

from app.cases.loader import CaseLoader
from app.domain.models import ActionType, PlayerAction, WorldEvent
from app.runtime.postgres_runtime import PostgresActionRuntime, request_hash_for_action
from app.runtime.replay import replay_events
from app.runtime.service import create_runtime
from app.storage.postgres import StoredWorldEvent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


def test_postgres_action_runtime_replays_latest_stream_and_appends_new_events() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    seed_session = runtime.session_store.create(case)
    store = _RecordingEventStore(seed_session.events)
    service_session = replay_events(case, seed_session.events)

    wrapper = PostgresActionRuntime(
        event_store=store,  # type: ignore[arg-type]
        action_service=runtime.action_service,
    )
    response = wrapper.handle(
        case=case,
        session_id=seed_session.id,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
        idempotency_key="inspect-desk",
    )

    assert response.accepted is True
    assert store.appended_events
    assert store.expected_current_sequence == 1
    assert store.idempotency_key == "inspect-desk"
    assert store.request_hash == request_hash_for_action(
        PlayerAction(type=ActionType.INSPECT, target_id="desk")
    )
    assert store.appended_events[0].session_id == seed_session.id
    assert service_session.events[0].id == seed_session.events[0].id


def test_postgres_action_runtime_replays_idempotent_response_without_regenerating() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    seed_session = runtime.session_store.create(case)
    action = PlayerAction(type=ActionType.INSPECT, target_id="desk")
    first_response = runtime.action_service.handle(session=seed_session, action=action)
    store = _RecordingEventStore(seed_session.events)
    store.seed_idempotent_response(
        idempotency_key="inspect-desk",
        request_hash=request_hash_for_action(action),
        response_events=first_response.new_events,
    )
    fail_service = _FailingActionService()

    wrapper = PostgresActionRuntime(
        event_store=store,  # type: ignore[arg-type]
        action_service=fail_service,  # type: ignore[arg-type]
    )
    response = wrapper.handle(
        case=case,
        session_id=seed_session.id,
        action=action,
        idempotency_key="inspect-desk",
    )

    assert response.accepted is True
    assert [event.id for event in response.new_events] == [
        event.id for event in first_response.new_events
    ]
    assert response.state.event_count == len(seed_session.events)
    assert store.appended_events == []


class _RecordingEventStore:
    def __init__(self, seed_events: list[WorldEvent]) -> None:
        self._events = list(seed_events)
        self.appended_events: list[WorldEvent] = []
        self.expected_current_sequence: int | None = None
        self.idempotency_key: str | None = None
        self.request_hash: str | None = None
        self._idempotent_response: dict[tuple[str, str, str], list[StoredWorldEvent]] = {}

    def load_stored(self, session_id: str) -> list[StoredWorldEvent]:
        return [
            StoredWorldEvent(event=event, sequence=index)
            for index, event in enumerate(self._events, start=1)
            if event.session_id == session_id
        ]

    def load_idempotent_response(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> list[StoredWorldEvent] | None:
        return self._idempotent_response.get((session_id, idempotency_key, request_hash))

    def seed_idempotent_response(
        self,
        *,
        idempotency_key: str,
        request_hash: str,
        response_events: list[WorldEvent],
    ) -> None:
        by_id = {
            item.event.id: item
            for item in self.load_stored(response_events[0].session_id)
        }
        self._idempotent_response[
            (response_events[0].session_id, idempotency_key, request_hash)
        ] = [by_id[event.id] for event in response_events]

    def append(
        self,
        session: object,
        events: list[WorldEvent],
        *,
        idempotency_key: str | None = None,
        request_hash: str | None = None,
        expected_current_sequence: int | None = None,
    ) -> list[StoredWorldEvent]:
        self.appended_events = list(events)
        self.expected_current_sequence = expected_current_sequence
        self.idempotency_key = idempotency_key
        self.request_hash = request_hash
        start = len(self._events) + 1
        self._events.extend(events)
        return [
            StoredWorldEvent(event=event, sequence=start + offset)
            for offset, event in enumerate(events)
        ]


class _FailingActionService:
    def handle(self, **_: object) -> object:
        raise AssertionError("idempotent replay must not call ActionService.handle")
