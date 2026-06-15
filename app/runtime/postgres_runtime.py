from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import ActionResponse, CasePackage, PlayerAction
from app.runtime.service import ActionService
from app.storage.memory import build_state_summary
from app.storage.postgres import PostgresEventStore


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

    def handle(
        self,
        *,
        case: CasePackage,
        session_id: str,
        action: PlayerAction,
        idempotency_key: str | None = None,
    ) -> ActionResponse:
        from app.runtime.replay import replay_events

        stored_before = self.event_store.load_stored(session_id)
        if not stored_before:
            raise KeyError(f"Unknown session_id: {session_id}")
        session = replay_events(case, [item.event for item in stored_before])
        expected_sequence = stored_before[-1].sequence

        response = self.action_service.handle(session=session, action=action)
        if response.new_events:
            self.event_store.append(
                session,
                response.new_events,
                idempotency_key=idempotency_key,
                expected_current_sequence=expected_sequence,
            )
        return response.model_copy(
            update={
                "state": build_state_summary(case, session),
            }
        )
