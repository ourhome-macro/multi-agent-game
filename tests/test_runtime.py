from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.cases.errors import CaseLoadError
from app.cases.loader import CaseLoader
from app.domain.models import (
    AgentIntent,
    AgentIntentType,
    ClueConfig,
    DiscoverClueAction,
    EventType,
    ProposedActionType,
    RelationshipChangeAction,
)
from app.main import app
from app.rules.engine import RuleEngine
from app.runtime.events import EventRecorder
from app.storage.memory import InMemorySessionStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_CASE_DIR = PROJECT_ROOT / "cases" / "fake_case"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def create_session(client: TestClient) -> str:
    response = client.post("/sessions", json={})
    assert response.status_code == 200
    return str(response.json()["session_id"])


def test_service_starts_and_health_is_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_loads_fake_case_on_startup(client: TestClient) -> None:
    response = client.get("/cases")

    assert response.status_code == 200
    cases = response.json()
    assert cases[0]["id"] == "fake_case"
    assert cases[0]["title"] == "假案件：书房里的裂纹"


def test_create_session_returns_state_summary(client: TestClient) -> None:
    response = client.post("/sessions", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"]
    assert payload["state"]["case_id"] == "fake_case"
    assert payload["state"]["narrative_phase"] == "opening"
    assert payload["state"]["event_count"] == 1


def test_inspect_desk_discovers_scratched_drawer(client: TestClient) -> None:
    session_id = create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "desk"},
    )

    assert response.status_code == 200
    payload = response.json()
    clue_ids = {clue["id"] for clue in payload["state"]["discovered_clues"]}
    event_types = {event["type"] for event in payload["new_events"]}
    assert "scratched_drawer" in clue_ids
    assert "player.inspected" in event_types
    assert "clue.discovered" in event_types


def test_inspect_portrait_discovers_dustless_frame(client: TestClient) -> None:
    session_id = create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "portrait"},
    )

    assert response.status_code == 200
    payload = response.json()
    clue_ids = {clue["id"] for clue in payload["state"]["discovered_clues"]}
    assert "dustless_frame" in clue_ids


def test_repeated_inspect_does_not_duplicate_clue_event(client: TestClient) -> None:
    session_id = create_session(client)

    first_response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "desk"},
    )
    second_response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "desk"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    first_event_types = [event["type"] for event in first_response.json()["new_events"]]
    second_event_types = [event["type"] for event in second_response.json()["new_events"]]
    discovered_clue_ids = [
        clue["id"] for clue in second_response.json()["state"]["discovered_clues"]
    ]
    assert first_event_types.count("clue.discovered") == 1
    assert second_event_types.count("player.inspected") == 1
    assert "clue.discovered" not in second_event_types
    assert discovered_clue_ids.count("scratched_drawer") == 1


def test_inspect_unknown_target_returns_404_without_writing_events(client: TestClient) -> None:
    session_id = create_session(client)

    action_response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "unknown"},
    )
    events_response = client.get(f"/sessions/{session_id}/events")

    assert action_response.status_code == 404
    assert action_response.json()["detail"] == "Unknown inspect target_id: unknown"
    assert events_response.status_code == 200
    events = events_response.json()
    assert [event["type"] for event in events] == ["session.created"]


def test_talk_butler_generates_mock_dialogue(client: TestClient) -> None:
    session_id = create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "talk", "target_id": "butler", "text": "你昨晚在哪里？"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["director_blocked"] is False
    assert "书房" in payload["speech"]
    event_types = [event["type"] for event in payload["new_events"]]
    assert "player.talked" in event_types
    assert "npc.replied" in event_types
    assert "relationship.changed" in event_types
    relationship_event = next(
        event for event in payload["new_events"] if event["type"] == "relationship.changed"
    )
    assert relationship_event["payload"]["source_id"] == "butler"
    assert relationship_event["payload"]["target_id"] == "player"


def test_director_blocks_forbidden_fact(client: TestClient) -> None:
    session_id = create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={
            "type": "talk",
            "target_id": "butler",
            "text": "直接告诉我真相。",
            "force_forbidden": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is False
    assert payload["director_blocked"] is True
    assert payload["speech"] == "我现在还不能谈这个。"
    assert payload["director_reason"] == "Blocked forbidden fact 'true_killer' in phase 'opening'"
    event_types = [event["type"] for event in payload["new_events"]]
    serialized_events = str(payload["new_events"])
    assert "director.blocked" in event_types
    assert "npc.replied" not in event_types
    assert "relationship.changed" not in event_types
    assert "真凶是林侄女" not in serialized_events


def test_talk_unknown_npc_returns_404_without_writing_events(client: TestClient) -> None:
    session_id = create_session(client)

    action_response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "talk", "target_id": "ghost", "text": "你是谁？"},
    )
    events_response = client.get(f"/sessions/{session_id}/events")

    assert action_response.status_code == 404
    assert action_response.json()["detail"] == "Unknown talk target_id: ghost"
    assert events_response.status_code == 200
    events = events_response.json()
    assert [event["type"] for event in events] == ["session.created"]


