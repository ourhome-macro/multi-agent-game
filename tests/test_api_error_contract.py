from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.errors import (
    CORRELATION_ID_HEADER,
    http_exception_from_api_error,
    install_api_error_handlers,
    map_exception_to_api_error,
    raise_api_error,
    resolve_correlation_id,
)
from app.domain.models import APIErrorCode, APIErrorResponse
from app.runtime.errors import ActionValidationError
from app.storage.postgres import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    PostgresPersistenceError,
    StaleSessionSequenceError,
    UnknownSessionError,
)


def test_api_error_response_is_a_strict_stable_dto() -> None:
    payload = APIErrorResponse(
        code=APIErrorCode.ACTION_NOT_ALLOWED,
        message="Action is not allowed in the current world state.",
        details={"reason": "Unknown inspect target_id: vault"},
        retryable=False,
        correlation_id="corr-test",
    )

    assert payload.model_dump(mode="json") == {
        "code": "ACTION_NOT_ALLOWED",
        "message": "Action is not allowed in the current world state.",
        "details": {"reason": "Unknown inspect target_id: vault"},
        "retryable": False,
        "correlation_id": "corr-test",
    }
    with pytest.raises(ValidationError):
        APIErrorResponse.model_validate(
            {
                "code": APIErrorCode.INTERNAL_ERROR,
                "message": "Unexpected server error.",
                "retryable": False,
                "correlation_id": "corr-test",
                "extra_field": True,
            }
        )


@pytest.mark.parametrize(
    ("exc", "kwargs", "expected_status", "expected_code", "expected_retryable"),
    [
        (
            KeyError("case_missing"),
            {"resource_type": "case", "resource_id": "case_missing"},
            404,
            APIErrorCode.CASE_NOT_FOUND,
            False,
        ),
        (
            UnknownSessionError("session_missing"),
            {},
            404,
            APIErrorCode.SESSION_NOT_FOUND,
            False,
        ),
        (
            ActionValidationError("Unknown inspect target_id: vault"),
            {},
            400,
            APIErrorCode.ACTION_NOT_ALLOWED,
            False,
        ),
        (
            IdempotencyConflictError("key reused"),
            {},
            409,
            APIErrorCode.IDEMPOTENCY_CONFLICT,
            False,
        ),
        (
            IdempotencyInProgressError("key still in progress"),
            {},
            409,
            APIErrorCode.IDEMPOTENCY_IN_PROGRESS,
            True,
        ),
        (
            StaleSessionSequenceError("expected sequence changed"),
            {},
            409,
            APIErrorCode.STALE_SESSION_SEQUENCE,
            True,
        ),
        (
            PostgresPersistenceError("database host leaked here"),
            {},
            500,
            APIErrorCode.PERSISTENCE_ERROR,
            True,
        ),
    ],
)
def test_exception_mapping_produces_stable_error_contract(
    exc: Exception,
    kwargs: Mapping[str, Any],
    expected_status: int,
    expected_code: APIErrorCode,
    expected_retryable: bool,
) -> None:
    mapping = map_exception_to_api_error(exc, correlation_id="corr-map", **kwargs)

    assert mapping.status_code == expected_status
    assert mapping.headers[CORRELATION_ID_HEADER] == "corr-map"
    assert mapping.body.code == expected_code
    assert mapping.body.retryable is expected_retryable
    assert mapping.body.correlation_id == "corr-map"
    assert set(mapping.body.model_dump(mode="json")) == {
        "code",
        "message",
        "details",
        "retryable",
        "correlation_id",
    }
    assert "database host leaked here" not in json.dumps(
        mapping.body.model_dump(mode="json"),
        ensure_ascii=False,
    )


def test_action_validation_maps_to_action_not_allowed_not_404() -> None:
    mapping = map_exception_to_api_error(
        ActionValidationError("Unknown talk target_id: ghost"),
        correlation_id="corr-action",
    )

    assert mapping.status_code == 400
    assert mapping.body.code == APIErrorCode.ACTION_NOT_ALLOWED
    assert mapping.body.details == {"reason": "Unknown talk target_id: ghost"}


def test_http_exception_adapter_preserves_stable_detail_for_legacy_routes() -> None:
    mapping = map_exception_to_api_error(
        KeyError("case_missing"),
        resource_type="case",
        resource_id="case_missing",
        correlation_id="corr-http",
    )
    exc = http_exception_from_api_error(mapping)

    assert exc.status_code == 404
    assert exc.headers == {CORRELATION_ID_HEADER: "corr-http"}
    assert isinstance(exc.detail, dict)
    assert exc.detail == {
        "code": "CASE_NOT_FOUND",
        "message": "Case not found.",
        "details": {"case_id": "case_missing"},
        "retryable": False,
        "correlation_id": "corr-http",
    }


def test_stable_api_error_handler_returns_root_error_dto() -> None:
    app = FastAPI()
    install_api_error_handlers(app)

    @app.get("/boom")
    def boom(request: Request) -> None:
        raise_api_error(
            ActionValidationError("Unknown inspect target_id: vault"),
            correlation_id=resolve_correlation_id(request=request),
        )

    client = TestClient(app)
    response = client.get("/boom", headers={CORRELATION_ID_HEADER: "corr-client"})

    assert response.status_code == 400
    assert response.headers[CORRELATION_ID_HEADER] == "corr-client"
    assert response.json() == {
        "code": "ACTION_NOT_ALLOWED",
        "message": "Action is not allowed in the current world state.",
        "details": {"reason": "Unknown inspect target_id: vault"},
        "retryable": False,
        "correlation_id": "corr-client",
    }


def test_request_validation_handler_returns_stable_422_without_input_echo() -> None:
    app = FastAPI()
    install_api_error_handlers(app)

    @app.get("/items")
    def get_items(limit: int) -> dict[str, str]:
        assert limit > 0
        return {"status": "ok"}

    client = TestClient(app)
    response = client.get(
        "/items",
        headers={CORRELATION_ID_HEADER: "corr-validation"},
        params={"limit": "raw user text must not be echoed"},
    )
    payload = response.json()

    assert response.status_code == 422
    assert response.headers[CORRELATION_ID_HEADER] == "corr-validation"
    assert payload["code"] == "REQUEST_VALIDATION_ERROR"
    assert payload["retryable"] is False
    assert payload["correlation_id"] == "corr-validation"
    assert payload["details"]["errors"][0]["loc"] == ["query", "limit"]
    assert set(payload["details"]["errors"][0]) == {"loc", "msg", "type"}
    assert "raw user text must not be echoed" not in json.dumps(
        payload,
        ensure_ascii=False,
    )
