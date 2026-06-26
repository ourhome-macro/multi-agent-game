from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, NoReturn, cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.domain.models import APIErrorCode, APIErrorResponse
from app.runtime.errors import ActionValidationError
from app.storage.postgres import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    PostgresPersistenceError,
    StaleSessionSequenceError,
    UnknownSessionError,
)

CORRELATION_ID_HEADER = "X-Correlation-ID"
MAX_CORRELATION_ID_LENGTH = 128

ExceptionResourceType = Literal["case", "session"]
ExceptionHandler = Callable[[Request, Exception], Response | Awaitable[Response]]


@dataclass(frozen=True)
class APIErrorMapping:
    status_code: int
    body: APIErrorResponse

    @property
    def headers(self) -> dict[str, str]:
        return {CORRELATION_ID_HEADER: self.body.correlation_id}


class StableAPIError(Exception):
    def __init__(self, mapping: APIErrorMapping) -> None:
        super().__init__(mapping.body.message)
        self.mapping = mapping


def resolve_correlation_id(
    *,
    request: Request | None = None,
    correlation_id: str | None = None,
) -> str:
    explicit = _normalize_correlation_id(correlation_id)
    if explicit is not None:
        return explicit
    if request is not None:
        incoming = _normalize_correlation_id(request.headers.get(CORRELATION_ID_HEADER))
        if incoming is not None:
            return incoming
    return str(uuid4())


