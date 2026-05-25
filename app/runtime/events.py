from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import EventType, SessionState, WorldEvent


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def make_event(
    *,
    case_id: str,
    session_id: str,
    actor_id: str,
    event_type: EventType,
    payload: dict,
    caused_by_event_id: str | None = None,
) -> WorldEvent:
    return WorldEvent(
        case_id=case_id,
        session_id=session_id,
        actor_id=actor_id,
        type=event_type,
        payload=payload,
        caused_by_event_id=caused_by_event_id,
        created_at=utc_now_iso(),
    )


class EventRecorder:
    def append(
        self,
        session: SessionState,
        *,
        actor_id: str,
        event_type: EventType,
        payload: dict,
        caused_by_event_id: str | None = None,
    ) -> WorldEvent:
        event = make_event(
            case_id=session.case_id,
            session_id=session.id,
            actor_id=actor_id,
            event_type=event_type,
            payload=payload,
            caused_by_event_id=caused_by_event_id,
        )
        session.events.append(event)
        return event
