from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents.context import build_agent_context
from app.agents.gateway import AgentGateway
from app.agents.llm_stub import LLMAgentStub
from app.cases.errors import CaseLoadError
from app.cases.loader import CaseLoader
from app.cases.validate import validate_cases
from app.domain.models import (
    AgentIntent,
    AgentIntentType,
    ClueConfig,
    DiscoverClueAction,
    EventType,
    NarrativePhaseChangeAction,
    PlayerAction,
    ProposedActionType,
    RelationshipChangeAction,
    WorldEvent,
)
from app.main import app
from app.rules.engine import RuleEngine
from app.runtime.events import EventRecorder
from app.runtime.replay import replay_events
from app.storage.memory import InMemorySessionStore, build_state_summary

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_CASE_001_DIR = PROJECT_ROOT / "cases" / "fake_case_001"
FAKE_CASE_002_DIR = PROJECT_ROOT / "cases" / "fake_case_002"


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def create_session(client: TestClient, case_id: str | None = None) -> str:
    response = client.post("/sessions", json={"case_id": case_id} if case_id else {})
    assert response.status_code == 200
    return str(response.json()["session_id"])


def test_service_starts_and_health_is_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_loads_fake_cases_on_startup(client: TestClient) -> None:
    response = client.get("/cases")

    assert response.status_code == 200
    cases = response.json()
    assert {case["id"] for case in cases} == {"fake_case_001", "fake_case_002"}
    assert all(case["title"] for case in cases)


def test_create_session_returns_state_summary(client: TestClient) -> None:
    response = client.post("/sessions", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"]
    assert payload["state"]["case_id"] == "fake_case_001"
    assert payload["state"]["narrative_phase"] == "opening"
    assert payload["state"]["event_count"] == 1


def test_create_session_for_second_case_without_runtime_hardcode(client: TestClient) -> None:
    response = client.post("/sessions", json={"case_id": "fake_case_002"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"]["case_id"] == "fake_case_002"
    assert payload["state"]["case_title"]


def test_inspect_desk_discovers_scratched_drawer(client: TestClient) -> None:
    session_id = create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "desk"},
    )

    assert response.status_code == 200
    payload = response.json()
    clue_ids = {clue["id"] for clue in payload["state"]["discovered_clues"]}
    knowledge_ids = {item["knowledge_id"] for item in payload["state"]["player_knowledge"]}
    event_types = {event["type"] for event in payload["new_events"]}
    assert "scratched_drawer" in clue_ids
    assert "player_knowledge.scratched_drawer" in knowledge_ids
    assert "player.inspected" in event_types
    assert "clue.discovered" in event_types
    assert "player_knowledge.updated" in event_types


def test_clue_discovered_completes_beat_and_advances_phase(client: TestClient) -> None:
    session_id = create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "desk"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [event["type"] for event in payload["new_events"]] == [
        "player.inspected",
        "clue.discovered",
        "player_knowledge.updated",
        "memory_candidate.created",
        "narrative.beat.completed",
        "narrative.phase.changed",
    ]
    assert payload["state"]["completed_beats"] == ["drawer_found"]
    assert payload["state"]["narrative_phase"] == "investigation"


def test_required_beats_and_clues_advance_to_reveal_phase(client: TestClient) -> None:
    session_id = create_session(client)
    for target_id in ("desk", "carpet"):
        client.post(
            f"/sessions/{session_id}/actions",
            json={"type": "inspect", "target_id": target_id},
        )

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "portrait"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"]["narrative_phase"] == "reveal"
    assert payload["state"]["completed_beats"] == [
        "drawer_found",
        "hidden_meeting_connected",
    ]


def test_inspect_portrait_discovers_dustless_frame(client: TestClient) -> None:
    session_id = create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "portrait"},
    )

    assert response.status_code == 200
    clue_ids = {clue["id"] for clue in response.json()["state"]["discovered_clues"]}
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
    assert [event["type"] for event in events_response.json()] == ["session.created"]


