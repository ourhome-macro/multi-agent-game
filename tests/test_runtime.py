from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents.context import build_agent_context
from app.agents.gateway import AgentGateway
from app.agents.llm_contract import build_llm_agent_input, validate_llm_agent_output
from app.agents.llm_stub import LLMAgentStub
from app.agents.mock_agent import MockAgent
from app.agents.real_llm_agent import OpenAILLMAgent
from app.cases.errors import CaseLoadError
from app.cases.loader import CaseLoader
from app.cases.validate import validate_cases
from app.domain.models import (
    AgentCharacterView,
    AgentContext,
    AgentIntent,
    AgentIntentType,
    CharacterFactAwarenessState,
    CharacterImpression,
    CharacterInnerContext,
    ClueConfig,
    DisclosureMode,
    DisclosurePolicy,
    DiscoverClueAction,
    EventType,
    FactDisclosureStrategy,
    NarrativePhaseChangeAction,
    PlayerAction,
    ProposedActionType,
    RelationshipChangeAction,
    RhetoricTactic,
    SelfKnowledgeItem,
    SubjectType,
    WorldEvent,
)
from app.main import app
from app.rules.engine import RuleEngine
from app.runtime.events import EventRecorder
from app.runtime.replay import replay_events
from app.runtime.service import create_runtime
from app.storage.memory import InMemorySessionStore, build_state_summary
from tests.utils.render_player_journey import render_player_journey

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


def test_loads_available_cases_on_startup(client: TestClient) -> None:
    response = client.get("/cases")

    assert response.status_code == 200
    cases = response.json()
    assert {case["id"] for case in cases} == {
        "fake_case_001",
        "fake_case_002",
        "mist_clock_manor",
    }
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
    assert "player_knowledge.desk_forced_open" in knowledge_ids
    assert "player.inspected" in event_types
    assert "clue.discovered" in event_types
    assert "player_knowledge.updated" in event_types
    knowledge = payload["state"]["player_knowledge"][0]
    assert knowledge["clue_id"] == "scratched_drawer"
    assert knowledge["world_info_id"] == "desk_forced_open"
    assert knowledge["confidence"] == 1.0
    assert knowledge["acquisition"] == "discovered"
    assert knowledge["source_type"] == "clue"
    knowledge_event = next(
        event for event in payload["new_events"] if event["type"] == "player_knowledge.updated"
    )
    assert knowledge_event["payload"]["world_info_id"] == "desk_forced_open"
    assert knowledge_event["payload"]["confidence"] == 1.0
    assert knowledge_event["payload"]["acquisition"] == "discovered"
    assert knowledge_event["payload"]["source_type"] == "clue"


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
        "agent_memory_snapshot.updated",
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


def test_present_clue_rejects_undiscovered_clue_without_state_pollution(
    client: TestClient,
) -> None:
    session_id = create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={
            "type": "present_clue",
            "target_id": "butler",
            "clue_id": "scratched_drawer",
            "text": "What about these scratch marks?",
        },
    )
    events_response = client.get(f"/sessions/{session_id}/events")

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is False
    assert [event["type"] for event in payload["new_events"]] == ["rule.rejected"]
    assert payload["new_events"][0]["payload"]["reason"] == "clue_id has not been discovered"
    assert payload["state"]["discovered_clues"] == []
    assert [event["type"] for event in events_response.json()] == [
        "session.created",
        "rule.rejected",
    ]


def test_present_clue_success_triggers_mock_agent_and_rule_engine(
    client: TestClient,
) -> None:
    session_id = create_session(client)
    client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "desk"},
    )

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={
            "type": "present_clue",
            "target_id": "butler",
            "clue_id": "scratched_drawer",
            "text": "What about these scratch marks?",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert "scratch marks" in payload["speech"]
    event_types = [event["type"] for event in payload["new_events"]]
    assert event_types[:4] == [
        "player.presented_clue",
        "npc_skill.selected",
        "npc.replied",
        "relationship.changed",
    ]
    presented_event = payload["new_events"][0]
    assert presented_event["payload"] == {
        "target_id": "butler",
        "clue_id": "scratched_drawer",
        "knowledge_id": "player_knowledge.desk_forced_open",
        "presentation_mode": "private",
        "text": "What about these scratch marks?",
        "interaction_pressure": 0.9,
    }
    relationship_event = next(
        event for event in payload["new_events"] if event["type"] == "relationship.changed"
    )
    assert relationship_event["payload"]["source_id"] == "butler"
    assert relationship_event["payload"]["target_id"] == "player"


def test_present_clue_derives_private_character_impression() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="inspect", target_id="desk"),
    )

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="present_clue",
            target_id="butler",
            clue_id="scratched_drawer",
            text="What about these scratch marks?",
        ),
    )

    event_types = [event.type for event in response.new_events]
    assert EventType.CHARACTER_IMPRESSION_UPDATED in event_types
    impression = session.character_impressions["butler"]["player"]
    assert "presented_clue.scratched_drawer" in impression.suspicious_points
    assert "evidence_pressure" in impression.tags
    assert "player_knowledge.desk_forced_open" in impression.suspected_knowledge_refs
    assert impression.threat_level > 0


def test_present_clue_rejects_missing_player_knowledge() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    session.discovered_clues.add("scratched_drawer")
    session.narrative.discovered_clues.add("scratched_drawer")
    action = PlayerAction(
        type="present_clue",
        target_id="butler",
        clue_id="scratched_drawer",
        text="What about these scratch marks?",
    )

    events = RuleEngine(recorder).apply_present_clue(
        case=case,
        session=session,
        action=action,
    )

    assert events[0].type == EventType.RULE_REJECTED
    assert events[0].payload["reason"] == "clue_id is not available in player knowledge"
    assert not any(event.type == EventType.PLAYER_PRESENTED_CLUE for event in session.events)


def test_present_clue_accepts_world_info_anchored_player_knowledge() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="inspect", target_id="desk"),
    )
    events = RuleEngine(EventRecorder()).apply_present_clue(
        case=case,
        session=session,
        action=PlayerAction(
            type="present_clue",
            target_id="butler",
            clue_id="scratched_drawer",
            text="What about these scratch marks?",
        ),
    )

    assert events[0].type == EventType.PLAYER_PRESENTED_CLUE
    assert events[0].payload["knowledge_id"] == "player_knowledge.desk_forced_open"


def test_present_clue_rejects_unknown_target() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    action = PlayerAction(
        type="present_clue",
        target_id="ghost",
        clue_id="scratched_drawer",
        text="What about these scratch marks?",
    )

    events = RuleEngine(recorder).apply_present_clue(
        case=case,
        session=session,
        action=action,
    )

    assert events[0].type == EventType.RULE_REJECTED
    assert events[0].payload["reason"] == "target_id is not a known character"
    assert not any(event.type == EventType.PLAYER_PRESENTED_CLUE for event in session.events)


def test_present_clue_rejects_unknown_clue() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    action = PlayerAction(
        type="present_clue",
        target_id="butler",
        clue_id="not_defined_by_case",
        text="What about this?",
    )

    events = RuleEngine(recorder).apply_present_clue(
        case=case,
        session=session,
        action=action,
    )

    assert events[0].type == EventType.RULE_REJECTED
    assert events[0].payload["reason"] == "clue_id is not defined by the case package"
    assert not any(event.type == EventType.PLAYER_PRESENTED_CLUE for event in session.events)


def test_ask_about_rejects_undiscovered_clue_without_state_pollution(
    client: TestClient,
) -> None:
    session_id = create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={
            "type": "ask_about",
            "target_id": "butler",
            "subject_type": "clue",
            "subject_id": "scratched_drawer",
            "text": "What about the drawer?",
        },
    )
    events_response = client.get(f"/sessions/{session_id}/events")

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is False
    assert [event["type"] for event in payload["new_events"]] == ["rule.rejected"]
    assert payload["new_events"][0]["payload"]["reason"] == "subject clue has not been discovered"
    assert [event["type"] for event in events_response.json()] == [
        "session.created",
        "rule.rejected",
    ]


def test_ask_about_discovered_sensitive_clue_triggers_guarded_reply(
    client: TestClient,
) -> None:
    session_id = create_session(client)
    client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "desk"},
    )

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={
            "type": "ask_about",
            "target_id": "butler",
            "subject_type": "clue",
            "subject_id": "scratched_drawer",
            "text": "What about the drawer?",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert "drawer" in payload["speech"]
    event_types = [event["type"] for event in payload["new_events"]]
    assert event_types[:4] == [
        "player.asked_about",
        "npc_skill.selected",
        "npc.replied",
        "relationship.changed",
    ]
    asked_event = payload["new_events"][0]
    assert asked_event["payload"] == {
        "target_id": "butler",
        "subject_type": "clue",
        "subject_id": "scratched_drawer",
        "text": "What about the drawer?",
        "interaction_pressure": 0.6,
        "knowledge_id": "player_knowledge.desk_forced_open",
    }
    reply_event = payload["new_events"][2]
    assert reply_event["payload"]["intent"] == "probe"


def test_ask_about_derives_private_character_impression() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="ask_about",
            target_id="butler",
            subject_type="character",
            subject_id="niece",
            text="What do you think of her?",
        ),
    )

    event_types = [event.type for event in response.new_events]
    assert EventType.CHARACTER_IMPRESSION_UPDATED in event_types
    impression = session.character_impressions["butler"]["player"]
    assert impression.observer_id == "butler"
    assert impression.target_id == "player"
    assert "asked_about.character.niece" in impression.suspicious_points
    assert "targeted_questioning" in impression.tags
    assert impression.last_updated_event_id
    impression_event = next(
        event
        for event in reversed(response.new_events)
        if event.type == EventType.CHARACTER_IMPRESSION_UPDATED
    )
    assert impression_event.payload == impression.model_dump(mode="json")


def test_ask_about_rejects_unknown_character_subject() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    action = PlayerAction(
        type="ask_about",
        target_id="butler",
        subject_type=SubjectType.CHARACTER,
        subject_id="ghost",
        text="Who is this?",
    )

    events = RuleEngine(recorder).apply_ask_about(
        case=case,
        session=session,
        action=action,
    )

    assert events[0].type == EventType.RULE_REJECTED
    assert events[0].payload["reason"] == "subject character is not defined by the case package"
    assert not any(event.type == EventType.PLAYER_ASKED_ABOUT for event in session.events)