def build_api_error_mapping(
    *,
    status_code: int,
    code: APIErrorCode,
    message: str,
    retryable: bool,
    correlation_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> APIErrorMapping:
    resolved_correlation_id = resolve_correlation_id(correlation_id=correlation_id)
    return APIErrorMapping(
        status_code=status_code,
        body=APIErrorResponse(
            code=code,
            message=message,
            details=_safe_details(details),
            retryable=retryable,
            correlation_id=resolved_correlation_id,
        ),
    )


def map_exception_to_api_error(
    exc: Exception,
    *,
    resource_type: ExceptionResourceType | None = None,
    resource_id: str | None = None,
    correlation_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> APIErrorMapping:
    if isinstance(exc, KeyError) and resource_type == "case":
        return case_not_found_error(
            case_id=resource_id or _key_error_value(exc),
            correlation_id=correlation_id,
            details=details,
        )
    if isinstance(exc, (KeyError, UnknownSessionError)) and resource_type == "session":
        return session_not_found_error(
            session_id=resource_id or _exception_arg(exc),
            correlation_id=correlation_id,
            details=details,
        )
    if isinstance(exc, UnknownSessionError):
        return session_not_found_error(
            session_id=resource_id or _exception_arg(exc),
            correlation_id=correlation_id,
            details=details,
        )
    if isinstance(exc, ActionValidationError):
        return action_not_allowed_error(
            reason=exc.message,
            correlation_id=correlation_id,
            details=details,
        )
    if isinstance(exc, StaleSessionSequenceError):
        return stale_session_sequence_error(
            correlation_id=correlation_id,
            details=details,
        )
    if isinstance(exc, IdempotencyConflictError):
        return idempotency_conflict_error(
            correlation_id=correlation_id,
            details=details,
        )
    if isinstance(exc, IdempotencyInProgressError):
        return idempotency_in_progress_error(
            correlation_id=correlation_id,
            details=details,
        )
    if isinstance(exc, RequestValidationError):
        return request_validation_error(
            exc,
            correlation_id=correlation_id,
            details=details,
        )
    if isinstance(exc, PostgresPersistenceError):
        return persistence_error(
            correlation_id=correlation_id,
            details=details,
        )
    return internal_error(correlation_id=correlation_id, details=details)


def case_not_found_error(
    *,
    case_id: str | None = None,
    correlation_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> APIErrorMapping:
    return build_api_error_mapping(
        status_code=status.HTTP_404_NOT_FOUND,
        code=APIErrorCode.CASE_NOT_FOUND,
        message="Case not found.",
        retryable=False,
        correlation_id=correlation_id,
        details=_merge_details({"case_id": case_id}, details),
    )


def session_not_found_error(
    *,
    session_id: str | None = None,
    correlation_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> APIErrorMapping:
    return build_api_error_mapping(
        status_code=status.HTTP_404_NOT_FOUND,
        code=APIErrorCode.SESSION_NOT_FOUND,
        message="Session not found.",
        retryable=False,
        correlation_id=correlation_id,
        details=_merge_details({"session_id": session_id}, details),
    )


def action_not_allowed_error(
    *,
    reason: str,
    correlation_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> APIErrorMapping:
    return build_api_error_mapping(
        status_code=status.HTTP_400_BAD_REQUEST,
        code=APIErrorCode.ACTION_NOT_ALLOWED,
        message="Action is not allowed in the current world state.",
        retryable=False,
        correlation_id=correlation_id,
        details=_merge_details({"reason": reason}, details),
    )


def idempotency_conflict_error(
    *,
    correlation_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> APIErrorMapping:
    return build_api_error_mapping(
        status_code=status.HTTP_409_CONFLICT,
        code=APIErrorCode.IDEMPOTENCY_CONFLICT,
        message="Idempotency key conflicts with another request.",
        retryable=False,
        correlation_id=correlation_id,
        details=_merge_details({"reason": "idempotency_key_reused"}, details),
    )


def idempotency_in_progress_error(
    *,
    correlation_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> APIErrorMapping:
    return build_api_error_mapping(
        status_code=status.HTTP_409_CONFLICT,
        code=APIErrorCode.IDEMPOTENCY_IN_PROGRESS,
        message="Idempotency key is still in progress.",
        retryable=True,
        correlation_id=correlation_id,
        details=_merge_details({"reason": "idempotency_key_in_progress"}, details),
    )


def stale_session_sequence_error(
    *,
    correlation_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> APIErrorMapping:
    return build_api_error_mapping(
        status_code=status.HTTP_409_CONFLICT,
        code=APIErrorCode.STALE_SESSION_SEQUENCE,
        message="Session event sequence is stale; refresh state and retry.",
        retryable=True,
        correlation_id=correlation_id,
        details=_merge_details({"retry_after": "refresh_session_state"}, details),
    )


def persistence_error(
    *,
    correlation_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> APIErrorMapping:
    return build_api_error_mapping(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=APIErrorCode.PERSISTENCE_ERROR,
        message="Persistence boundary failed.",
        retryable=True,
        correlation_id=correlation_id,
        details=_merge_details({"boundary": "persistence"}, details),
    )


def request_validation_error(
    exc: RequestValidationError,
    *,
    correlation_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> APIErrorMapping:
    return build_api_error_mapping(
        status_code=422,
        code=APIErrorCode.REQUEST_VALIDATION_ERROR,
        message="Request payload failed validation.",
        retryable=False,
        correlation_id=correlation_id,
        details=_merge_details({"errors": _validation_errors(exc)}, details),
    )


def internal_error(
    *,
    correlation_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> APIErrorMapping:
    return build_api_error_mapping(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=APIErrorCode.INTERNAL_ERROR,
        message="Unexpected server error.",
        retryable=False,
        correlation_id=correlation_id,
        details=_merge_details({"boundary": "api"}, details),
    )


def api_error_response(mapping: APIErrorMapping) -> JSONResponse:
    return JSONResponse(
        status_code=mapping.status_code,
        content=mapping.body.model_dump(mode="json"),
        headers=mapping.headers,
    )


def api_error_response_from_exception(
    exc: Exception,
    *,
    resource_type: ExceptionResourceType | None = None,
    resource_id: str | None = None,
    correlation_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> JSONResponse:
    return api_error_response(
        map_exception_to_api_error(
            exc,
            resource_type=resource_type,
            resource_id=resource_id,
            correlation_id=correlation_id,
            details=details,
        )
    )


def raise_api_error(
    exc: Exception,
    *,
    resource_type: ExceptionResourceType | None = None,
    resource_id: str | None = None,
    correlation_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> NoReturn:
    raise StableAPIError(
        map_exception_to_api_error(
            exc,
            resource_type=resource_type,
            resource_id=resource_id,
            correlation_id=correlation_id,
            details=details,
        )
    )


def http_exception_from_api_error(mapping: APIErrorMapping) -> HTTPException:
    return HTTPException(
        status_code=mapping.status_code,
        detail=mapping.body.model_dump(mode="json"),
        headers=mapping.headers,
    )


def raise_http_api_error(
    exc: Exception,
    *,
    resource_type: ExceptionResourceType | None = None,
    resource_id: str | None = None,
    correlation_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> NoReturn:
    raise http_exception_from_api_error(
        map_exception_to_api_error(
            exc,
            resource_type=resource_type,
            resource_id=resource_id,
            correlation_id=correlation_id,
            details=details,
        )
    )


def install_api_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        StableAPIError,
        cast(ExceptionHandler, stable_api_error_handler),
    )
    app.add_exception_handler(
        RequestValidationError,
        cast(ExceptionHandler, request_validation_error_handler),
    )


async def stable_api_error_handler(_: Request, exc: StableAPIError) -> JSONResponse:
    return api_error_response(exc.mapping)


async def request_validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    correlation_id = resolve_correlation_id(request=request)
    return api_error_response(request_validation_error(exc, correlation_id=correlation_id))


def _normalize_correlation_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:MAX_CORRELATION_ID_LENGTH]


def _safe_details(details: Mapping[str, Any] | None) -> dict[str, Any]:
    if details is None:
        return {}
    encoded = jsonable_encoder({key: value for key, value in details.items() if value is not None})
    if isinstance(encoded, dict):
        return {str(key): value for key, value in encoded.items()}
    return {"value": encoded}


def _merge_details(
    base: Mapping[str, Any],
    override: Mapping[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(base)
    if override is not None:
        merged.update(override)
    return merged


def _key_error_value(exc: KeyError) -> str | None:
    if not exc.args:
        return None
    return str(exc.args[0])


def _exception_arg(exc: Exception) -> str | None:
    if not exc.args:
        return None
    return str(exc.args[0])


def _validation_errors(exc: RequestValidationError) -> list[dict[str, object]]:
    errors: list[dict[str, object]] = []
    for item in exc.errors():
        errors.append(
            {
                "loc": [str(part) for part in item.get("loc", [])],
                "msg": str(item.get("msg", "")),
                "type": str(item.get("type", "")),
            }
        )
    return errors
