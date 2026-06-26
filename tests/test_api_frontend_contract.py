from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.projections import build_public_action_response, build_public_state_summary
from app.api.routes import create_router
from app.cases.loader import CaseLoader
from app.domain.models import ActionType, PlayerAction, PublicRawTextActionResponse
from app.runtime.service import RuntimeContainer, create_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_CASE_001_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


def test_public_case_detail_does_not_leak_internal_truth_fields() -> None:
    runtime = _runtime()
    client = TestClient(_app(runtime))

    response = client.get("/cases/fake_case_001")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "fake_case_001"
    assert payload["initial_scene_id"] == "study"
    assert payload["assets"] == []
    assert [scene["id"] for scene in payload["scenes"]] == ["study"]
    assert {hotspot["id"] for hotspot in payload["scenes"][0]["hotspots"]} == {
        "desk",
        "carpet",
        "portrait",
    }

    serialized = json.dumps(payload, ensure_ascii=False)
    forbidden_terms = [
        "truth_status",
        "reveals_world_info",
        "world_info",
        "desk_forced_open",
        "will_swapped",
        "forbidden_facts",
        "solution_claims",
        "private",
        "mock_dialogues",
        "reply_options",
    ]
    for term in forbidden_terms:
        assert term not in serialized


def test_session_affordances_are_derived_from_runtime_state() -> None:
    runtime = _runtime()
    client = TestClient(_app(runtime))
    session_id = _create_session(client)

    initial = client.get(f"/sessions/{session_id}/affordances").json()
    assert set(initial["available_hotspot_ids"]) == {"desk", "carpet", "portrait"}
    assert set(initial["available_character_ids"]) == {"butler", "niece"}
    assert initial["discovered_clue_ids"] == []
    assert initial["evidence_asset_ids"] == []
    assert initial["present_clue"] == []
    assert not _has_ask_about_subject(initial, "clue", "scratched_drawer")
    assert initial["can_accuse"] is False

    _inspect(client, session_id, "desk")
    after_desk = client.get(f"/sessions/{session_id}/affordances").json()
    assert after_desk["discovered_clue_ids"] == ["scratched_drawer"]
    assert after_desk["evidence_asset_ids"] == ["scratched_drawer"]
    assert _has_ask_about_subject(after_desk, "clue", "scratched_drawer")
    assert _has_present_clue(after_desk, "butler", "scratched_drawer")
    assert after_desk["valid_presentation_modes"] == ["private", "scene_shared"]
    assert after_desk["can_accuse"] is False

    _inspect(client, session_id, "carpet")
    _inspect(client, session_id, "portrait")
    reveal = client.get(f"/sessions/{session_id}/affordances").json()
    assert reveal["narrative_phase"] == "reveal"
    assert reveal["can_accuse"] is True
    assert {item["target_id"] for item in reveal["accuse"]} == {"butler", "niece"}

    serialized = json.dumps(reveal, ensure_ascii=False)
    assert "claim_id" not in serialized
    assert "required_world_info" not in serialized
    assert "correct" not in serialized
    assert "incorrect" not in serialized


def test_public_event_stream_uses_incremental_count_cursor_and_redacted_payload() -> None:
    runtime = _runtime()
    client = TestClient(_app(runtime))
    session_id = _create_session(client)

    initial = client.get(f"/sessions/{session_id}/events", params={"after_count": 0}).json()
    assert initial["after_count"] == 0
    assert initial["next_after_count"] == 1
    assert initial["has_more"] is False
    assert [(event["sequence"], event["type"]) for event in initial["events"]] == [
        (1, "session.created")
    ]

    _inspect(client, session_id, "desk")
    stream = client.get(
        f"/sessions/{session_id}/events",
        params={"after_count": initial["next_after_count"]},
    ).json()

    assert stream["after_count"] == 1
    assert stream["next_after_count"] > stream["after_count"]
    event_types = [event["type"] for event in stream["events"]]
    assert "player.inspected" in event_types
    assert "clue.discovered" in event_types
    assert "player_knowledge.updated" in event_types
    assert "memory_candidate.created" not in event_types
    assert "agent_memory_snapshot.updated" not in event_types

    serialized = json.dumps(stream, ensure_ascii=False)
    forbidden_terms = [
        "world_info_id",
        "knowledge_id",
        "memory_id",
        "rule_id",
        "content",
        "reply_options",
        "proposed_actions",
        "disclosure_claims",
    ]
    for term in forbidden_terms:
        assert term not in serialized

    drained = client.get(
        f"/sessions/{session_id}/events",
        params={"after_count": stream["next_after_count"]},
    ).json()
    assert drained["events"] == []
    assert drained["next_after_count"] == stream["next_after_count"]
    assert drained["has_more"] is False


