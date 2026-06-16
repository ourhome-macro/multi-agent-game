from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.domain.models import (
    ActionResponse,
    CaseMeta,
    CreateSessionRequest,
    CreateSessionResponse,
    PlayerAction,
    RawTextActionRequest,
    RawTextActionResponse,
    StateSummary,
    WorldEvent,
)
from app.runtime.errors import ActionValidationError
from app.runtime.service import RuntimeContainer
from app.storage.memory import build_state_summary
from app.storage.postgres import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    PostgresPersistenceError,
    StaleSessionSequenceError,
    UnknownSessionError,
)


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
        session = runtime.create_session(case)
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
            session = runtime.get_session(session_id)
            case = runtime.case_store.get(session.case_id)
        except (KeyError, UnknownSessionError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        return build_state_summary(case, session)

    @router.post("/sessions/{session_id}/actions", response_model=ActionResponse)
    def submit_action(
        session_id: str,
        action: PlayerAction,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        runtime: RuntimeContainer = runtime_dep,
    ) -> ActionResponse:
        try:
            return runtime.handle_action(
                session_id=session_id,
                action=action,
                idempotency_key=idempotency_key,
            )
        except (KeyError, UnknownSessionError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except ActionValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=exc.message,
            ) from exc
        except StaleSessionSequenceError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except (IdempotencyConflictError, IdempotencyInProgressError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except PostgresPersistenceError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    @router.post("/sessions/{session_id}/raw-actions", response_model=RawTextActionResponse)
    def submit_raw_action(
        session_id: str,
        request: RawTextActionRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        runtime: RuntimeContainer = runtime_dep,
    ) -> RawTextActionResponse:
        try:
            intake = runtime.handle_raw_text(
                session_id=session_id,
                raw_text=request.raw_text,
                idempotency_key=idempotency_key,
            )
        except (KeyError, UnknownSessionError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except ActionValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=exc.message,
            ) from exc
        except StaleSessionSequenceError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except (IdempotencyConflictError, IdempotencyInProgressError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except PostgresPersistenceError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc
        return RawTextActionResponse(
            status=intake.status.value,
            action=intake.action,
            response=intake.response,
            reason=intake.reason,
            missing_slots=list(intake.missing_slots),
            route_trace=intake.route.trace.to_safe_dict(),
        )

    @router.get("/sessions/{session_id}/events", response_model=list[WorldEvent])
    def get_events(
        session_id: str,
        runtime: RuntimeContainer = runtime_dep,
    ) -> list[WorldEvent]:
        try:
            return runtime.get_events(session_id)
        except (KeyError, UnknownSessionError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    return router