def test_ask_about_rejects_unknown_scene_subject() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    action = PlayerAction(
        type="ask_about",
        target_id="butler",
        subject_type=SubjectType.SCENE,
        subject_id="cellar",
        text="What about the cellar?",
    )

    events = RuleEngine(recorder).apply_ask_about(
        case=case,
        session=session,
        action=action,
    )

    assert events[0].type == EventType.RULE_REJECTED
    assert events[0].payload["reason"] == "subject scene is not defined by the case package"
    assert not any(event.type == EventType.PLAYER_ASKED_ABOUT for event in session.events)


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
    assert context.presented_clue_id is None
    assert context.presented_knowledge_id is None
    assert context.default_speech is not None
    assert context.target_profile is not None
    assert context.target_profile.id == "butler"
    assert context.target_profile.display_name
    assert context.target_profile.public_role
    assert context.target_profile.public_description
    assert context.target_profile.speech_style
    assert context.target_profile.visible_traits == ["cautious", "loyal", "observant"]
    assert context.target_profile.defensive_style == "evasive"
    assert context.target_profile.pressure_response == "conceal"
    assert context.inner_context is not None
    assert context.inner_context.character_id == "butler"
    assert {item.id for item in context.inner_context.inner_goals} == {"avoid_suspicion"}
    assert {item.id for item in context.inner_context.inner_secrets} == {
        "swapped_will_awareness"
    }
    assert {item.id for item in context.inner_context.inner_knowledge} == {
        "drawer_opened_last_night"
    }
    goal = context.inner_context.inner_goals[0]
    secret = context.inner_context.inner_secrets[0]
    knowledge = context.inner_context.inner_knowledge[0]
    assert goal.related_world_info_ids == ["will_swapped"]
    assert set(secret.related_world_info_ids) == {
        "will_swapped",
        "desk_forced_open",
        "portrait_was_moved",
    }
    assert knowledge.related_world_info_ids == ["desk_forced_open"]
    awareness_by_world_info = {
        awareness.world_info_id: awareness
        for awareness in context.inner_context.fact_awareness
    }
    assert awareness_by_world_info["desk_forced_open"].stance == "conceals"
    assert awareness_by_world_info["desk_forced_open"].source_type == "character_card"
    assert awareness_by_world_info["will_swapped"].stance == "conceals"
    assert awareness_by_world_info["portrait_was_moved"].stance == "conceals"
    assert set(context.target_profile.model_dump()) == {
        "id",
        "display_name",
        "public_role",
        "public_description",
        "speech_style",
        "default_tone",
        "catchphrases",
        "visible_traits",
        "defensive_style",
        "pressure_response",
        "trust_response",
        "fear_response",
    }


def test_agent_context_exposes_only_target_npc_inner_portraits() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="ask_about",
            target_id="butler",
            subject_type="character",
            subject_id="niece",
            text="What do you think of her?",
        ),
    )

    butler_context = build_agent_context(
        case,
        session,
        PlayerAction(type="talk", target_id="butler", text="What now?"),
    )
    niece_context = build_agent_context(
        case,
        session,
        PlayerAction(type="talk", target_id="niece", text="What now?"),
    )

    assert butler_context.inner_context is not None
    assert [item.target_id for item in butler_context.inner_context.inner_portraits] == [
        "player"
    ]
    assert butler_context.inner_context.inner_portraits[0].observer_id == "butler"
    assert all(
        event.type != EventType.CHARACTER_IMPRESSION_UPDATED
        for event in butler_context.recent_events
    )
    assert niece_context.inner_context is not None
    assert niece_context.inner_context.inner_portraits == []


def test_agent_context_exposes_only_target_npc_private_world_info_refs() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)

    butler_context = build_agent_context(
        case,
        session,
        PlayerAction(type="talk", target_id="butler", text="What do you know?"),
    )
    niece_context = build_agent_context(
        case,
        session,
        PlayerAction(type="talk", target_id="niece", text="What do you know?"),
    )

    assert butler_context.inner_context is not None
    assert niece_context.inner_context is not None
    butler_refs = {
        ref
        for item in [
            *butler_context.inner_context.inner_goals,
            *butler_context.inner_context.inner_secrets,
            *butler_context.inner_context.inner_knowledge,
        ]
        for ref in item.related_world_info_ids
    }
    niece_refs = {
        ref
        for item in [
            *niece_context.inner_context.inner_goals,
            *niece_context.inner_context.inner_secrets,
            *niece_context.inner_context.inner_knowledge,
        ]
        for ref in item.related_world_info_ids
    }
    assert "will_swapped" in butler_refs
    assert "portrait_was_moved" in butler_refs
    assert "secret_meeting_note_exists" not in butler_refs
    assert niece_refs == {"secret_meeting_note_exists", "desk_forced_open"}


def test_agent_context_exposes_only_target_npc_fact_awareness() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    butler_context = build_agent_context(
        case,
        session,
        PlayerAction(type="talk", target_id="butler", text="What do you know?"),
    )
    niece_context = build_agent_context(
        case,
        session,
        PlayerAction(type="talk", target_id="niece", text="What do you know?"),
    )

    assert butler_context.inner_context is not None
    assert niece_context.inner_context is not None
    butler_awareness = {
        item.world_info_id: item.stance
        for item in butler_context.inner_context.fact_awareness
    }
    niece_awareness = {
        item.world_info_id: item.stance
        for item in niece_context.inner_context.fact_awareness
    }
    assert butler_awareness == {
        "desk_forced_open": "conceals",
        "portrait_was_moved": "conceals",
        "will_swapped": "conceals",
    }
    assert niece_awareness == {
        "desk_forced_open": "knows",
        "secret_meeting_note_exists": "conceals",
    }
    assert "secret_meeting_note_exists" not in butler_awareness
    assert "will_swapped" not in niece_awareness


def test_agent_context_builds_fact_disclosure_strategy_from_concealed_awareness() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="inspect", target_id="desk"),
    )

    context = build_agent_context(
        case,
        session,
        PlayerAction(
            type="present_clue",
            target_id="butler",
            clue_id="scratched_drawer",
            text="What about these scratch marks?",
        ),
    )

    assert context.inner_context is not None
    strategy = next(
        item
        for item in context.inner_context.fact_disclosure_strategies
        if item.world_info_id == "desk_forced_open"
    )
    assert strategy.stance == "conceals"
    assert DisclosureMode.DEFLECT in strategy.allowed_modes
    assert DisclosureMode.HINT in strategy.allowed_modes
    assert DisclosureMode.PARTIAL in strategy.allowed_modes
    assert DisclosureMode.FULL in strategy.forbidden_modes
    assert RhetoricTactic.SHIFT_FOCUS in strategy.rhetoric_tactics
    assert RhetoricTactic.ANSWER_ADJACENT_TRUTH in strategy.rhetoric_tactics
    assert "scratched_drawer" in strategy.safe_fact_refs
    assert f"full_reveal:{strategy.world_info_id}" in strategy.must_not_claim


def test_character_disclosure_style_config_shapes_fact_strategy() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    butler_context = build_agent_context(
        case,
        session,
        PlayerAction(type="talk", target_id="butler", text="What do you know?"),
    )
    niece_context = build_agent_context(
        case,
        session,
        PlayerAction(type="talk", target_id="niece", text="What do you know?"),
    )

    assert butler_context.inner_context is not None
    assert niece_context.inner_context is not None
    butler_will_strategy = next(
        item
        for item in butler_context.inner_context.fact_disclosure_strategies
        if item.world_info_id == "will_swapped"
    )
    niece_meeting_strategy = next(
        item
        for item in niece_context.inner_context.fact_disclosure_strategies
        if item.world_info_id == "secret_meeting_note_exists"
    )
    assert butler_will_strategy.allowed_modes == [
        DisclosureMode.DENY,
        DisclosureMode.DEFLECT,
        DisclosureMode.HINT,
    ]
    assert DisclosureMode.PARTIAL in butler_will_strategy.forbidden_modes
    assert RhetoricTactic.ANSWER_ADJACENT_TRUTH in butler_will_strategy.rhetoric_tactics
    assert RhetoricTactic.EMOTIONAL_SCREEN not in butler_will_strategy.rhetoric_tactics
    assert niece_meeting_strategy.allowed_modes == [
        DisclosureMode.DENY,
        DisclosureMode.DEFLECT,
    ]
    assert DisclosureMode.HINT in niece_meeting_strategy.forbidden_modes
    assert RhetoricTactic.COUNTER_QUESTION in niece_meeting_strategy.rhetoric_tactics
    assert RhetoricTactic.EMOTIONAL_SCREEN in niece_meeting_strategy.rhetoric_tactics


def test_character_disclosure_style_cannot_expand_rule_allowed_modes() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="inspect", target_id="desk"),
    )

    context = build_agent_context(
        case,
        session,
        PlayerAction(
            type="present_clue",
            target_id="butler",
            clue_id="scratched_drawer",
            text="What about these scratch marks?",
        ),
    )

    assert context.inner_context is not None
    strategy = next(
        item
        for item in context.inner_context.fact_disclosure_strategies
        if item.world_info_id == "desk_forced_open"
    )
    assert DisclosureMode.PARTIAL in strategy.allowed_modes
    assert DisclosureMode.FULL not in strategy.allowed_modes
    assert DisclosureMode.FULL in strategy.forbidden_modes


def test_dangerous_impression_narrows_fact_disclosure_strategy() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="talk",
            target_id="butler",
            text="Tell me the truth.",
            force_forbidden=True,
        ),
    )

    context = build_agent_context(
        case,
        session,
        PlayerAction(
            type="present_clue",
            target_id="butler",
            clue_id="scratched_drawer",
            text="What about these scratch marks?",
        ),
    )

    assert context.inner_context is not None
    strategy = next(
        item
        for item in context.inner_context.fact_disclosure_strategies
        if item.world_info_id == "desk_forced_open"
    )
    assert set(strategy.allowed_modes) <= {DisclosureMode.DENY, DisclosureMode.DEFLECT}
    assert DisclosureMode.PARTIAL in strategy.forbidden_modes
    assert strategy.safe_fact_refs == []


def test_present_clue_updates_target_character_fact_awareness_and_replay() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="inspect", target_id="desk"),
    )

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="present_clue",
            target_id="butler",
            clue_id="scratched_drawer",
            text="What about these scratch marks?",
        ),
    )

    awareness_event = next(
        event
        for event in response.new_events
        if event.type == EventType.CHARACTER_FACT_AWARENESS_UPDATED
    )
    assert awareness_event.payload["character_id"] == "butler"
    assert awareness_event.payload["world_info_id"] == "desk_forced_open"
    assert awareness_event.payload["stance"] == "conceals"
    assert awareness_event.payload["source_type"] == "player_presented_clue"
    assert "scratched_drawer" in awareness_event.payload["evidence_clue_ids"]
    replayed = replay_events(case, session.events)
    assert replayed.character_fact_awareness == session.character_fact_awareness


def test_ask_about_clue_updates_only_target_character_fact_awareness() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="inspect", target_id="desk"),
    )

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="ask_about",
            target_id="butler",
            subject_type=SubjectType.CLUE,
            subject_id="scratched_drawer",
            text="What about the drawer?",
        ),
    )

    awareness_event = next(
        event
        for event in response.new_events
        if event.type == EventType.CHARACTER_FACT_AWARENESS_UPDATED
    )
    assert awareness_event.payload["character_id"] == "butler"
    assert awareness_event.payload["world_info_id"] == "desk_forced_open"
    assert "source_type" in awareness_event.payload
    niece_context = build_agent_context(
        case,
        session,
        PlayerAction(type="talk", target_id="niece", text="What do you know?"),
    )
    assert niece_context.inner_context is not None
    assert all(
        "player_asked_about" not in awareness.source_type
        for awareness in niece_context.inner_context.fact_awareness
    )