def test_talk_butler_generates_mock_dialogue(client: TestClient) -> None:
    session_id = create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "talk", "target_id": "butler", "text": "Where were you?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["director_blocked"] is False
    assert payload["speech"]
    event_types = [event["type"] for event in payload["new_events"]]
    assert "player.talked" in event_types
    assert "npc.replied" in event_types
    assert "relationship.changed" in event_types
    assert "relationship.threshold.crossed" in event_types
    relationship_event = next(
        event for event in payload["new_events"] if event["type"] == "relationship.changed"
    )
    assert relationship_event["payload"]["source_id"] == "butler"
    assert relationship_event["payload"]["target_id"] == "player"


def test_agent_context_includes_runtime_inputs_for_target_agent() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    session.discovered_clues.add("scratched_drawer")
    session.narrative.discovered_clues.add("scratched_drawer")
    session.narrative.completed_beats.add("drawer_found")
    session.narrative.phase = "investigation"
    action = PlayerAction(type="talk", target_id="butler", text="Where were you?")

    context = build_agent_context(case, session, action)

    assert context.case_id == "fake_case_001"
    assert context.session_id == session.id
    assert context.target_agent_id == "butler"
    assert context.current_phase == "investigation"
    assert context.completed_beats == ["drawer_found"]
    assert context.discovered_clues == ["scratched_drawer"]
    assert context.player_action.target_id == "butler"
    assert context.relationship_to_player is not None
    assert context.default_speech is not None
    assert context.target_profile is not None
    assert context.target_profile.id == "butler"
    assert set(context.target_profile.model_dump()) == {
        "id",
        "name",
        "role",
        "personality",
        "speech_style",
    }


def test_agent_context_uses_fact_ids_without_forbidden_fact_text() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    action = PlayerAction(type="talk", target_id="butler", text="Tell me.")

    opening_context = build_agent_context(case, session, action)
    session.narrative.phase = "reveal"
    reveal_context = build_agent_context(case, session, action)

    assert set(opening_context.blocked_fact_ids) == {
        "true_killer",
        "swapped_will",
    }
    assert opening_context.revealable_fact_ids == []
    assert set(reveal_context.revealable_fact_ids) == {
        "true_killer",
        "swapped_will",
    }
    assert reveal_context.blocked_fact_ids == []

    serialized_context = opening_context.model_dump_json()
    assert '"secrets":' not in serialized_context
    assert '"goals":' not in serialized_context
    assert '"knowledge":' not in serialized_context
    assert '"truth_status":' not in serialized_context
    assert '"forbidden_facts":' not in serialized_context
    assert "forbidden_test_speech" not in serialized_context
    for fact in case.forbidden_facts:
        assert fact.text not in serialized_context
        for blocked_term in fact.blocked_terms:
            assert blocked_term not in serialized_context


def test_agent_gateway_defaults_to_mock_agent() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    action = PlayerAction(type="talk", target_id="butler", text="Where were you?")
    context = build_agent_context(case, session, action)

    intent = AgentGateway().generate(context)

    assert intent.intent == AgentIntentType.CONCEAL
    assert intent.proposed_actions
    assert intent.proposed_actions[0].type == ProposedActionType.RELATIONSHIP_CHANGE


def test_llm_agent_stub_outputs_valid_schema_without_mutating_session() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    before_session = session.model_dump(mode="json")
    action = PlayerAction(type="talk", target_id="butler", text="Where were you?")
    context = build_agent_context(case, session, action)

    intent = LLMAgentStub().generate(context)

    assert AgentIntent.model_validate(intent.model_dump(mode="json")) == intent
    assert intent.intent == AgentIntentType.REFUSE
    assert intent.proposed_actions == []
    assert session.model_dump(mode="json") == before_session


