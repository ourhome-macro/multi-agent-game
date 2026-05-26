from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, status

from app.domain.models import (
    ActionResponse,
    CaseMeta,
    CreateSessionRequest,
    CreateSessionResponse,
    PlayerAction,
    StateSummary,
    WorldEvent,
)
from app.runtime.errors import ActionValidationError
from app.runtime.service import RuntimeContainer
from app.storage.memory import build_state_summary


def get_runtime() -> RuntimeContainer:
    raise RuntimeError("Runtime dependency is not configured")


def create_router(runtime_dependency: Callable[[], RuntimeContainer] = get_runtime) -> APIRouter:
    router = APIRouter()
    runtime_dep = Depends(runtime_dependency)

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/cases", response_model=list[CaseMeta])
    def list_cases(runtime: RuntimeContainer = runtime_dep) -> list[CaseMeta]:
        return [case.meta for case in runtime.case_store.list()]

    @router.post("/sessions", response_model=CreateSessionResponse)
    def create_session(
        request: CreateSessionRequest,
        runtime: RuntimeContainer = runtime_dep,
    ) -> CreateSessionResponse:
        case_id = request.case_id or runtime.case_store.default_case_id()
        try:
            case = runtime.case_store.get(case_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        session = runtime.session_store.create(case)
        return CreateSessionResponse(
            session_id=session.id,
            state=build_state_summary(case, session),
        )

    @router.get("/sessions/{session_id}/state", response_model=StateSummary)
    def get_state(
        session_id: str,
        runtime: RuntimeContainer = runtime_dep,
    ) -> StateSummary:
        try:
            session = runtime.session_store.get(session_id)
            case = runtime.case_store.get(session.case_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        return build_state_summary(case, session)

    @router.post("/sessions/{session_id}/actions", response_model=ActionResponse)
    def submit_action(
        session_id: str,
        action: PlayerAction,
        runtime: RuntimeContainer = runtime_dep,
    ) -> ActionResponse:
        try:
            session = runtime.session_store.get(session_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        try:
            return runtime.action_service.handle(session=session, action=action)
        except ActionValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=exc.message,
            ) from exc

    @router.get("/sessions/{session_id}/events", response_model=list[WorldEvent])
    def get_events(
        session_id: str,
        runtime: RuntimeContainer = runtime_dep,
    ) -> list[WorldEvent]:
        try:
            session = runtime.session_store.get(session_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        return session.events

    return router
