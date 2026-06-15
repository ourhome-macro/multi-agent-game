from __future__ import annotations

from pathlib import Path

from app.cases.loader import CaseLoader
from app.domain.models import ActionType, PlayerAction, WorldEvent
from app.runtime.postgres_runtime import PostgresActionRuntime
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
    assert store.appended_events[0].session_id == seed_session.id
    assert service_session.events[0].id == seed_session.events[0].id


class _RecordingEventStore:
    def __init__(self, seed_events: list[WorldEvent]) -> None:
        self._events = list(seed_events)
        self.appended_events: list[WorldEvent] = []
        self.expected_current_sequence: int | None = None
        self.idempotency_key: str | None = None

    def load_stored(self, session_id: str) -> list[StoredWorldEvent]:
        return [
            StoredWorldEvent(event=event, sequence=index)
            for index, event in enumerate(self._events, start=1)
            if event.session_id == session_id
        ]

    def append(
        self,
        session: object,
        events: list[WorldEvent],
        *,
        idempotency_key: str | None = None,
        expected_current_sequence: int | None = None,
    ) -> list[StoredWorldEvent]:
        self.appended_events = list(events)
        self.expected_current_sequence = expected_current_sequence
        self.idempotency_key = idempotency_key
        start = len(self._events) + 1
        self._events.extend(events)
        return [
            StoredWorldEvent(event=event, sequence=start + offset)
            for offset, event in enumerate(events)
        ]
