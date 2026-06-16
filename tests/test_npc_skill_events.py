from __future__ import annotations

import json
from pathlib import Path

from app.cases.loader import CaseLoader
from app.domain.models import ActionType, EventType, PlayerAction, SubjectType
from app.runtime.replay import replay_events
from app.runtime.service import create_runtime
from app.runtime.tracing import RuntimeTracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "fake_case_001"
SKILL_ID = "butler_drawer_pressure_deflection"
SAFE_FRAGMENT_REF = "desk_forced_open.safe_fragment:drawer_was_forced"


def test_agent_backed_turn_records_selected_skill_event() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )

    response = runtime.action_service.handle(
        session=session,
        action=_ask_about_drawer(),
    )

    selected_event = _only_event(response.new_events, EventType.NPC_SKILL_SELECTED)

    assert selected_event.caused_by_event_id is not None
    assert selected_event.payload["target_id"] == "butler"
    assert selected_event.payload["action_type"] == "ask_about"
    assert selected_event.payload["selected_skill_ids"] == [SKILL_ID]
    assert selected_event.payload["selected_skills"] == [
        {
            "skill_id": SKILL_ID,
            "type": "dialogue",
            "level": 1,
            "signature": True,
            "safe_fragment_refs": [SAFE_FRAGMENT_REF],
            "allowed_intents": ["answer", "conceal", "probe"],
            "allowed_tactics": [
                "answer_adjacent_truth",
                "shift_focus",
                "qualify_certainty",
            ],
            "allowed_proposed_actions": ["relationship.change"],
        }
    ]


def test_agent_backed_turn_records_rejected_skill_event() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id="butler",
            text="Where were you?",
        ),
    )

    rejected_event = _only_event(response.new_events, EventType.NPC_SKILL_REJECTED)

    assert rejected_event.caused_by_event_id is not None
    assert rejected_event.payload["target_id"] == "butler"
    assert rejected_event.payload["action_type"] == "talk"
    assert {
        str(item["skill_id"]): str(item["reason"])
        for item in rejected_event.payload["rejected_skills"]
    } == {SKILL_ID: "trigger_mismatch"}


def test_npc_skill_event_payload_excludes_sensitive_text() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )
    player_text = "What about the drawer scratches?"

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.ASK_ABOUT,
            target_id="butler",
            subject_type=SubjectType.CLUE,
            subject_id="scratched_drawer",
            text=player_text,
        ),
    )

    skill_events = [
        event
        for event in response.new_events
        if event.type
        in {EventType.NPC_SKILL_SELECTED, EventType.NPC_SKILL_REJECTED}
    ]
    serialized = json.dumps(
        [event.payload for event in skill_events],
        ensure_ascii=False,
    )

    assert SKILL_ID in serialized
    assert SAFE_FRAGMENT_REF in serialized
    assert player_text not in serialized
    assert "summary" not in serialized
    assert "content" not in serialized
    assert "涔︽鎶藉眽瀛樺湪鏂伴矞鎾姩鐥曡抗" not in serialized
    for private_value in _private_character_values(case):
        assert private_value not in serialized


def test_director_block_preserves_selected_skill_event_for_audit() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )

    response = runtime.action_service.handle(
        session=session,
        action=_ask_about_drawer(force_forbidden=True),
    )

    assert response.director_blocked is True
    event_types = [event.type for event in response.new_events]
    assert EventType.NPC_SKILL_SELECTED in event_types
    assert event_types.index(EventType.NPC_SKILL_SELECTED) < event_types.index(
        EventType.DIRECTOR_BLOCKED
    )
    selected_event = _only_event(response.new_events, EventType.NPC_SKILL_SELECTED)
    assert selected_event.payload["selected_skill_ids"] == [SKILL_ID]


def test_replay_keeps_npc_skill_events_without_projection_side_effects() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )
    runtime.action_service.handle(session=session, action=_ask_about_drawer())

    replayed = replay_events(case, session.events)

    assert [event.type for event in replayed.events] == [
        event.type for event in session.events
    ]
    assert any(
        event.type == EventType.NPC_SKILL_SELECTED for event in replayed.events
    )
    assert replayed.discovered_clues == session.discovered_clues
    assert replayed.narrative.phase == session.narrative.phase


def _ask_about_drawer(*, force_forbidden: bool = False) -> PlayerAction:
    return PlayerAction(
        type=ActionType.ASK_ABOUT,
        target_id="butler",
        subject_type=SubjectType.CLUE,
        subject_id="scratched_drawer",
        text="What about the drawer scratches?",
        force_forbidden=force_forbidden,
    )


def _only_event(events: list[object], event_type: EventType) -> object:
    matched = [event for event in events if getattr(event, "type", None) == event_type]
    assert len(matched) == 1
    return matched[0]


def _private_character_values(case: object) -> list[str]:
    values: list[str] = []
    for character in case.characters:
        values.extend(goal.summary for goal in character.private.goals)
        values.extend(secret.summary for secret in character.private.secrets)
        values.extend(knowledge.summary for knowledge in character.private.knowledge)
    return [value for value in values if value]