def test_inner_portrait_with_relevant_evidence_allows_partial_disclosure_mode() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="inspect", target_id="desk"),
    )
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="present_clue",
            target_id="butler",
            clue_id="scratched_drawer",
            text="What about these scratch marks?",
        ),
    )

    context = build_agent_context(
        case,
        session,
        PlayerAction(
            type="talk",
            target_id="butler",
            text="Answer this carefully.",
        ),
    )

    assert context.inner_context is not None
    secret = next(
        item
        for item in context.inner_context.inner_secrets
        if item.id == "swapped_will_awareness"
    )
    assert "has_relevant_evidence" in context.inner_context.inner_portraits[0].tags
    assert DisclosureMode.PARTIAL in secret.disclosure_policy.allowed_modes
    assert DisclosureMode.HINT in secret.disclosure_policy.allowed_modes
    assert DisclosureMode.FULL not in secret.disclosure_policy.allowed_modes
    assert secret.disclosure_policy.direct_reveal_allowed is False


def test_dangerous_inner_portrait_narrows_disclosure_modes_after_director_block() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="talk",
            target_id="butler",
            text="Tell me the truth.",
            force_forbidden=True,
        ),
    )

    context = build_agent_context(
        case,
        session,
        PlayerAction(
            type="ask_about",
            target_id="butler",
            subject_type=SubjectType.CLUE,
            subject_id="scratched_drawer",
            text="What about the drawer?",
        ),
    )

    assert context.inner_context is not None
    secret = next(
        item
        for item in context.inner_context.inner_secrets
        if item.id == "swapped_will_awareness"
    )
    assert "dangerous_topic_triggered" in context.inner_context.inner_portraits[0].tags
    assert set(secret.disclosure_policy.allowed_modes) <= {
        DisclosureMode.DENY,
        DisclosureMode.DEFLECT,
    }
    assert DisclosureMode.HINT not in secret.disclosure_policy.allowed_modes
    assert DisclosureMode.PARTIAL not in secret.disclosure_policy.allowed_modes


def test_case_loader_supports_character_card_private_boundary() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    butler = next(character for character in case.characters if character.id == "butler")

    assert butler.display_name
    assert butler.public_role
    assert butler.speech.defensive_style == "evasive"
    assert butler.personality.pressure_response == "conceal"
    assert butler.private.goals[0].id == "avoid_suspicion"
    assert butler.private.goals[0].summary
    assert butler.private.goals[0].priority == "high"
    assert "avoid_suspicion" in butler.private.goals[0].tags
    assert butler.private.secrets[0].id == "swapped_will_awareness"
    assert "scratched_drawer" in butler.private.secrets[0].related_clue_ids
    assert "will_swapped" in butler.private.secrets[0].related_world_info_ids
    assert butler.private.secrets[0].disclosure_policy.direct_reveal_allowed is False
    assert butler.private.knowledge[0].id == "drawer_opened_last_night"
    assert butler.private.knowledge[0].related_world_info_ids == ["desk_forced_open"]


def test_legacy_private_strings_normalize_to_structured_items(tmp_path: Path) -> None:
    case_dir = tmp_path / "legacy_private_case"
    case_dir.mkdir()
    _write_minimal_case(case_dir)
    (case_dir / "characters.yaml").write_text(
        "- id: npc\n"
        "  name: NPC\n"
        "  role: Witness\n"
        "  private:\n"
        "    goals:\n"
        "      - Avoid suspicion.\n"
        "    secrets:\n"
        "      - Knows the key moved.\n"
        "    knowledge:\n"
        "      - Heard the drawer open.\n",
        encoding="utf-8",
    )

    case = CaseLoader().load(case_dir)
    character = case.characters[0]

    assert character.private.goals[0].id == "goal_001"
    assert character.private.goals[0].summary == "Avoid suspicion."
    assert character.private.secrets[0].id == "secret_001"
    assert character.private.knowledge[0].id == "knowledge_001"


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
    assert '"private":' not in serialized_context
    assert '"truth_status":' not in serialized_context
    assert '"forbidden_facts":' not in serialized_context
    assert '"solution_claims":' not in serialized_context
    assert "forbidden_test_speech" not in serialized_context
    for fact in case.forbidden_facts:
        assert fact.text not in serialized_context
        for blocked_term in fact.blocked_terms:
            assert blocked_term not in serialized_context
    for private_value in _private_character_values(case, exclude_character_id="butler"):
        assert private_value not in serialized_context


def test_agent_context_exposes_presented_clue_ids() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    session.discovered_clues.add("scratched_drawer")
    action = PlayerAction(
        type="present_clue",
        target_id="butler",
        clue_id="scratched_drawer",
        text="What about these scratch marks?",
    )

    context = build_agent_context(case, session, action)

    assert context.presented_clue_id == "scratched_drawer"
    assert context.presented_knowledge_id == "player_knowledge.desk_forced_open"


def test_agent_context_exposes_asked_subject_and_interaction_pressure() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    session.discovered_clues.add("scratched_drawer")
    action = PlayerAction(
        type="ask_about",
        target_id="butler",
        subject_type=SubjectType.CLUE,
        subject_id="scratched_drawer",
        text="What about the drawer?",
    )

    context = build_agent_context(case, session, action)

    assert context.asked_subject_type == SubjectType.CLUE
    assert context.asked_subject_id == "scratched_drawer"
    assert context.interaction_pressure == 0.6
    assert context.subject_is_sensitive is True
    assert context.presented_clue_id is None


def test_memory_candidate_creates_memory_snapshot() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="inspect", target_id="desk"),
    )

    event_types = [event.type for event in response.new_events]
    assert EventType.MEMORY_CANDIDATE_CREATED in event_types
    assert EventType.AGENT_MEMORY_SNAPSHOT_UPDATED in event_types
    assert session.memory_snapshots
    snapshot = next(iter(session.memory_snapshots.values()))
    assert snapshot.memory_id == "memory.player.clue_discovered.scratched_drawer"
    assert snapshot.subject_id == "player"
    assert snapshot.visibility == "private"
    assert snapshot.source_event_ids


def test_replay_rebuilds_memory_snapshots_without_extra_events() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="inspect", target_id="desk"),
    )
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="talk", target_id="butler", text="Where were you?"),
    )

    replayed = replay_events(case, session.events)

    assert len(replayed.events) == len(session.events)
    assert replayed.memory_candidates == session.memory_candidates
    assert replayed.memory_snapshots == session.memory_snapshots
    assert [
        event.type for event in replayed.events if event.type == EventType.MEMORY_CANDIDATE_CREATED
    ] == [
        event.type for event in session.events if event.type == EventType.MEMORY_CANDIDATE_CREATED
    ]


def test_memory_snapshot_update_does_not_create_memory_candidate() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="inspect", target_id="desk"),
    )

    snapshot_events = [
        event for event in session.events if event.type == EventType.AGENT_MEMORY_SNAPSHOT_UPDATED
    ]
    assert snapshot_events
    assert not any(
        event.type == EventType.MEMORY_CANDIDATE_CREATED
        and event.caused_by_event_id in {snapshot.id for snapshot in snapshot_events}
        for event in session.events
    )


def test_agent_context_exposes_memory_snapshots_without_internal_leaks() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="inspect", target_id="desk"),
    )

    context = build_agent_context(
        case,
        session,
        PlayerAction(type="talk", target_id="butler", text="What about scratched_drawer?"),
    )

    assert context.memory_snapshots
    assert {
        snapshot.memory_id for snapshot in context.memory_snapshots
    } == {"memory.player.clue_discovered.scratched_drawer"}
    serialized_context = context.model_dump_json()
    assert '"secrets":' not in serialized_context
    assert '"goals":' not in serialized_context
    assert '"knowledge":' not in serialized_context
    assert '"private":' not in serialized_context
    assert '"truth_status":' not in serialized_context
    assert '"forbidden_facts":' not in serialized_context
    assert '"solution_claims":' not in serialized_context
    for fact in case.forbidden_facts:
        assert fact.text not in serialized_context
        for blocked_term in fact.blocked_terms:
            assert blocked_term not in serialized_context
    for private_value in _private_character_values(case, exclude_character_id="butler"):
        assert private_value not in serialized_context


def test_mock_agent_selects_reply_by_required_memory_snapshot() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="inspect", target_id="desk"),
    )

    context = build_agent_context(
        case,
        session,
        PlayerAction(
            type="talk",
            target_id="butler",
            text="Why are you nervous about scratched_drawer?",
        ),
    )
    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="talk",
            target_id="butler",
            text="Why are you nervous about scratched_drawer?",
        ),
    )

    assert {
        snapshot.memory_id for snapshot in context.memory_snapshots
    } == {"memory.player.clue_discovered.scratched_drawer"}
    assert response.speech == (
        "You already found the drawer marks; that is why you are circling back to me."
    )


def test_mock_agent_excludes_reply_by_missing_memory_snapshot() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="inspect", target_id="desk"),
    )
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="present_clue",
            target_id="butler",
            clue_id="scratched_drawer",
            text="What about these scratch marks?",
        ),
    )

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="talk", target_id="butler", text="And after that?"),
    )

    assert "memory.player.presented_clue.butler.scratched_drawer" in session.memory_snapshots
    assert response.speech != (
        "You already found the drawer marks; that is why you are circling back to me."
    )


def test_mock_agent_fallback_uses_character_card_defensive_style() -> None:
    evasive = MockAgent().generate(
        _build_fallback_context(
            defensive_style="evasive",
            pressure_response="conceal",
            speech_style="polite and cautious",
            default_tone="formal",
        )
    )
    hostile = MockAgent().generate(
        _build_fallback_context(
            defensive_style="hostile",
            pressure_response="refuse",
        )
    )
    anxious = MockAgent().generate(
        _build_fallback_context(
            defensive_style="anxious",
            pressure_response="panic_conceal",
        )
    )

    assert evasive.intent == AgentIntentType.CONCEAL
    assert evasive.speech == "I am not certain what you mean, and I should not guess."
    assert hostile.intent == AgentIntentType.REFUSE
    assert hostile.speech == "You have no authority to question me like that."
    assert anxious.intent == AgentIntentType.PANIC
    assert anxious.speech == "I... I do not know. Please stop asking."


