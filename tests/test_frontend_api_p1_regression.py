from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import create_router
from app.cases.loader import CaseLoader
from app.runtime.service import RuntimeContainer, create_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_CASE_001_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


def test_events_endpoint_returns_cursor_envelope_not_legacy_bare_array() -> None:
    runtime = _runtime()
    client = TestClient(_app(runtime))
    session_id = _create_session(client)

    payload = client.get(f"/sessions/{session_id}/events").json()

    assert isinstance(payload, dict)
    assert payload["session_id"] == session_id
    assert payload["case_id"] == "fake_case_001"
    assert payload["after_count"] == 0
    assert payload["next_after_count"] == 1
    assert payload["has_more"] is False
    assert [event["type"] for event in payload["events"]] == ["session.created"]


def test_action_response_events_can_be_read_from_current_or_projected_shape() -> None:
    runtime = _runtime()
    client = TestClient(_app(runtime))
    session_id = _create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "desk"},
    )

    assert response.status_code == 200
    payload = response.json()
    events = _action_events(payload)
    event_types = [event["type"] for event in events]
    assert "player.inspected" in event_types
    assert "clue.discovered" in event_types
    assert "player_knowledge.updated" in event_types
    assert payload["state"]["event_count"] >= len(events)


def test_state_summary_does_not_expose_world_info_ids() -> None:
    runtime = _runtime()
    client = TestClient(_app(runtime))
    session_id = _create_session(client)
    client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "desk"},
    )

    state_payload = client.get(f"/sessions/{session_id}/state").json()

    paths = _find_key_paths(state_payload, "world_info_id")
    assert paths == []


def test_error_detail_can_be_normalized_from_legacy_string_or_structured_object() -> None:
    runtime = _runtime()
    client = TestClient(_app(runtime))
    session_id = _create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "unknown"},
    )

    assert response.status_code == 400
    normalized = _normalize_error_detail(response.json().get("detail"))
    details = response.json()["detail"].get("details", {})
    reason = details.get("reason", "")
    assert normalized["code"] == "ACTION_NOT_ALLOWED"
    assert normalized["message"]
    assert "unknown" in str(reason).casefold()


def _runtime() -> RuntimeContainer:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    return create_runtime([case])


def _app(runtime: RuntimeContainer) -> FastAPI:
    app = FastAPI()
    app.include_router(create_router(lambda: runtime))
    return app


def _create_session(client: TestClient) -> str:
    response = client.post("/sessions", json={"case_id": "fake_case_001"})
    assert response.status_code == 200
    return str(response.json()["session_id"])


def _action_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events = payload.get("events")
    if isinstance(events, list):
        return [event for event in events if isinstance(event, dict)]

    event_stream = payload.get("event_stream")
    if isinstance(event_stream, dict) and isinstance(event_stream.get("events"), list):
        return [event for event in event_stream["events"] if isinstance(event, dict)]

    new_events = payload.get("new_events")
    if isinstance(new_events, list):
        return [event for event in new_events if isinstance(event, dict)]

    raise AssertionError("Action response does not expose readable action events")


def _find_key_paths(value: Any, key: str, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for item_key, item_value in value.items():
            item_path = f"{prefix}.{item_key}" if prefix else str(item_key)
            if item_key == key:
                paths.append(item_path)
            paths.extend(_find_key_paths(item_value, key, item_path))
        return paths

    if isinstance(value, list):
        paths = []
        item_prefix = f"{prefix}[]" if prefix else "[]"
        for item in value:
            paths.extend(_find_key_paths(item, key, item_prefix))
        return paths

    return []


def _normalize_error_detail(detail: Any) -> dict[str, str]:
    if isinstance(detail, str):
        return {"code": "", "message": detail}
    if isinstance(detail, dict):
        code = detail.get("code")
        message = detail.get("message", detail.get("detail", ""))
        return {
            "code": code if isinstance(code, str) else "",
            "message": message if isinstance(message, str) else "",
        }
    raise AssertionError(f"Unsupported error detail shape: {detail!r}")