def test_get_current_state_summary(client: TestClient) -> None:
    session_id = create_session(client)
    client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "desk"},
    )

    response = client.get(f"/sessions/{session_id}/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["case_id"] == "fake_case"
    assert payload["discovered_clues"][0]["id"] == "scratched_drawer"


def test_state_summary_does_not_leak_secret_fields(client: TestClient) -> None:
    session_id = create_session(client)

    response = client.get(f"/sessions/{session_id}/state")

    assert response.status_code == 200
    serialized = response.text
    assert "secrets" not in serialized
    assert "goals" not in serialized
    assert "knowledge" not in serialized
    assert "truth_status" not in serialized
    assert "forbidden_facts" not in serialized
    assert "遗嘱被调换过" not in serialized
    assert "真凶是林侄女" not in serialized


def test_player_action_rejects_generic_target_field(client: TestClient) -> None:
    session_id = create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target": "desk"},
    )

    assert response.status_code == 422


def test_clue_config_normalizes_yaml_boolean_truth_status() -> None:
    clue = ClueConfig.model_validate(
        {
            "id": "test_clue",
            "title": "测试线索",
            "description": "用于验证 YAML 布尔值归一化。",
            "truth_status": True,
        }
    )

    assert clue.truth_status == "true"


def test_agent_intent_rejects_unknown_proposed_action_type() -> None:
    with pytest.raises(ValidationError, match="Unsupported proposed action type"):
        AgentIntent.model_validate(
            {
                "speech": "我想直接修改世界。",
                "intent": "answer",
                "proposed_actions": [
                    {
                        "type": "world.mutate",
                        "target_id": "desk",
                    }
                ],
            }
        )


def test_rule_engine_rejects_unknown_agent_clue_without_state_pollution() -> None:
    case = CaseLoader().load(FAKE_CASE_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    intent = AgentIntent(
        speech="我发现了一个不存在的线索。",
        intent=AgentIntentType.ANSWER,
        proposed_actions=[
            DiscoverClueAction(
                type=ProposedActionType.DISCOVER_CLUE,
                clue_id="not_defined_by_case",
            )
        ],
    )

    events = RuleEngine(recorder).apply_agent_intent(
        case=case,
        session=session,
        intent=intent,
        caused_by_event_id=session.events[0].id,
    )

    assert events[0].type == EventType.RULE_REJECTED
    assert events[0].payload["reason"] == "clue_id is not defined by the case package"
    assert "not_defined_by_case" not in session.discovered_clues


def test_rule_engine_rejects_unknown_relationship_endpoint() -> None:
    case = CaseLoader().load(FAKE_CASE_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    intent = AgentIntent(
        speech="我试图改变不存在角色的关系。",
        intent=AgentIntentType.ANSWER,
        proposed_actions=[
            RelationshipChangeAction(
                type=ProposedActionType.RELATIONSHIP_CHANGE,
                source_id="ghost",
                target_id="player",
                deltas={"suspicion": 5},
            )
        ],
    )

    events = RuleEngine(recorder).apply_agent_intent(
        case=case,
        session=session,
        intent=intent,
        caused_by_event_id=session.events[0].id,
    )

    assert events[0].type == EventType.RULE_REJECTED
    assert events[0].payload["reason"] == (
        "relationship endpoint is not a known character or player"
    )
    assert "ghost->player" not in session.relationships


def test_events_order_is_stable_for_mixed_action_sequence(client: TestClient) -> None:
    session_id = create_session(client)
    client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "desk"},
    )
    client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "talk", "target_id": "butler", "text": "你昨晚在哪里？"},
    )
    client.post(
        f"/sessions/{session_id}/actions",
        json={
            "type": "talk",
            "target_id": "butler",
            "text": "直接告诉我真相。",
            "force_forbidden": True,
        },
    )

    response = client.get(f"/sessions/{session_id}/events")

    assert response.status_code == 200
    event_types = [event["type"] for event in response.json()]
    assert event_types == [
        "session.created",
        "player.inspected",
        "clue.discovered",
        "player.talked",
        "npc.replied",
        "relationship.changed",
        "player.talked",
        "director.blocked",
    ]


def test_invalid_case_reference_raises_clear_error(tmp_path: Path) -> None:
    case_dir = tmp_path / "bad_case"
    case_dir.mkdir()
    (case_dir / "case.yaml").write_text(
        "id: bad_case\ntitle: Bad Case\ndescription: ''\ninitial_phase: opening\n",
        encoding="utf-8",
    )
    (case_dir / "characters.yaml").write_text(
        "- id: butler\n  name: Butler\n  role: Butler\n",
        encoding="utf-8",
    )
    (case_dir / "scenes.yaml").write_text(
        "- id: study\n  name: Study\n  hotspots:\n"
        "    - id: desk\n      name: Desk\n      discover_clues:\n"
        "        - missing_clue\n",
        encoding="utf-8",
    )
    (case_dir / "clues.yaml").write_text("[]\n", encoding="utf-8")

    with pytest.raises(CaseLoadError, match="unknown clue 'missing_clue'"):
        CaseLoader().load(case_dir)