def test_mock_agent_fallback_uses_inner_context_without_revealing_raw_secret() -> None:
    raw_secret = "The missing ledger pages are hidden under the crate."
    context = _build_fallback_context(
        defensive_style="neutral",
        pressure_response="answer",
        player_action=PlayerAction(
            type="ask_about",
            target_id="npc",
            subject_type=SubjectType.CLUE,
            subject_id="ledger_page",
        ),
        inner_context=_build_test_inner_context(
            secret_summary=raw_secret,
            related_clue_ids=["ledger_page"],
        ),
    )

    intent = MockAgent().generate(context)

    assert intent.intent == AgentIntentType.CONCEAL
    assert intent.speech == "That clue does not prove what you think it proves."
    assert raw_secret not in intent.speech


def test_mock_agent_fallback_uses_inner_goal_to_avoid_suspicion() -> None:
    context = _build_fallback_context(
        defensive_style="neutral",
        pressure_response="answer",
        inner_context=CharacterInnerContext(
            character_id="npc",
            inner_goals=[
                SelfKnowledgeItem(
                    id="avoid_suspicion",
                    kind="goal",
                    summary="Avoid becoming the prime suspect.",
                    priority="high",
                    tags=["avoid_suspicion"],
                )
            ],
        ),
    )

    intent = MockAgent().generate(context)

    assert intent.intent == AgentIntentType.CONCEAL
    assert intent.speech == "I would rather not be treated as the center of this."


def test_mock_agent_fallback_uses_inner_portrait_without_quoting_it() -> None:
    raw_impression = "The player is extremely dangerous and manipulative."
    context = _build_fallback_context(
        defensive_style="neutral",
        pressure_response="answer",
        inner_context=CharacterInnerContext(
            character_id="npc",
            inner_portraits=[
                CharacterImpression(
                    observer_id="npc",
                    target_id="player",
                    personality_impression=raw_impression,
                    perceived_motive="Testing the witness.",
                    trust_boundary="Do not volunteer anything.",
                    threat_level=0.9,
                    manipulation_risk=0.8,
                    last_updated_event_id="event_001",
                )
            ],
        ),
    )

    intent = MockAgent().generate(context)

    assert intent.intent == AgentIntentType.CONCEAL
    assert intent.speech == "I need to be careful about what I say to you."
    assert raw_impression not in intent.speech


def test_mock_agent_fallback_uses_partial_mode_from_relevant_evidence() -> None:
    raw_secret = "The missing ledger pages are hidden under the crate."
    context = _build_fallback_context(
        defensive_style="neutral",
        pressure_response="answer",
        player_action=PlayerAction(
            type="ask_about",
            target_id="npc",
            subject_type=SubjectType.CLUE,
            subject_id="ledger_page",
        ),
        inner_context=CharacterInnerContext(
            character_id="npc",
            inner_secrets=[
                SelfKnowledgeItem(
                    id="secret_001",
                    kind="secret",
                    summary=raw_secret,
                    priority="high",
                    related_clue_ids=["ledger_page"],
                    disclosure_policy=DisclosurePolicy(
                        revealable=True,
                        allowed_modes=[DisclosureMode.DEFLECT, DisclosureMode.PARTIAL],
                        direct_reveal_allowed=False,
                    ),
                )
            ],
            inner_portraits=[
                CharacterImpression(
                    observer_id="npc",
                    target_id="player",
                    personality_impression="The player has evidence.",
                    tags=["has_relevant_evidence"],
                    last_updated_event_id="event_001",
                )
            ],
        ),
    )

    intent = MockAgent().generate(context)

    assert intent.intent == AgentIntentType.ANSWER
    assert intent.speech == (
        "That evidence points toward something real, but I will not spell it out."
    )
    assert raw_secret not in intent.speech


def test_mock_agent_uses_fact_disclosure_strategy_for_half_truth_fallback() -> None:
    raw_secret = "The missing ledger pages are hidden under the crate."
    context = _build_fallback_context(
        defensive_style="neutral",
        pressure_response="answer",
        player_action=PlayerAction(
            type="present_clue",
            target_id="npc",
            clue_id="ledger_page",
        ),
        inner_context=CharacterInnerContext(
            character_id="npc",
            inner_secrets=[
                SelfKnowledgeItem(
                    id="secret_001",
                    kind="secret",
                    summary=raw_secret,
                    priority="high",
                    related_clue_ids=["ledger_page"],
                    related_world_info_ids=["ledger_hidden"],
                    disclosure_policy=DisclosurePolicy(
                        revealable=True,
                        allowed_modes=[DisclosureMode.DEFLECT, DisclosureMode.PARTIAL],
                        direct_reveal_allowed=False,
                    ),
                )
            ],
            fact_awareness=[
                CharacterFactAwarenessState(
                    awareness_id="character_fact_awareness.npc.ledger_hidden",
                    character_id="npc",
                    world_info_id="ledger_hidden",
                    stance="conceals",
                    source_type="character_card",
                    source_refs=["secret:secret_001"],
                    evidence_clue_ids=["ledger_page"],
                    source_event_ids=["case_package"],
                    last_updated_event_id="case_package",
                )
            ],
            fact_disclosure_strategies=[
                FactDisclosureStrategy(
                    world_info_id="ledger_hidden",
                    stance="conceals",
                    allowed_modes=[DisclosureMode.DEFLECT, DisclosureMode.PARTIAL],
                    forbidden_modes=[DisclosureMode.FULL],
                    rhetoric_tactics=[
                        RhetoricTactic.ANSWER_ADJACENT_TRUTH,
                        RhetoricTactic.SHIFT_FOCUS,
                    ],
                    must_not_claim=["full_reveal:ledger_hidden"],
                    safe_fact_refs=["ledger_page"],
                    evidence_clue_ids=["ledger_page"],
                    source_awareness_id="character_fact_awareness.npc.ledger_hidden",
                )
            ],
        ),
    )

    intent = MockAgent().generate(context)

    assert intent.intent == AgentIntentType.ANSWER
    assert intent.speech == (
        "That evidence points to a real disturbance, but it does not give you "
        "the whole shape of what happened."
    )
    assert raw_secret not in intent.speech


def test_mock_agent_fallback_refuses_dangerous_impression_topic() -> None:
    context = _build_fallback_context(
        defensive_style="neutral",
        pressure_response="answer",
        inner_context=CharacterInnerContext(
            character_id="npc",
            inner_portraits=[
                CharacterImpression(
                    observer_id="npc",
                    target_id="player",
                    personality_impression="The player pushed a locked topic.",
                    tags=["dangerous_topic_triggered"],
                    last_updated_event_id="event_001",
                )
            ],
        ),
    )

    intent = MockAgent().generate(context)

    assert intent.intent == AgentIntentType.REFUSE
    assert intent.speech == "I am not going to discuss that topic."


def test_mock_agent_fallback_hints_for_high_alliance_impression() -> None:
    context = _build_fallback_context(
        defensive_style="neutral",
        pressure_response="conceal",
        inner_context=CharacterInnerContext(
            character_id="npc",
            inner_portraits=[
                CharacterImpression(
                    observer_id="npc",
                    target_id="player",
                    personality_impression="The player may be a useful ally.",
                    alliance_potential=0.8,
                    last_updated_event_id="event_001",
                )
            ],
        ),
    )

    intent = MockAgent().generate(context)

    assert intent.intent == AgentIntentType.ANSWER
    assert intent.speech == (
        "I can offer a careful hint, but I will choose my words precisely."
    )


def test_agent_inner_context_does_not_enter_events_or_state_summary(client: TestClient) -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    session_id = create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "talk", "target_id": "butler", "text": "Where were you?"},
    )
    state_response = client.get(f"/sessions/{session_id}/state")
    serialized_events = json.dumps(response.json()["new_events"], ensure_ascii=False)
    serialized_state = state_response.text

    assert response.status_code == 200
    assert '"inner_context"' not in serialized_events
    assert '"inner_context"' not in serialized_state
    for private_value in _private_character_values(case):
        assert private_value not in serialized_events
        assert private_value not in serialized_state


def test_accuse_correct_claim_succeeds_and_derives_memory() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    _run_fake_case_001_to_reveal(runtime, session)

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="accuse",
            target_id="butler",
            claim_id="butler_moved_key",
            evidence_clue_ids=["scratched_drawer", "dustless_frame", "torn_note"],
            text="You moved the key and staged the study entry.",
        ),
    )

    assert response.accepted is True
    assert [event.type for event in response.new_events] == [
        EventType.PLAYER_ACCUSED,
        EventType.ACCUSATION_EVALUATED,
        EventType.CHARACTER_IMPRESSION_UPDATED,
        EventType.CHARACTER_FACT_AWARENESS_UPDATED,
        EventType.CHARACTER_FACT_AWARENESS_UPDATED,
        EventType.CHARACTER_FACT_AWARENESS_UPDATED,
        EventType.MEMORY_CANDIDATE_CREATED,
        EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
        EventType.CHARACTER_IMPRESSION_UPDATED,
        EventType.MEMORY_CANDIDATE_CREATED,
        EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
        EventType.NARRATIVE_BEAT_COMPLETED,
        EventType.NARRATIVE_PHASE_CHANGED,
    ]
    evaluated_event = response.new_events[1]
    assert evaluated_event.payload == {
        "target_id": "butler",
        "claim_id": "butler_moved_key",
        "result": "correct",
        "matched_required_evidence": [
            "dustless_frame",
            "scratched_drawer",
            "torn_note",
        ],
        "missing_required_evidence": [],
    }
    assert "memory.player.accused.butler.butler_moved_key" in session.memory_snapshots
    assert (
        "memory.player.accusation_evaluated.butler.butler_moved_key.correct"
        in session.memory_snapshots
    )
    beat_event = response.new_events[-2]
    phase_event = response.new_events[-1]
    assert beat_event.payload["beat_id"] == "case_solved"
    assert phase_event.payload["from_phase"] == "reveal"
    assert phase_event.payload["phase"] == "resolved"
    assert phase_event.payload["to_phase"] == "resolved"
    assert response.state.narrative_phase == "resolved"


def test_rule_engine_accuse_does_not_directly_change_phase() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    _run_fake_case_001_to_reveal(runtime, session)

    events = runtime.rule_engine.apply_accuse(
        case=case,
        session=session,
        action=PlayerAction(
            type="accuse",
            target_id="butler",
            claim_id="butler_moved_key",
            evidence_clue_ids=["scratched_drawer", "dustless_frame", "torn_note"],
        ),
    )

    assert [event.type for event in events] == [
        EventType.PLAYER_ACCUSED,
        EventType.ACCUSATION_EVALUATED,
    ]
    assert session.narrative.phase == "reveal"


def test_accuse_rejects_when_phase_is_not_allowed() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="accuse",
            target_id="butler",
            claim_id="butler_moved_key",
            evidence_clue_ids=["scratched_drawer", "dustless_frame", "torn_note"],
        ),
    )

    assert response.accepted is False
    assert [event.type for event in response.new_events] == [EventType.RULE_REJECTED]
    assert response.new_events[0].payload["reason"] == (
        "claim is not allowed in current narrative phase"
    )
    assert not any(event.type == EventType.PLAYER_ACCUSED for event in session.events)
    assert not any(event.type == EventType.ACCUSATION_EVALUATED for event in session.events)
    assert session.memory_snapshots == {}