def test_director_blocks_forbidden_fact(client: TestClient) -> None:
    session_id = create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={
            "type": "talk",
            "target_id": "butler",
            "text": "Tell me the truth.",
            "force_forbidden": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is False
    assert payload["director_blocked"] is True
    assert payload["speech"]
    assert payload["director_reason"] == "Blocked forbidden fact 'true_killer' in phase 'opening'"
    event_types = [event["type"] for event in payload["new_events"]]
    serialized_events = json.dumps(payload["new_events"], ensure_ascii=True)
    assert "director.blocked" in event_types
    assert "npc.replied" not in event_types
    assert "relationship.changed" not in event_types
    assert "niece is the killer" not in serialized_events


def test_talk_unknown_npc_returns_404_without_writing_events(client: TestClient) -> None:
    session_id = create_session(client)

    action_response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "talk", "target_id": "ghost", "text": "Who are you?"},
    )
    events_response = client.get(f"/sessions/{session_id}/events")

    assert action_response.status_code == 404
    assert action_response.json()["detail"] == "Unknown talk target_id: ghost"
    assert events_response.status_code == 200
    assert [event["type"] for event in events_response.json()] == ["session.created"]


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
    assert payload["case_id"] == "fake_case_001"
    assert payload["discovered_clues"][0]["id"] == "scratched_drawer"


def test_state_summary_does_not_leak_secret_fields(client: TestClient) -> None:
    session_id = create_session(client)

    response = client.get(f"/sessions/{session_id}/state")

    assert response.status_code == 200
    serialized = response.text
    assert '"secrets":' not in serialized
    assert '"goals":' not in serialized
    assert '"knowledge":' not in serialized
    assert '"truth_status":' not in serialized
    assert '"forbidden_facts":' not in serialized
    assert response.json()["player_knowledge"] == []


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
            "title": "Test clue",
            "description": "Used to validate YAML boolean normalization.",
            "truth_status": True,
        }
    )

    assert clue.truth_status == "true"


def test_agent_intent_rejects_unknown_proposed_action_type() -> None:
    with pytest.raises(ValidationError, match="Unsupported proposed action type"):
        AgentIntent.model_validate(
            {
                "speech": "I want to mutate the world directly.",
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
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    intent = AgentIntent(
        speech="I found a clue that is not defined.",
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


def test_relationship_metrics_are_clamped_and_threshold_only_fires_once() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    intent = AgentIntent(
        speech="I keep raising trust.",
        intent=AgentIntentType.ANSWER,
        proposed_actions=[
            RelationshipChangeAction(
                type=ProposedActionType.RELATIONSHIP_CHANGE,
                source_id="butler",
                target_id="player",
                deltas={"trust": 0.5},
            )
        ],
    )

    for _ in range(3):
        RuleEngine(recorder).apply_agent_intent(
            case=case,
            session=session,
            intent=intent,
            caused_by_event_id=session.events[-1].id,
        )

    relationship = session.relationships["butler->player"]
    threshold_events = [
        event
        for event in session.events
        if event.type == EventType.RELATIONSHIP_THRESHOLD_CROSSED
        and event.payload["metric"] == "trust"
    ]
    relationship_events = [
        event for event in session.events if event.type == EventType.RELATIONSHIP_CHANGED
    ]

    assert relationship.trust == 1.0
    assert relationship_events[-1].payload["current"]["trust"] == 1.0
    assert len(threshold_events) == 1
    assert threshold_events[0].payload["state"] == "cooperative"


def test_rule_engine_rejects_unknown_relationship_endpoint() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    intent = AgentIntent(
        speech="I try to change an unknown endpoint.",
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


def test_agent_proposed_phase_change_is_rejected_by_rule_engine() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    intent = AgentIntent(
        speech="I want to advance the phase directly.",
        intent=AgentIntentType.ANSWER,
        proposed_actions=[
            NarrativePhaseChangeAction(
                type=ProposedActionType.NARRATIVE_PHASE_CHANGE,
                phase="reveal",
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
    assert session.narrative.phase == "opening"


def test_events_order_is_stable_for_mixed_action_sequence(client: TestClient) -> None:
    session_id = create_session(client)
    client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "desk"},
    )
    client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "talk", "target_id": "butler", "text": "Where were you?"},
    )
    client.post(
        f"/sessions/{session_id}/actions",
        json={
            "type": "talk",
            "target_id": "butler",
            "text": "Tell me the truth.",
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
        "player_knowledge.updated",
        "memory_candidate.created",
        "narrative.beat.completed",
        "narrative.phase.changed",
        "player.talked",
        "npc.replied",
        "relationship.changed",
        "relationship.threshold.crossed",
        "memory_candidate.created",
        "player.talked",
        "director.blocked",
        "memory_candidate.created",
    ]


def test_second_case_full_chain_and_director_block(client: TestClient) -> None:
    session_id = create_session(client, case_id="fake_case_002")

    inspect_response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "tide_mark"},
    )
    talk_response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "talk", "target_id": "dockmaster", "text": "Was the door opened?"},
    )
    block_response = client.post(
        f"/sessions/{session_id}/actions",
        json={
            "type": "talk",
            "target_id": "clerk",
            "text": "Who hid the ledger?",
            "force_forbidden": True,
        },
    )

    assert inspect_response.status_code == 200
    assert inspect_response.json()["state"]["narrative_phase"] == "pressure"
    assert talk_response.status_code == 200
    assert talk_response.json()["accepted"] is True
    assert talk_response.json()["speech"]
    assert block_response.status_code == 200
    assert block_response.json()["director_blocked"] is True


