from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, Query

from app.api.errors import raise_http_api_error
from app.api.projections import (
    build_public_action_response,
    build_public_case_detail,
    build_public_event_stream,
    build_public_state_summary,
)
from app.domain.models import (
    CaseMeta,
    CreateSessionRequest,
    PlayerAction,
    PublicActionResponse,
    PublicCaseDetail,
    PublicCreateSessionResponse,
    PublicEventStreamResponse,
    PublicRawTextActionResponse,
    PublicStateSummary,
    RawTextActionRequest,
    SessionAffordances,
)
from app.runtime.affordances import build_session_affordances
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

    @router.get("/cases/{case_id}", response_model=PublicCaseDetail)
    def get_case_detail(
        case_id: str,
        runtime: RuntimeContainer = runtime_dep,
    ) -> PublicCaseDetail:
        try:
            case = runtime.case_store.get(case_id)
        except KeyError as exc:
            raise_http_api_error(exc, resource_type="case", resource_id=case_id)
        return build_public_case_detail(case)

    @router.post("/sessions", response_model=PublicCreateSessionResponse)
    def create_session(
        request: CreateSessionRequest,
        runtime: RuntimeContainer = runtime_dep,
    ) -> PublicCreateSessionResponse:
        case_id = request.case_id or runtime.case_store.default_case_id()
        try:
            case = runtime.case_store.get(case_id)
        except KeyError as exc:
            raise_http_api_error(exc, resource_type="case", resource_id=case_id)
        session = runtime.create_session(case)
        return PublicCreateSessionResponse(
            session_id=session.id,
            state=build_public_state_summary(build_state_summary(case, session)),
        )

    @router.get("/sessions/{session_id}/state", response_model=PublicStateSummary)
    def get_state(
        session_id: str,
        runtime: RuntimeContainer = runtime_dep,
    ) -> PublicStateSummary:
        try:
            session = runtime.get_session(session_id)
            case = runtime.case_store.get(session.case_id)
        except (KeyError, UnknownSessionError) as exc:
            raise_http_api_error(exc, resource_type="session", resource_id=session_id)
        return build_public_state_summary(build_state_summary(case, session))

    @router.get("/sessions/{session_id}/affordances", response_model=SessionAffordances)
    def get_affordances(
        session_id: str,
        runtime: RuntimeContainer = runtime_dep,
    ) -> SessionAffordances:
        try:
            session = runtime.get_session(session_id)
            case = runtime.case_store.get(session.case_id)
        except (KeyError, UnknownSessionError) as exc:
            raise_http_api_error(exc, resource_type="session", resource_id=session_id)
        return build_session_affordances(
            case=case,
            session=session,
            rule_engine=runtime.rule_engine,
        )

    @router.post("/sessions/{session_id}/actions", response_model=PublicActionResponse)
    def submit_action(
        session_id: str,
        action: PlayerAction,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        runtime: RuntimeContainer = runtime_dep,
    ) -> PublicActionResponse:
        try:
            return build_public_action_response(
                runtime.handle_action(
                    session_id=session_id,
                    action=action,
                    idempotency_key=idempotency_key,
                )
            )
        except (KeyError, UnknownSessionError) as exc:
            raise_http_api_error(exc, resource_type="session", resource_id=session_id)
        except ActionValidationError as exc:
            raise_http_api_error(exc)
        except StaleSessionSequenceError as exc:
            raise_http_api_error(exc)
        except (IdempotencyConflictError, IdempotencyInProgressError) as exc:
            raise_http_api_error(exc)
        except PostgresPersistenceError as exc:
            raise_http_api_error(exc)

    @router.post("/sessions/{session_id}/raw-actions", response_model=PublicRawTextActionResponse)
    def submit_raw_action(
        session_id: str,
        request: RawTextActionRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        runtime: RuntimeContainer = runtime_dep,
    ) -> PublicRawTextActionResponse:
        try:
            intake = runtime.handle_raw_text(
                session_id=session_id,
                raw_text=request.raw_text,
                idempotency_key=idempotency_key,
            )
        except (KeyError, UnknownSessionError) as exc:
            raise_http_api_error(exc, resource_type="session", resource_id=session_id)
        except ActionValidationError as exc:
            raise_http_api_error(exc)
        except StaleSessionSequenceError as exc:
            raise_http_api_error(exc)
        except (IdempotencyConflictError, IdempotencyInProgressError) as exc:
            raise_http_api_error(exc)
        except PostgresPersistenceError as exc:
            raise_http_api_error(exc)
        return PublicRawTextActionResponse(
            status=intake.status.value,
            action=intake.action,
            response=(
                build_public_action_response(intake.response)
                if intake.response is not None
                else None
            ),
            reason=intake.reason,
            missing_slots=list(intake.missing_slots),
            route_trace=intake.route.trace.to_safe_dict(),
        )

    @router.get("/sessions/{session_id}/events", response_model=PublicEventStreamResponse)
    def get_events(
        session_id: str,
        after_count: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        runtime: RuntimeContainer = runtime_dep,
    ) -> PublicEventStreamResponse:
        try:
            session = runtime.get_session(session_id)
            events = runtime.get_events(session_id)
        except (KeyError, UnknownSessionError) as exc:
            raise_http_api_error(exc, resource_type="session", resource_id=session_id)
        return build_public_event_stream(
            session_id=session.id,
            case_id=session.case_id,
            events=events,
            after_count=after_count,
            limit=limit,
        )

    return router