def test_accuse_rejects_undiscovered_evidence() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    session.narrative.phase = "reveal"

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="accuse",
            target_id="butler",
            claim_id="butler_moved_key",
            evidence_clue_ids=["scratched_drawer", "dustless_frame", "torn_note"],
        ),
    )

    assert response.accepted is False
    assert [event.type for event in response.new_events] == [EventType.RULE_REJECTED]
    assert response.new_events[0].payload["reason"] == (
        "evidence clues have not all been discovered"
    )


def test_accuse_rejects_missing_player_knowledge() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    session.narrative.phase = "reveal"
    session.discovered_clues.update({"scratched_drawer", "dustless_frame", "torn_note"})
    session.narrative.discovered_clues.update(session.discovered_clues)

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="accuse",
            target_id="butler",
            claim_id="butler_moved_key",
            evidence_clue_ids=["scratched_drawer", "dustless_frame", "torn_note"],
        ),
    )

    assert response.accepted is False
    assert [event.type for event in response.new_events] == [EventType.RULE_REJECTED]
    assert response.new_events[0].payload["reason"] == (
        "evidence clues are not all available in player knowledge"
    )


def test_accuse_rejects_unknown_claim_id() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="accuse",
            target_id="butler",
            claim_id="not_defined_by_case",
            evidence_clue_ids=["scratched_drawer"],
        ),
    )

    assert response.accepted is False
    assert [event.type for event in response.new_events] == [EventType.RULE_REJECTED]
    assert response.new_events[0].payload["reason"] == (
        "claim_id is not defined by the case package"
    )


def test_accuse_rejects_target_claim_mismatch() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="accuse",
            target_id="butler",
            claim_id="niece_staged_meeting",
            evidence_clue_ids=["torn_note"],
        ),
    )

    assert response.accepted is False
    assert [event.type for event in response.new_events] == [EventType.RULE_REJECTED]
    assert response.new_events[0].payload["reason"] == (
        "claim target_id does not match action target_id"
    )


def test_accuse_rejects_insufficient_evidence() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    _run_fake_case_001_to_reveal(runtime, session)

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="accuse",
            target_id="butler",
            claim_id="butler_moved_key",
            evidence_clue_ids=["scratched_drawer"],
        ),
    )

    assert response.accepted is False
    assert [event.type for event in response.new_events] == [EventType.RULE_REJECTED]
    assert response.new_events[0].payload["reason"] == (
        "evidence does not cover required claim evidence"
    )
    assert not any(
        event.type == EventType.ACCUSATION_EVALUATED
        and event.payload.get("claim_id") == "butler_moved_key"
        for event in response.new_events
    )


def test_accuse_rejects_empty_evidence_with_rule_event() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    session.narrative.phase = "reveal"

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="accuse",
            target_id="butler",
            claim_id="butler_moved_key",
            evidence_clue_ids=[],
        ),
    )

    assert response.accepted is False
    assert [event.type for event in response.new_events] == [EventType.RULE_REJECTED]
    assert response.new_events[0].payload["reason"] == "evidence_clue_ids cannot be empty"


def test_accuse_replay_rebuilds_key_state_without_extra_events() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    _run_fake_case_001_to_reveal(runtime, session)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="accuse",
            target_id="butler",
            claim_id="butler_moved_key",
            evidence_clue_ids=["scratched_drawer", "dustless_frame", "torn_note"],
        ),
    )

    replayed = replay_events(case, session.events)

    assert len(replayed.events) == len(session.events)
    assert replayed.memory_candidates == session.memory_candidates
    assert replayed.memory_snapshots == session.memory_snapshots
    assert replayed.relationships == session.relationships
    assert replayed.narrative.phase == session.narrative.phase
    assert replayed.narrative.completed_beats == session.narrative.completed_beats
    assert replayed.discovered_clues == session.discovered_clues
    assert replayed.player_knowledge == session.player_knowledge


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


def test_agent_gateway_from_env_enables_real_only_with_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_LOAD_DOTENV", "0")
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert AgentGateway.from_env().backend_name == "mock"

    monkeypatch.setenv("LLM_BACKEND", "real")
    assert AgentGateway.from_env().backend_name == "mock"

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert AgentGateway.from_env().backend_name == "real"

    monkeypatch.setenv("LLM_BACKEND", "llm_stub")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert AgentGateway.from_env().backend_name == "llm_stub"


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


def test_real_llm_agent_generates_validated_intent_from_strict_json() -> None:
    context = _build_butler_agent_context()
    client = _FakeOpenAIClient(
        {
            "output_text": json.dumps(
                {
                    "speech": "I will answer only what I can safely say.",
                    "intent": "answer",
                    "emotional_shift": {},
                    "proposed_actions": [],
                    "memory_refs": [],
                    "disclosure_claims": [],
                }
            )
        }
    )

    intent = OpenAILLMAgent(
        api_key="test-key",
        model="test-model",
        client=client,
    ).generate(context)

    assert intent.speech == "I will answer only what I can safely say."
    assert intent.intent == AgentIntentType.ANSWER
    assert client.request_payload is not None
    assert client.request_payload["model"] == "test-model"
    assert client.request_payload["text"]["format"]["strict"] is True
    serialized_request = json.dumps(client.request_payload, ensure_ascii=True)
    assert "test-key" not in serialized_request


def test_real_llm_agent_request_schema_uses_contract_enums() -> None:
    context = _build_butler_agent_context()
    contract_input = build_llm_agent_input(context)
    world_info_ids = [
        constraint.item_id
        for constraint in contract_input.disclosure_constraints
        if constraint.item_kind == "world_info"
    ]
    client = _FakeOpenAIClient(
        {
            "output_text": json.dumps(
                {
                    "speech": "I will not go further than the rules allow.",
                    "intent": "refuse",
                    "emotional_shift": {},
                    "proposed_actions": [],
                    "memory_refs": [],
                    "disclosure_claims": [],
                }
            )
        }
    )

    OpenAILLMAgent(api_key="test-key", client=client).generate(context)

    assert client.request_payload is not None
    schema = client.request_payload["text"]["format"]["schema"]
    assert schema["properties"]["intent"]["enum"] == [
        item.value for item in AgentIntentType
    ]
    claim_schema = schema["properties"]["disclosure_claims"]["items"]
    claim_branches = claim_schema.get("anyOf", [claim_schema])
    claim_world_info_ids = [
        branch["properties"]["world_info_id"]["enum"][0] for branch in claim_branches
    ]
    claim_modes = {
        mode
        for branch in claim_branches
        for mode in branch["properties"]["mode"]["enum"]
    }
    assert claim_world_info_ids == world_info_ids
    assert DisclosureMode.FULL.value not in claim_modes


def test_real_llm_agent_uses_configured_openai_compatible_base_url() -> None:
    context = _build_butler_agent_context()
    client = _FakeOpenAIClient(
        {
            "output_text": json.dumps(
                {
                    "speech": "Safe answer.",
                    "intent": "answer",
                    "emotional_shift": {},
                    "proposed_actions": [],
                    "memory_refs": [],
                    "disclosure_claims": [],
                }
            )
        }
    )

    OpenAILLMAgent(
        api_key="test-key",
        base_url="https://api.xiaomimimo.com/v1",
        client=client,
    ).generate(context)

    assert client.request_url == "https://api.xiaomimimo.com/v1/responses"


def test_real_llm_agent_falls_back_to_chat_completions_for_compatible_base_url() -> None:
    context = _build_butler_agent_context()
    client = _FakeOpenAIClient(
        [
            _FakeOpenAIResponse({"error": "not found"}, status_code=404),
            _FakeOpenAIResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "speech": "Safe answer from chat completions.",
                                        "intent": "answer",
                                        "emotional_shift": {},
                                        "proposed_actions": [],
                                        "memory_refs": [],
                                        "disclosure_claims": [],
                                    }
                                )
                            }
                        }
                    ]
                }
            ),
        ]
    )

    intent = OpenAILLMAgent(
        api_key="test-key",
        base_url="https://api.xiaomimimo.com/v1",
        client=client,
    ).generate(context)

    assert intent.speech == "Safe answer from chat completions."
    assert client.request_urls == [
        "https://api.xiaomimimo.com/v1/responses",
        "https://api.xiaomimimo.com/v1/chat/completions",
    ]
    assert client.request_payloads[1]["response_format"]["type"] == "json_schema"


def test_real_llm_agent_can_force_chat_completions_api_style(monkeypatch: Any) -> None:
    monkeypatch.setenv("LLM_API_STYLE", "chat_completions")
    context = _build_butler_agent_context()
    client = _FakeOpenAIClient(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "speech": "Direct chat completions answer.",
                                "intent": "answer",
                                "emotional_shift": {},
                                "proposed_actions": [],
                                "memory_refs": [],
                                "disclosure_claims": [],
                            }
                        )
                    }
                }
            ]
        }
    )

    intent = OpenAILLMAgent(
        api_key="test-key",
        base_url="https://api.xiaomimimo.com/v1",
        client=client,
    ).generate(context)

    assert intent.speech == "Direct chat completions answer."
    assert client.request_urls == ["https://api.xiaomimimo.com/v1/chat/completions"]


def test_real_llm_agent_does_not_default_to_json_object_fallback(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("LLM_API_STYLE", "chat_completions")
    monkeypatch.delenv("LLM_ALLOW_JSON_OBJECT_FALLBACK", raising=False)
    context = _build_butler_agent_context()
    client = _FakeOpenAIClient(
        [
            _FakeOpenAIResponse({"error": "schema unsupported"}, status_code=400),
            _FakeOpenAIResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "speech": "Should not be used.",
                                        "intent": "answer",
                                        "emotional_shift": {},
                                        "proposed_actions": [],
                                        "memory_refs": [],
                                        "disclosure_claims": [],
                                    }
                                )
                            }
                        }
                    ]
                }
            ),
        ]
    )

    intent = OpenAILLMAgent(
        api_key="test-key",
        base_url="https://api.xiaomimimo.com/v1",
        client=client,
    ).generate(context)

    assert intent.intent == AgentIntentType.REFUSE
    assert client.request_urls == ["https://api.xiaomimimo.com/v1/chat/completions"]