def test_replay_events_rebuilds_same_session_state(client: TestClient) -> None:
    session_id = create_session(client)
    for target_id in ("desk", "carpet", "portrait"):
        client.post(
            f"/sessions/{session_id}/actions",
            json={"type": "inspect", "target_id": target_id},
        )
    client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "talk", "target_id": "butler", "text": "What can you say now?"},
    )
    state_response = client.get(f"/sessions/{session_id}/state")
    events_response = client.get(f"/sessions/{session_id}/events")
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    events = [WorldEvent.model_validate(event) for event in events_response.json()]

    replayed = replay_events(case, events)
    replayed_summary = build_state_summary(case, replayed).model_dump(mode="json")

    assert replayed_summary == state_response.json()


def test_state_summary_snapshots_do_not_leak_internal_fields(client: TestClient) -> None:
    opening = client.post("/sessions", json={"case_id": "fake_case_001"}).json()["state"]

    investigation_response = client.post("/sessions", json={"case_id": "fake_case_001"})
    investigation_session_id = investigation_response.json()["session_id"]
    investigation = client.post(
        f"/sessions/{investigation_session_id}/actions",
        json={"type": "inspect", "target_id": "desk"},
    ).json()["state"]

    second_case_response = client.post("/sessions", json={"case_id": "fake_case_002"})
    second_case_session_id = second_case_response.json()["session_id"]
    second_case_talk = client.post(
        f"/sessions/{second_case_session_id}/actions",
        json={"type": "talk", "target_id": "dockmaster", "text": "Tell me about warehouse."},
    ).json()["state"]

    snapshots = {
        "fake_case_001_after_opening": {
            "case_id": opening["case_id"],
            "phase": opening["narrative_phase"],
            "completed_beats": opening["completed_beats"],
            "discovered": [clue["id"] for clue in opening["discovered_clues"]],
            "player_knowledge": [item["knowledge_id"] for item in opening["player_knowledge"]],
            "event_count": opening["event_count"],
        },
        "fake_case_001_after_investigation": {
            "case_id": investigation["case_id"],
            "phase": investigation["narrative_phase"],
            "completed_beats": investigation["completed_beats"],
            "discovered": [clue["id"] for clue in investigation["discovered_clues"]],
            "player_knowledge": [
                item["knowledge_id"] for item in investigation["player_knowledge"]
            ],
            "event_count": investigation["event_count"],
        },
        "fake_case_002_after_first_talk": {
            "case_id": second_case_talk["case_id"],
            "phase": second_case_talk["narrative_phase"],
            "completed_beats": second_case_talk["completed_beats"],
            "discovered": [clue["id"] for clue in second_case_talk["discovered_clues"]],
            "player_knowledge": [
                item["knowledge_id"] for item in second_case_talk["player_knowledge"]
            ],
            "event_count": second_case_talk["event_count"],
        },
    }

    assert snapshots == {
        "fake_case_001_after_opening": {
            "case_id": "fake_case_001",
            "phase": "opening",
            "completed_beats": [],
            "discovered": [],
            "player_knowledge": [],
            "event_count": 1,
        },
        "fake_case_001_after_investigation": {
            "case_id": "fake_case_001",
            "phase": "investigation",
            "completed_beats": ["drawer_found"],
            "discovered": ["scratched_drawer"],
            "player_knowledge": ["player_knowledge.scratched_drawer"],
            "event_count": 7,
        },
        "fake_case_002_after_first_talk": {
            "case_id": "fake_case_002",
            "phase": "opening",
            "completed_beats": [],
            "discovered": [],
            "player_knowledge": [],
            "event_count": 4,
        },
    }
    serialized = json.dumps([opening, investigation, second_case_talk], ensure_ascii=False)
    assert '"secrets":' not in serialized
    assert '"goals":' not in serialized
    assert '"knowledge":' not in serialized
    assert '"truth_status":' not in serialized
    assert '"forbidden_facts":' not in serialized


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
    (case_dir / "narrative_rules.yaml").write_text(
        "phases:\n  - id: opening\nbeats: []\n",
        encoding="utf-8",
    )

    with pytest.raises(CaseLoadError, match="unknown clue 'missing_clue'"):
        CaseLoader().load(case_dir)


