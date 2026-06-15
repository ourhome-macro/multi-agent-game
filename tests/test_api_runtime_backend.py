from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.routes import create_router
from app.cases.loader import CaseLoader
from app.domain.models import ActionResponse, ActionType, PlayerAction, SessionState, WorldEvent
from app.runtime.service import RuntimeContainer, create_runtime


def test_submit_action_forwards_idempotency_key_to_runtime_backend() -> None:
    case = CaseLoader().load(Path("cases/fake_case_001"))
    container = create_runtime([case])
    session = container.session_store.create(case)
    backend = _RecordingBackend(container=container, session=session)
    runtime = RuntimeContainer(
        case_store=container.case_store,
        session_store=container.session_store,
        action_service=container.action_service,
        rule_engine=container.rule_engine,
        agent_loop=container.agent_loop,
        session_backend=backend,
    )
    client = TestClient(create_router_app(runtime))

    response = client.post(
        f"/sessions/{session.id}/actions",
        headers={"Idempotency-Key": "action-001"},
        json={"type": "inspect", "target_id": "desk"},
    )

    assert response.status_code == 200
    assert backend.idempotency_key == "action-001"
    assert backend.action == PlayerAction(type=ActionType.INSPECT, target_id="desk")


def create_router_app(runtime: RuntimeContainer) -> object:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(create_router(lambda: runtime))
    return app


@dataclass
class _RecordingBackend:
    container: RuntimeContainer
    session: SessionState
    idempotency_key: str | None = None
    action: PlayerAction | None = None

    def create_session(self, case: object) -> SessionState:
        return self.session

    def get_session(self, session_id: str) -> SessionState:
        if session_id != self.session.id:
            raise KeyError(session_id)
        return self.session

    def handle_action(
        self,
        *,
        session_id: str,
        action: PlayerAction,
        idempotency_key: str | None = None,
    ) -> ActionResponse:
        self.idempotency_key = idempotency_key
        self.action = action
        if session_id != self.session.id:
            raise KeyError(session_id)
        return self.container.action_service.handle(session=self.session, action=action)

    def get_events(self, session_id: str) -> list[WorldEvent]:
        return self.session.events

    def close(self) -> None:
        return None