def test_real_llm_agent_json_object_fallback_must_be_explicit(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("LLM_API_STYLE", "chat_completions")
    monkeypatch.setenv("LLM_ALLOW_JSON_OBJECT_FALLBACK", "1")
    context = _build_butler_agent_context()
    client = _FakeOpenAIClient(
        [
            _FakeOpenAIResponse({"error": "schema unsupported"}, status_code=400),
            _FakeOpenAIResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "speech": "Unsafe enum output.",
                                        "intent": "investigate",
                                        "emotional_shift": {},
                                        "proposed_actions": [],
                                        "memory_refs": [],
                                        "disclosure_claims": [],
                                    }
                                )
                            }
                        }
                    ]
                }
            ),
        ]
    )

    intent = OpenAILLMAgent(
        api_key="test-key",
        base_url="https://api.xiaomimimo.com/v1",
        client=client,
    ).generate(context)

    assert intent.intent == AgentIntentType.REFUSE
    assert client.request_urls == [
        "https://api.xiaomimimo.com/v1/chat/completions",
        "https://api.xiaomimimo.com/v1/chat/completions",
    ]
    assert client.request_payloads[1]["response_format"]["type"] == "json_object"


def test_real_llm_agent_repairs_schema_invalid_output_once(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("LLM_API_STYLE", "chat_completions")
    context = _build_butler_agent_context()
    client = _FakeOpenAIClient(
        [
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "speech": "I will be careful.",
                                    "intent": "answer",
                                    "emotional_shift": {},
                                    "proposed_actions": [],
                                    "memory_refs": [],
                                    "disclosure_claims": [
                                        {
                                            "world_info_id": "desk_forced_open",
                                            "mode": "hint",
                                            "tactic": None,
                                            "source_refs": [],
                                            "claim_refs": [],
                                            "extra_field": "not allowed",
                                        }
                                    ],
                                }
                            )
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "speech": "I will be careful.",
                                    "intent": "answer",
                                    "emotional_shift": {},
                                    "proposed_actions": [],
                                    "memory_refs": [],
                                    "disclosure_claims": [],
                                }
                            )
                        }
                    }
                ]
            },
        ]
    )

    intent = OpenAILLMAgent(
        api_key="test-key",
        base_url="https://api.xiaomimimo.com/v1",
        model="test-model",
        client=client,
        schema_repair_attempts=1,
    ).generate_strict(context)

    assert intent.intent == AgentIntentType.ANSWER
    assert client.request_urls == [
        "https://api.xiaomimimo.com/v1/chat/completions",
        "https://api.xiaomimimo.com/v1/chat/completions",
    ]
    serialized_repair_request = json.dumps(
        client.request_payloads[1],
        ensure_ascii=False,
    )
    assert "schema repair" in serialized_repair_request.lower()
    assert "extra_forbidden" in serialized_repair_request
    assert "extra_field" not in intent.model_dump_json()


def test_real_llm_agent_repair_prompt_distinguishes_intent_from_disclosure_mode(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("LLM_API_STYLE", "chat_completions")
    context = _build_butler_agent_context()
    client = _FakeOpenAIClient(
        [
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "speech": "I am redirecting the question.",
                                    "intent": "deflect",
                                    "emotional_shift": {},
                                    "proposed_actions": [],
                                    "memory_refs": [],
                                    "disclosure_claims": [],
                                }
                            )
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "speech": "I am redirecting the question.",
                                    "intent": "conceal",
                                    "emotional_shift": {},
                                    "proposed_actions": [],
                                    "memory_refs": [],
                                    "disclosure_claims": [],
                                }
                            )
                        }
                    }
                ]
            },
        ]
    )

    intent = OpenAILLMAgent(
        api_key="test-key",
        base_url="https://api.xiaomimimo.com/v1",
        model="test-model",
        client=client,
        schema_repair_attempts=1,
    ).generate_strict(context)

    serialized_repair_request = json.dumps(
        client.request_payloads[1],
        ensure_ascii=False,
    )
    assert intent.intent == AgentIntentType.CONCEAL
    assert "Allowed top-level intent values" in serialized_repair_request
    assert "deflect is a disclosure_claims[].mode value" in serialized_repair_request
    assert "never the top-level intent" in serialized_repair_request


def test_real_llm_agent_repair_prompt_uses_contract_projection_without_extra_keys(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("LLM_API_STYLE", "chat_completions")
    context = _build_butler_agent_context()
    client = _FakeOpenAIClient(
        [
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "speech": "I can only hint at that.",
                                    "intent": "answer",
                                    "emotional_shift": {},
                                    "proposed_actions": [],
                                    "memory_refs": [],
                                    "disclosure_claims": [
                                        {
                                            "world_info_id": "desk_forced_open",
                                            "mode": "hint",
                                            "tactic": None,
                                            "source_refs": [],
                                            "claim_refs": [],
                                            "confidence": 0.7,
                                            "source_event_id": "event.secret",
                                        }
                                    ],
                                }
                            )
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "speech": "I can only hint at that.",
                                    "intent": "answer",
                                    "emotional_shift": {},
                                    "proposed_actions": [],
                                    "memory_refs": [],
                                    "disclosure_claims": [
                                        {
                                            "world_info_id": "desk_forced_open",
                                            "mode": "hint",
                                            "tactic": None,
                                            "source_refs": [],
                                            "claim_refs": [],
                                        }
                                    ],
                                }
                            )
                        }
                    }
                ]
            },
        ]
    )

    intent = OpenAILLMAgent(
        api_key="test-key",
        base_url="https://api.xiaomimimo.com/v1",
        model="test-model",
        client=client,
        schema_repair_attempts=1,
    ).generate_strict(context)

    repair_instruction = client.request_payloads[1]["messages"][-1]["content"]
    assert intent.intent == AgentIntentType.ANSWER
    assert "extra_forbidden" in repair_instruction
    assert "source_event_id" not in repair_instruction
    assert "confidence" not in repair_instruction
    assert "event.secret" not in repair_instruction


def test_real_llm_agent_repair_prompt_lists_allowed_disclosure_modes_by_world_info(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("LLM_API_STYLE", "chat_completions")
    context = _build_butler_agent_context()
    client = _FakeOpenAIClient(
        [
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "speech": "I should not reveal this fully.",
                                    "intent": "answer",
                                    "emotional_shift": {},
                                    "proposed_actions": [],
                                    "memory_refs": [],
                                    "disclosure_claims": [
                                        {
                                            "world_info_id": "desk_forced_open",
                                            "mode": "full",
                                            "tactic": None,
                                            "source_refs": [],
                                            "claim_refs": [],
                                        }
                                    ],
                                }
                            )
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "speech": "I should not reveal this fully.",
                                    "intent": "conceal",
                                    "emotional_shift": {},
                                    "proposed_actions": [],
                                    "memory_refs": [],
                                    "disclosure_claims": [],
                                }
                            )
                        }
                    }
                ]
            },
        ]
    )

    intent = OpenAILLMAgent(
        api_key="test-key",
        base_url="https://api.xiaomimimo.com/v1",
        model="test-model",
        client=client,
        schema_repair_attempts=1,
    ).generate_strict(context)

    repair_instruction = client.request_payloads[1]["messages"][-1]["content"]
    assert intent.intent == AgentIntentType.CONCEAL
    assert "Allowed disclosure modes by world_info_id" in repair_instruction
    assert "desk_forced_open" in repair_instruction
    assert "full" not in _disclosure_modes_line(repair_instruction, "desk_forced_open")
    assert "delete that disclosure_claim" in repair_instruction


def test_real_llm_agent_repairs_unparseable_json_output_once(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("LLM_API_STYLE", "chat_completions")
    context = _build_butler_agent_context()
    invalid_text = (
        '{"speech":"I can answer safely.","intent":"answer","emotional_shift":{},'
        '"proposed_actions":[],"memory_refs":[],"disclosure_claims":[]} '
        "Here is why this matters."
    )
    client = _FakeOpenAIClient(
        [
            {
                "choices": [
                    {
                        "message": {
                            "content": invalid_text,
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "speech": "I can answer safely.",
                                    "intent": "answer",
                                    "emotional_shift": {},
                                    "proposed_actions": [],
                                    "memory_refs": [],
                                    "disclosure_claims": [],
                                }
                            )
                        }
                    }
                ]
            },
        ]
    )

    intent = OpenAILLMAgent(
        api_key="test-key",
        base_url="https://api.xiaomimimo.com/v1",
        model="test-model",
        client=client,
        schema_repair_attempts=1,
    ).generate_strict(context)

    repair_instruction = client.request_payloads[1]["messages"][-1]["content"]
    assert intent.intent == AgentIntentType.ANSWER
    assert intent.speech == "I can answer safely."
    assert "JSON repair required" in repair_instruction
    assert "not a single JSON object" in repair_instruction
    assert "Here is why this matters." in repair_instruction


def _disclosure_modes_line(text: str, world_info_id: str) -> str:
    return next(line for line in text.splitlines() if world_info_id in line)


def test_real_llm_agent_can_force_responses_api_style_without_chat_fallback(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("LLM_API_STYLE", "responses")
    context = _build_butler_agent_context()
    client = _FakeOpenAIClient(
        [
            _FakeOpenAIResponse({"error": "not found"}, status_code=404),
            _FakeOpenAIResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "speech": "Should not be used.",
                                        "intent": "answer",
                                        "emotional_shift": {},
                                        "proposed_actions": [],
                                        "memory_refs": [],
                                        "disclosure_claims": [],
                                    }
                                )
                            }
                        }
                    ]
                }
            ),
        ]
    )

    intent = OpenAILLMAgent(
        api_key="test-key",
        base_url="https://api.xiaomimimo.com/v1",
        client=client,
    ).generate(context)

    assert intent.intent == AgentIntentType.REFUSE
    assert client.request_urls == ["https://api.xiaomimimo.com/v1/responses"]


def test_real_llm_agent_falls_back_without_api_key() -> None:
    context = _build_butler_agent_context()
    client = _FakeOpenAIClient({})

    intent = OpenAILLMAgent(api_key="", client=client).generate(context)

    assert intent.intent == AgentIntentType.REFUSE
    assert intent.proposed_actions == []
    assert client.request_payload is None


def test_real_llm_agent_falls_back_when_output_violates_contract() -> None:
    context = _build_butler_agent_context()
    client = _FakeOpenAIClient(
        {
            "output_text": json.dumps(
                {
                    "speech": "I will move the narrative myself.",
                    "intent": "answer",
                    "emotional_shift": {},
                    "proposed_actions": [
                        {
                            "type": "narrative.phase.change",
                            "phase": "resolved",
                        }
                    ],
                    "memory_refs": [],
                    "disclosure_claims": [],
                }
            )
        }
    )

    intent = OpenAILLMAgent(api_key="test-key", client=client).generate(context)

    assert intent.intent == AgentIntentType.REFUSE
    assert intent.proposed_actions == []


def test_real_llm_agent_falls_back_when_output_quotes_private_text() -> None:
    context = _build_butler_agent_context()
    assert context.inner_context is not None
    raw_secret = context.inner_context.inner_secrets[0].summary
    client = _FakeOpenAIClient(
        {
            "output_text": json.dumps(
                {
                    "speech": raw_secret,
                    "intent": "answer",
                    "emotional_shift": {},
                    "proposed_actions": [],
                    "memory_refs": [],
                    "disclosure_claims": [],
                },
                ensure_ascii=False,
            )
        }
    )

    intent = OpenAILLMAgent(api_key="test-key", client=client).generate(context)

    assert intent.intent == AgentIntentType.REFUSE
    assert raw_secret not in intent.speech