def test_public_action_response_projects_events_and_state_without_internal_anchors() -> None:
    runtime = _runtime()
    case = runtime.case_store.get("fake_case_001")
    session = runtime.create_session(case)

    internal = runtime.handle_action(
        session_id=session.id,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )

    assert internal.new_events
    assert "world_info_id" in json.dumps(internal.state.model_dump(mode="json"))

    public = build_public_action_response(internal).model_dump(mode="json")
    assert public["accepted"] is True
    assert public["state"]["event_count"] == internal.state.event_count
    assert public["state"]["player_knowledge"]
    assert public["state"]["evidence_assets"]

    event_types = [event["type"] for event in public["new_events"]]
    assert "player.inspected" in event_types
    assert "clue.discovered" in event_types
    assert "player_knowledge.updated" in event_types
    assert "memory_candidate.created" not in event_types
    assert "agent_memory_snapshot.updated" not in event_types
    assert min(event["sequence"] for event in public["new_events"]) >= 2
    assert (
        max(event["sequence"] for event in public["new_events"])
        <= public["state"]["event_count"]
    )

    serialized = json.dumps(public, ensure_ascii=False)
    _assert_no_public_response_internal_terms(serialized)


def test_public_state_summary_strips_internal_knowledge_and_evidence_refs() -> None:
    runtime = _runtime()
    case = runtime.case_store.get("fake_case_001")
    session = runtime.create_session(case)
    response = runtime.handle_action(
        session_id=session.id,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )

    public = build_public_state_summary(response.state).model_dump(mode="json")

    assert len(public["player_knowledge"]) == 1
    knowledge = public["player_knowledge"][0]
    assert set(knowledge) == {
        "clue_id",
        "confidence",
        "acquisition",
        "source_type",
        "title",
        "summary",
    }
    assert knowledge["clue_id"] == "scratched_drawer"
    assert knowledge["confidence"] == 1.0
    assert knowledge["acquisition"] == "discovered"
    assert knowledge["source_type"] == "clue"

    assert len(public["evidence_assets"]) == 1
    asset = public["evidence_assets"][0]
    assert set(asset) == {"id", "title", "summary", "source", "clue_id"}
    assert asset["id"] == "scratched_drawer"
    assert asset["source"] == "clue"
    assert asset["clue_id"] == "scratched_drawer"

    serialized = json.dumps(public, ensure_ascii=False)
    _assert_no_public_response_internal_terms(serialized)


def test_public_raw_action_response_wraps_projected_response() -> None:
    runtime = _runtime()
    case = runtime.case_store.get("fake_case_001")
    session = runtime.create_session(case)
    action = PlayerAction(type=ActionType.INSPECT, target_id="desk")
    response = runtime.handle_action(session_id=session.id, action=action)

    public_raw = PublicRawTextActionResponse(
        status="accepted",
        action=action,
        response=build_public_action_response(response),
        route_trace={"recognized_action": "inspect"},
    ).model_dump(mode="json")

    assert public_raw["response"]["accepted"] is True
    assert public_raw["response"]["new_events"][0]["type"] == "player.inspected"
    serialized = json.dumps(public_raw, ensure_ascii=False)
    _assert_no_public_response_internal_terms(serialized)


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


def _inspect(client: TestClient, session_id: str, target_id: str) -> None:
    response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": target_id},
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is True


def _has_ask_about_subject(
    payload: dict[str, Any],
    subject_type: str,
    subject_id: str,
) -> bool:
    return any(
        item["subject_type"] == subject_type and item["subject_id"] == subject_id
        for item in payload["ask_about"]
    )


def _has_present_clue(payload: dict[str, Any], target_id: str, clue_id: str) -> bool:
    return any(
        item["target_id"] == target_id and item["clue_id"] == clue_id
        for item in payload["present_clue"]
    )


def _assert_no_public_response_internal_terms(serialized: str) -> None:
    forbidden_terms = [
        "world_info_id",
        "knowledge_id",
        "source_knowledge_id",
        "memory_id",
        "rule_id",
        "disclosure_claims",
        "proposed_actions",
        "unlocked_at_event_id",
        "blocked_fact_id",
        "matched_text",
    ]
    for term in forbidden_terms:
        assert term not in serialized