def test_case_validate_command_accepts_all_fake_cases() -> None:
    assert validate_cases(PROJECT_ROOT / "cases") == ["fake_case_001", "fake_case_002"]


def test_case_loader_rejects_unreachable_clue(tmp_path: Path) -> None:
    case_dir = tmp_path / "unreachable_case"
    case_dir.mkdir()
    _write_minimal_case(case_dir)
    (case_dir / "clues.yaml").write_text(
        "- id: unreachable\n  title: Unreachable\n  description: hidden\n",
        encoding="utf-8",
    )

    with pytest.raises(CaseLoadError, match="not reachable"):
        CaseLoader().load(case_dir)


def test_case_loader_rejects_bad_narrative_rule_reference(tmp_path: Path) -> None:
    case_dir = tmp_path / "bad_rule_case"
    case_dir.mkdir()
    _write_minimal_case(case_dir)
    (case_dir / "narrative_rules.yaml").write_text(
        "phases:\n"
        "  - id: opening\n"
        "beats:\n"
        "  - id: bad_beat\n"
        "    all_discovered:\n"
        "      - missing_clue\n",
        encoding="utf-8",
    )

    with pytest.raises(CaseLoadError, match="unknown clues"):
        CaseLoader().load(case_dir)


def test_case_loader_rejects_legacy_relationship_endpoint_fields(tmp_path: Path) -> None:
    case_dir = tmp_path / "legacy_relationship_case"
    case_dir.mkdir()
    _write_minimal_case(case_dir)
    (case_dir / "relationships.yaml").write_text(
        "- source: npc\n  target: player\n",
        encoding="utf-8",
    )

    with pytest.raises(CaseLoadError, match="schema validation failed"):
        CaseLoader().load(case_dir)


def _write_minimal_case(case_dir: Path) -> None:
    (case_dir / "case.yaml").write_text(
        "id: test_case\ntitle: Test Case\ndescription: ''\ninitial_phase: opening\n",
        encoding="utf-8",
    )
    (case_dir / "characters.yaml").write_text(
        "- id: npc\n  name: NPC\n  role: Witness\n",
        encoding="utf-8",
    )
    (case_dir / "scenes.yaml").write_text(
        "- id: room\n  name: Room\n  characters:\n"
        "    - npc\n  hotspots:\n"
        "    - id: desk\n      name: Desk\n      discover_clues: []\n",
        encoding="utf-8",
    )
    (case_dir / "clues.yaml").write_text("[]\n", encoding="utf-8")
    (case_dir / "relationships.yaml").write_text("[]\n", encoding="utf-8")
    (case_dir / "forbidden_facts.yaml").write_text("[]\n", encoding="utf-8")
    (case_dir / "mock_dialogues.yaml").write_text(
        "- character_id: npc\n  default_speech: ok\n",
        encoding="utf-8",
    )
    (case_dir / "narrative_rules.yaml").write_text(
        "phases:\n  - id: opening\nbeats: []\n",
        encoding="utf-8",
    )