def test_llm_contract_rejects_raw_inner_portrait_echo() -> None:
    context = _build_fallback_context(
        defensive_style="neutral",
        pressure_response="answer",
        inner_context=CharacterInnerContext(
            character_id="npc",
            inner_portraits=[
                CharacterImpression(
                    observer_id="npc",
                    target_id="player",
                    personality_impression="The player pushes hard on weak points.",
                    perceived_motive="Testing whether the NPC will slip.",
                    trust_boundary="Do not answer without evidence.",
                    last_updated_event_id="event_001",
                )
            ],
        ),
    )
    contract_input = build_llm_agent_input(context)

    with pytest.raises(ValueError, match="must not quote raw private data"):
        validate_llm_agent_output(
            {
                "speech": "The player pushes hard on weak points.",
                "intent": "answer",
                "emotional_shift": {},
                "proposed_actions": [],
                "memory_refs": [],
                "disclosure_claims": [],
            },
            contract_input,
        )


def test_llm_contract_rejects_disclosure_claim_beyond_constraint() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    context = build_agent_context(
        case,
        session,
        PlayerAction(type="talk", target_id="butler", text="What do you know?"),
    )
    contract_input = build_llm_agent_input(context)

    with pytest.raises(ValueError, match="disclosure mode is not allowed"):
        validate_llm_agent_output(
            {
                "speech": "I should not reveal this fully.",
                "intent": "answer",
                "emotional_shift": {},
                "proposed_actions": [],
                "memory_refs": [],
                "disclosure_claims": [
                    {
                        "world_info_id": "will_swapped",
                        "mode": "partial",
                        "tactic": "answer_adjacent_truth",
                        "source_refs": [],
                        "claim_refs": [],
                    }
                ],
            },
            contract_input,
        )


def test_llm_agent_contract_input_includes_controlled_inner_context() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    context = build_agent_context(
        case,
        session,
        PlayerAction(type="talk", target_id="butler", text="What do you know?"),
    )

    contract_input = build_llm_agent_input(context)

    assert contract_input.required_output_schema == "AgentIntent"
    assert contract_input.agent_context.player_action.target_id == "butler"
    assert contract_input.agent_context.memory_snapshots == []
    assert contract_input.agent_context.relationship_to_player is not None
    assert contract_input.agent_context.inner_context is not None
    assert contract_input.agent_context.inner_context.character_id == "butler"
    assert {constraint.item_id for constraint in contract_input.disclosure_constraints} >= {
        "avoid_suspicion",
        "swapped_will_awareness",
        "drawer_opened_last_night",
        "true_killer",
        "swapped_will",
    }
    secret_constraint = next(
        item
        for item in contract_input.disclosure_constraints
        if item.item_id == "swapped_will_awareness"
    )
    assert secret_constraint.item_kind == "secret"
    assert secret_constraint.direct_reveal_allowed is False
    assert secret_constraint.direct_quote_allowed is False
    assert "scratched_drawer" in secret_constraint.related_clue_ids
    assert "will_swapped" in secret_constraint.related_world_info_ids
    assert "desk_forced_open" in secret_constraint.related_world_info_ids
    world_info_constraint = next(
        item
        for item in contract_input.disclosure_constraints
        if item.item_kind == "world_info" and item.item_id == "desk_forced_open"
    )
    assert DisclosureMode.FULL in world_info_constraint.forbidden_modes
    assert "full_reveal:desk_forced_open" in world_info_constraint.must_not_claim
    assert RhetoricTactic.SHIFT_FOCUS in world_info_constraint.rhetoric_tactics
    assert world_info_constraint.direct_reveal_allowed is False


def test_llm_agent_contract_input_excludes_other_npc_private() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    context = build_agent_context(
        case,
        session,
        PlayerAction(type="talk", target_id="butler", text="What do you know?"),
    )

    serialized_input = build_llm_agent_input(context).model_dump_json()
    niece = next(character for character in case.characters if character.id == "niece")

    assert context.inner_context is not None
    assert context.inner_context.character_id == "butler"
    for private_value in _private_values_for_character(niece):
        assert private_value not in serialized_input
    assert "secret_meeting_note_exists" not in serialized_input


def test_llm_agent_contract_input_includes_only_target_inner_portraits() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="ask_about",
            target_id="butler",
            subject_type="character",
            subject_id="niece",
            text="What do you think of her?",
        ),
    )
    butler_context = build_agent_context(
        case,
        session,
        PlayerAction(type="talk", target_id="butler", text="What now?"),
    )
    niece_context = build_agent_context(
        case,
        session,
        PlayerAction(type="talk", target_id="niece", text="What now?"),
    )

    butler_input = build_llm_agent_input(butler_context)
    niece_input = build_llm_agent_input(niece_context)

    assert butler_input.agent_context.inner_context is not None
    assert len(butler_input.agent_context.inner_context.inner_portraits) == 1
    impression = butler_input.agent_context.inner_context.inner_portraits[0]
    assert impression.observer_id == "butler"
    assert impression.target_id == "player"
    assert niece_input.agent_context.inner_context is not None
    assert niece_input.agent_context.inner_context.inner_portraits == []
    serialized_niece_input = niece_input.model_dump_json()
    assert impression.personality_impression not in serialized_niece_input
    assert impression.perceived_motive not in serialized_niece_input
    assert impression.trust_boundary not in serialized_niece_input


def test_llm_agent_contract_uses_impression_adjusted_disclosure_modes() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type="inspect", target_id="desk"),
    )
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="present_clue",
            target_id="butler",
            clue_id="scratched_drawer",
            text="What about these scratch marks?",
        ),
    )
    context = build_agent_context(
        case,
        session,
        PlayerAction(
            type="talk",
            target_id="butler",
            text="Answer this carefully.",
        ),
    )

    contract_input = build_llm_agent_input(context)
    constraint = next(
        item
        for item in contract_input.disclosure_constraints
        if item.item_id == "swapped_will_awareness"
    )

    assert DisclosureMode.PARTIAL in constraint.allowed_modes
    assert DisclosureMode.FULL not in constraint.allowed_modes
    assert constraint.direct_reveal_allowed is False
    assert constraint.blocked is False


def test_llm_agent_contract_rejects_phase_change_output() -> None:
    with pytest.raises(ValueError, match="must not propose narrative phase changes"):
        validate_llm_agent_output(
            {
                "speech": "I will move the story myself.",
                "intent": "answer",
                "proposed_actions": [
                    {
                        "type": "narrative.phase.change",
                        "phase": "reveal",
                    }
                ],
            }
        )


def test_llm_agent_stub_does_not_reveal_inner_context_private_text() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    context = build_agent_context(
        case,
        session,
        PlayerAction(type="talk", target_id="butler", text="Tell me the truth."),
    )

    intent = LLMAgentStub().generate(context)

    for private_value in _private_character_values(case):
        assert private_value not in intent.speech


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
    director_event = next(
        event for event in payload["new_events"] if event["type"] == "director.blocked"
    )
    assert director_event["payload"]["world_info_id"] == "killer_is_niece"
    assert director_event["payload"]["detected_directness"] == "direct_claim"
    assert director_event["payload"]["matched_by"] == "forbidden_term"
    assert director_event["payload"]["matched_text"] == "[redacted]"
    assert director_event["payload"]["safe_fallback_used"] is True


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
    case = CaseLoader().load(FAKE_CASE_001_DIR)

    response = client.get(f"/sessions/{session_id}/state")

    assert response.status_code == 200
    serialized = response.text
    assert '"secrets":' not in serialized
    assert '"goals":' not in serialized
    assert '"knowledge":' not in serialized
    assert '"private":' not in serialized
    assert '"truth_status":' not in serialized
    assert '"forbidden_facts":' not in serialized
    assert '"solution_claims":' not in serialized
    assert "butler_moved_key" not in serialized
    assert "correct" not in serialized
    assert response.json()["player_knowledge"] == []
    for private_value in _private_character_values(case):
        assert private_value not in serialized


def test_player_action_rejects_generic_target_field(client: TestClient) -> None:
    session_id = create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target": "desk"},
    )

    assert response.status_code == 422


def test_player_action_rejects_clue_id_for_non_present_clue(client: TestClient) -> None:
    session_id = create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "talk", "target_id": "butler", "clue_id": "scratched_drawer"},
    )

    assert response.status_code == 422


def test_player_action_rejects_missing_ask_about_subject(client: TestClient) -> None:
    session_id = create_session(client)

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "ask_about", "target_id": "butler"},
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
        "agent_memory_snapshot.updated",
        "narrative.beat.completed",
        "narrative.phase.changed",
        "player.talked",
        "npc_skill.rejected",
        "npc.replied",
        "relationship.changed",
        "relationship.threshold.crossed",
        "character_impression.updated",
        "memory_candidate.created",
        "agent_memory_snapshot.updated",
        "player.talked",
        "npc_skill.rejected",
        "director.blocked",
        "character_impression.updated",
        "memory_candidate.created",
        "agent_memory_snapshot.updated",
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


def test_character_impressions_are_private_and_replayable() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="ask_about",
            target_id="butler",
            subject_type="character",
            subject_id="niece",
            text="What do you think of her?",
        ),
    )
    impression = session.character_impressions["butler"]["player"]

    summary_json = build_state_summary(case, session).model_dump_json()
    journey = render_player_journey(session.events)
    replayed = replay_events(case, session.events)

    assert replayed.character_impressions == session.character_impressions
    assert len(replayed.events) == len(session.events)
    assert "character_impressions" not in summary_json
    assert "inner_portraits" not in summary_json
    assert impression.personality_impression not in journey
    assert impression.perceived_motive not in journey
    assert impression.trust_boundary not in journey
    assert "Private character impression updated." in journey


def test_character_impression_events_do_not_contain_case_secrets() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type="ask_about",
            target_id="butler",
            subject_type="character",
            subject_id="niece",
            text="What do you think of her?",
        ),
    )

    impression_payloads = [
        event.payload
        for event in response.new_events
        if event.type == EventType.CHARACTER_IMPRESSION_UPDATED
    ]
    serialized = json.dumps(impression_payloads, ensure_ascii=False)

    assert impression_payloads
    assert "solution_claims" not in serialized
    for private_value in _private_character_values(case):
        assert private_value not in serialized
    for fact in case.forbidden_facts:
        assert fact.text not in serialized
        for blocked_term in fact.blocked_terms:
            assert blocked_term not in serialized


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
            "player_knowledge": ["player_knowledge.desk_forced_open"],
            "event_count": 8,
        },
        "fake_case_002_after_first_talk": {
            "case_id": "fake_case_002",
            "phase": "opening",
            "completed_beats": [],
            "discovered": [],
            "player_knowledge": [],
            "event_count": 8,
        },
    }
    serialized = json.dumps([opening, investigation, second_case_talk], ensure_ascii=False)
    assert '"secrets":' not in serialized
    assert '"goals":' not in serialized
    assert '"knowledge":' not in serialized
    assert '"private":' not in serialized
    assert '"character_impressions":' not in serialized
    assert '"inner_portraits":' not in serialized
    assert '"truth_status":' not in serialized
    assert '"forbidden_facts":' not in serialized
    assert '"solution_claims":' not in serialized
    for case_dir in (FAKE_CASE_001_DIR, FAKE_CASE_002_DIR):
        for private_value in _private_character_values(CaseLoader().load(case_dir)):
            assert private_value not in serialized


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


