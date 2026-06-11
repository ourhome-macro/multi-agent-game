from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.context import build_agent_context
from app.agents.memory import MemoryRetriever
from app.cases.loader import CaseLoader
from app.domain.models import (
    ActionType,
    CasePackage,
    EventType,
    PlayerAction,
    PresentationMode,
    SessionState,
)
from app.main import app
from app.runtime.service import RuntimeContainer, create_runtime
from scripts.run_terminal_mvp import parse_player_command

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"

JIANG = "jiang_yanhui"
QI = "qi_yan"
LIN = "lin_qichi"
SHEN = "shen_zhaoye"
STUDY = "study"
EMPTY_CAPSULES = "empty_capsules"

PRIVATE_PRESENTED_MEMORY = f"memory.player.presented_clue.{JIANG}.{EMPTY_CAPSULES}"
SCENE_SHARED_MEMORY = f"memory.player.scene_shared.presented_clue.{STUDY}.{EMPTY_CAPSULES}"


def test_action_service_private_present_clue_stays_target_private() -> None:
    case, runtime, session = _runtime()
    _discover_empty_capsules(runtime, session)

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.PRESENT_CLUE,
            target_id=JIANG,
            clue_id=EMPTY_CAPSULES,
            presentation_mode=PresentationMode.PRIVATE,
            text="private display",
        ),
    )

    assert response.accepted is True
    presented = _presented_event(response.new_events)
    assert presented.payload["presentation_mode"] == "private"
    assert "scene_id" not in presented.payload
    assert "present_character_ids" not in presented.payload
    assert PRIVATE_PRESENTED_MEMORY in session.memory_snapshots
    assert SCENE_SHARED_MEMORY not in session.memory_snapshots

    jiang_context = build_agent_context(case, session, _talk(JIANG))
    qi_context = build_agent_context(case, session, _talk(QI))
    assert PRIVATE_PRESENTED_MEMORY in _context_memory_ids(jiang_context)
    assert PRIVATE_PRESENTED_MEMORY not in _context_memory_ids(qi_context)

    qi_memories = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=_talk(QI, text=EMPTY_CAPSULES),
    )
    assert PRIVATE_PRESENTED_MEMORY not in _memory_ids(qi_memories)


def test_action_service_scene_shared_present_clue_reaches_present_scene_npcs() -> None:
    case, runtime, session = _runtime()
    _discover_empty_capsules(runtime, session)

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.PRESENT_CLUE,
            target_id=JIANG,
            clue_id=EMPTY_CAPSULES,
            presentation_mode=PresentationMode.SCENE_SHARED,
            scene_id=STUDY,
            text="public display",
        ),
    )

    assert response.accepted is True
    presented = _presented_event(response.new_events)
    assert presented.payload["presentation_mode"] == "scene_shared"
    assert presented.payload["scene_id"] == STUDY
    assert set(presented.payload["present_character_ids"]) == {LIN, QI, JIANG}

    shared = session.memory_snapshots[SCENE_SHARED_MEMORY]
    assert shared.memory_scope == "scene_shared"
    assert shared.memory_layer == "working"
    assert set(shared.visible_to_character_ids) == {LIN, QI, JIANG}

    for npc_id in (JIANG, QI, LIN):
        context = build_agent_context(case, session, _talk(npc_id, text=EMPTY_CAPSULES))
        assert SCENE_SHARED_MEMORY in _context_memory_ids(context)

    shen_context = build_agent_context(case, session, _talk(SHEN, text=EMPTY_CAPSULES))
    assert SCENE_SHARED_MEMORY not in _context_memory_ids(shen_context)

    qi_memories = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=_talk(QI, text=EMPTY_CAPSULES),
    )
    shen_memories = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=_talk(SHEN, text=EMPTY_CAPSULES),
    )
    assert SCENE_SHARED_MEMORY in _memory_ids(qi_memories)
    assert SCENE_SHARED_MEMORY not in _memory_ids(shen_memories)


def test_api_present_clue_contract_accepts_scene_shared_mode() -> None:
    client = TestClient(app)
    session_id = _create_mist_session(client)
    client.post(
        f"/sessions/{session_id}/actions",
        json={"type": "inspect", "target_id": "medicine_box"},
    )

    response = client.post(
        f"/sessions/{session_id}/actions",
        json={
            "type": "present_clue",
            "target_id": JIANG,
            "clue_id": EMPTY_CAPSULES,
            "presentation_mode": "scene_shared",
            "scene_id": STUDY,
            "text": "public display",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    presented = payload["new_events"][0]["payload"]
    assert presented["presentation_mode"] == "scene_shared"
    assert presented["scene_id"] == STUDY
    assert set(presented["present_character_ids"]) == {LIN, QI, JIANG}


def test_api_present_clue_contract_rejects_ambiguous_mode_payloads() -> None:
    client = TestClient(app)
    session_id = _create_mist_session(client)

    missing_scene = client.post(
        f"/sessions/{session_id}/actions",
        json={
            "type": "present_clue",
            "target_id": JIANG,
            "clue_id": EMPTY_CAPSULES,
            "presentation_mode": "scene_shared",
        },
    )
    private_with_scene = client.post(
        f"/sessions/{session_id}/actions",
        json={
            "type": "present_clue",
            "target_id": JIANG,
            "clue_id": EMPTY_CAPSULES,
            "presentation_mode": "private",
            "scene_id": STUDY,
        },
    )
    mode_on_talk = client.post(
        f"/sessions/{session_id}/actions",
        json={
            "type": "talk",
            "target_id": JIANG,
            "presentation_mode": "private",
            "text": "bad payload",
        },
    )

    assert missing_scene.status_code == 422
    assert private_with_scene.status_code == 422
    assert mode_on_talk.status_code == 422


def test_terminal_repl_parses_structured_present_clue_modes() -> None:
    private = parse_player_command(
        "present jiang_yanhui empty_capsules private show quietly"
    )
    public = parse_player_command(
        "present jiang_yanhui empty_capsules public study show to everyone"
    )
    missing_scene = parse_player_command("present jiang_yanhui empty_capsules public")

    assert private.action is not None
    assert private.action.presentation_mode == PresentationMode.PRIVATE
    assert private.action.scene_id is None
    assert private.action.text == "show quietly"

    assert public.action is not None
    assert public.action.presentation_mode == PresentationMode.SCENE_SHARED
    assert public.action.scene_id == STUDY
    assert public.action.text == "show to everyone"

    assert missing_scene.action is None
    assert missing_scene.error == "usage: present <npc> <clue> public <scene> [text]"


def _runtime() -> tuple[CasePackage, RuntimeContainer, SessionState]:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    return case, runtime, runtime.session_store.create(case)


def _discover_empty_capsules(runtime: RuntimeContainer, session: SessionState) -> None:
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="medicine_box"),
    )


def _talk(target_id: str, *, text: str = "What do you know?") -> PlayerAction:
    return PlayerAction(type=ActionType.TALK, target_id=target_id, text=text)


def _presented_event(events: list[object]) -> object:
    return next(event for event in events if event.type == EventType.PLAYER_PRESENTED_CLUE)


def _context_memory_ids(context: object) -> set[str]:
    return {memory.memory_id for memory in context.memory_snapshots}


def _memory_ids(memories: list[object]) -> set[str]:
    return {str(memory.memory_id) for memory in memories}


def _create_mist_session(client: TestClient) -> str:
    response = client.post("/sessions", json={"case_id": "mist_clock_manor"})
    assert response.status_code == 200
    return str(response.json()["session_id"])