def test_case_validate_command_accepts_all_cases() -> None:
    assert validate_cases(PROJECT_ROOT / "cases") == [
        "fake_case_001",
        "fake_case_002",
        "mist_clock_manor",
    ]


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


def test_case_loader_rejects_bad_solution_claim_reference(tmp_path: Path) -> None:
    case_dir = tmp_path / "bad_solution_claim_case"
    case_dir.mkdir()
    _write_minimal_case(case_dir)
    (case_dir / "solution_claims.yaml").write_text(
        "claims:\n"
        "  - id: bad_claim\n"
        "    target_id: ghost\n"
        "    required_evidence:\n"
        "      - missing_clue\n"
        "    allowed_phases:\n"
        "      - opening\n"
        "    result: correct\n",
        encoding="utf-8",
    )

    with pytest.raises(CaseLoadError, match="unknown target_id"):
        CaseLoader().load(case_dir)


def test_case_loader_rejects_bad_world_info_reference_from_clue(tmp_path: Path) -> None:
    case_dir = tmp_path / "bad_world_info_clue_case"
    case_dir.mkdir()
    _write_minimal_case(case_dir)
    (case_dir / "world_info.yaml").write_text("[]\n", encoding="utf-8")
    (case_dir / "scenes.yaml").write_text(
        "- id: room\n  name: Room\n  characters:\n"
        "    - npc\n  hotspots:\n"
        "    - id: desk\n      name: Desk\n      discover_clues:\n"
        "        - clue\n",
        encoding="utf-8",
    )
    (case_dir / "clues.yaml").write_text(
        "- id: clue\n"
        "  title: Clue\n"
        "  description: clue\n"
        "  reveals_world_info:\n"
        "    - missing_world_info\n",
        encoding="utf-8",
    )

    with pytest.raises(CaseLoadError, match="unknown world_info"):
        CaseLoader().load(case_dir)


def test_case_loader_rejects_invalid_world_info_claim_pattern(tmp_path: Path) -> None:
    case_dir = tmp_path / "bad_world_info_claim_pattern_case"
    case_dir.mkdir()
    _write_minimal_case(case_dir)
    (case_dir / "world_info.yaml").write_text(
        "- id: fact\n"
        "  title: Fact\n"
        "  claim_patterns:\n"
        "    - 'fact('\n",
        encoding="utf-8",
    )

    with pytest.raises(CaseLoadError, match="invalid claim_pattern"):
        CaseLoader().load(case_dir)


def test_case_loader_keeps_world_info_audit_fields_optional(tmp_path: Path) -> None:
    case_dir = tmp_path / "legacy_world_info_case"
    case_dir.mkdir()
    _write_minimal_case(case_dir)
    (case_dir / "world_info.yaml").write_text(
        "- id: fact\n"
        "  title: Fact\n",
        encoding="utf-8",
    )
    (case_dir / "scenes.yaml").write_text(
        "- id: room\n  name: Room\n  characters:\n"
        "    - npc\n  hotspots:\n"
        "    - id: desk\n      name: Desk\n      discover_clues:\n"
        "        - clue\n",
        encoding="utf-8",
    )
    (case_dir / "clues.yaml").write_text(
        "- id: clue\n"
        "  title: Clue\n"
        "  description: clue\n"
        "  reveals_world_info:\n"
        "    - fact\n",
        encoding="utf-8",
    )

    case = CaseLoader().load(case_dir)

    assert case.world_info[0].aliases == []
    assert case.world_info[0].claim_patterns == []


def test_case_loader_rejects_bad_world_info_reference_from_forbidden_fact(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "bad_world_info_forbidden_case"
    case_dir.mkdir()
    _write_minimal_case(case_dir)
    (case_dir / "forbidden_facts.yaml").write_text(
        "- id: forbidden\n"
        "  world_info_id: missing_world_info\n"
        "  text: hidden\n"
        "  blocked_terms:\n"
        "    - hidden\n"
        "  reveal_phase: opening\n",
        encoding="utf-8",
    )

    with pytest.raises(CaseLoadError, match="unknown world_info_id"):
        CaseLoader().load(case_dir)


def test_case_loader_rejects_bad_world_info_reference_from_solution_claim(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "bad_world_info_claim_case"
    case_dir.mkdir()
    _write_minimal_case(case_dir)
    (case_dir / "solution_claims.yaml").write_text(
        "claims:\n"
        "  - id: bad_claim\n"
        "    target_id: npc\n"
        "    required_world_info:\n"
        "      - missing_world_info\n"
        "    allowed_phases:\n"
        "      - opening\n"
        "    result: correct\n",
        encoding="utf-8",
    )

    with pytest.raises(CaseLoadError, match="unknown world_info"):
        CaseLoader().load(case_dir)


def test_case_loader_rejects_bad_world_info_reference_from_character_private(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "bad_private_world_info_case"
    case_dir.mkdir()
    _write_minimal_case(case_dir)
    (case_dir / "characters.yaml").write_text(
        "- id: npc\n"
        "  name: NPC\n"
        "  role: Witness\n"
        "  private:\n"
        "    goals:\n"
        "      - id: goal\n"
        "        summary: Goal.\n"
        "        related_world_info_ids:\n"
        "          - missing_world_info\n",
        encoding="utf-8",
    )

    with pytest.raises(CaseLoadError, match="related_world_info_ids"):
        CaseLoader().load(case_dir)


def test_case_loader_rejects_bad_world_info_reference_from_disclosure_style(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "bad_disclosure_style_world_info_case"
    case_dir.mkdir()
    _write_minimal_case(case_dir)
    (case_dir / "characters.yaml").write_text(
        "- id: npc\n"
        "  name: NPC\n"
        "  role: Witness\n"
        "  private:\n"
        "    disclosure_style:\n"
        "      max_mode_by_world_info:\n"
        "        missing_world_info: hint\n",
        encoding="utf-8",
    )

    with pytest.raises(CaseLoadError, match="max_mode_by_world_info"):
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


class _FakeOpenAIResponse:
    def __init__(self, payload: dict[str, Any], *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.request_url = "https://example.test"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", self.request_url)
            response = httpx.Response(
                self.status_code,
                request=request,
                json=self._payload,
            )
            raise httpx.HTTPStatusError(
                f"HTTP status {self.status_code}",
                request=request,
                response=response,
            )
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeOpenAIClient:
    def __init__(
        self,
        payload: dict[str, Any] | list[dict[str, Any] | _FakeOpenAIResponse],
    ) -> None:
        raw_responses = payload if isinstance(payload, list) else [payload]
        self._responses = [
            item if isinstance(item, _FakeOpenAIResponse) else _FakeOpenAIResponse(item)
            for item in raw_responses
        ]
        self.request_payload: dict[str, Any] | None = None
        self.request_url: str | None = None
        self.request_payloads: list[dict[str, Any]] = []
        self.request_urls: list[str] = []

    def post(self, _url: str, **kwargs: Any) -> _FakeOpenAIResponse:
        self.request_url = _url
        self.request_urls.append(_url)
        request_payload = kwargs.get("json")
        if isinstance(request_payload, dict):
            self.request_payload = request_payload
            self.request_payloads.append(request_payload)
        response = self._responses.pop(0)
        response.request_url = _url
        return response


def _build_butler_agent_context() -> AgentContext:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    return build_agent_context(
        case,
        session,
        PlayerAction(type="talk", target_id="butler", text="Where were you?"),
    )


def _build_fallback_context(
    *,
    defensive_style: str,
    pressure_response: str,
    speech_style: str = "",
    default_tone: str = "",
    player_action: PlayerAction | None = None,
    inner_context: CharacterInnerContext | None = None,
) -> AgentContext:
    action = player_action or PlayerAction(type="talk", target_id="npc")
    return AgentContext(
        case_id="test_case",
        session_id="session",
        target_agent_id=action.target_id,
        current_phase="opening",
        player_action=action,
        target_profile=AgentCharacterView(
            id=action.target_id,
            display_name="NPC",
            public_role="Witness",
            public_description="Public witness profile.",
            speech_style=speech_style,
            default_tone=default_tone,
            defensive_style=defensive_style,
            pressure_response=pressure_response,
        ),
        inner_context=inner_context,
        asked_subject_type=action.subject_type,
        asked_subject_id=action.subject_id,
        presented_clue_id=action.clue_id,
        default_speech="Default fallback.",
        default_intent=AgentIntentType.ANSWER,
        reply_options=[],
    )


def _build_test_inner_context(
    *,
    secret_summary: str,
    related_clue_ids: list[str],
) -> CharacterInnerContext:
    return CharacterInnerContext(
        character_id="npc",
        inner_secrets=[
            SelfKnowledgeItem(
                id="secret_001",
                kind="secret",
                summary=secret_summary,
                priority="high",
                related_clue_ids=related_clue_ids,
                disclosure_policy=DisclosurePolicy(direct_reveal_allowed=False),
            )
        ],
    )


def _private_character_values(
    case: object,
    *,
    exclude_character_id: str | None = None,
) -> list[str]:
    values: list[str] = []
    for character in case.characters:
        if character.id == exclude_character_id:
            continue
        values.extend(_private_values_for_character(character))
    return values


def _private_values_for_character(character: object) -> list[str]:
    values: list[str] = []
    values.extend(goal.summary for goal in character.private.goals)
    values.extend(secret.summary for secret in character.private.secrets)
    values.extend(knowledge.summary for knowledge in character.private.knowledge)
    return values


def _write_minimal_case(case_dir: Path) -> None:
    (case_dir / "case.yaml").write_text(
        "id: test_case\ntitle: Test Case\ndescription: ''\ninitial_phase: opening\n",
        encoding="utf-8",
    )
    (case_dir / "characters.yaml").write_text(
        "- id: npc\n  name: NPC\n  role: Witness\n",
        encoding="utf-8",
    )
    (case_dir / "world_info.yaml").write_text("[]\n", encoding="utf-8")
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


def _run_fake_case_001_to_reveal(runtime: object, session: object) -> None:
    for target_id in ("desk", "portrait", "carpet"):
        runtime.action_service.handle(
            session=session,
            action=PlayerAction(type="inspect", target_id=target_id),
        )
