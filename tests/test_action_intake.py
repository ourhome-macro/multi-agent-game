from __future__ import annotations

from pathlib import Path

from app.cases.loader import CaseLoader
from app.domain.models import ActionType, EventType, PlayerAction
from app.runtime.action_router import (
    ASK_MARKERS,
    COMMON_CLUE_ALIASES,
    GENERIC_CHARACTER_TERMS,
    GENERIC_SUBJECT_TERMS,
    INSPECT_MARKERS,
    TALK_MARKERS,
    UNKNOWN_CHARACTER_TERMS,
)
from app.runtime.service import ActionIntakeStatus, create_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"


def _runtime_session():
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    return runtime, case, session


def test_raw_text_intake_returns_clarification_for_ambiguous_target_and_subject() -> None:
    runtime, _, session = _runtime_session()
    raw_text = (
        f"{ASK_MARKERS[1]} {GENERIC_CHARACTER_TERMS[0]} "
        f"{GENERIC_SUBJECT_TERMS[0]}"
    )

    intake = runtime.action_service.handle_raw_text(session=session, raw_text=raw_text)

    assert intake.status == ActionIntakeStatus.NEEDS_CLARIFICATION
    assert intake.needs_clarification is True
    assert set(intake.missing_slots) == {"target", "subject"}
    assert intake.action is None
    assert intake.response is None
    assert [event.type for event in session.events] == [EventType.SESSION_CREATED]


def test_raw_text_intake_rejects_unknown_target_without_player_action() -> None:
    runtime, _, session = _runtime_session()
    raw_text = f"{TALK_MARKERS[0]} {UNKNOWN_CHARACTER_TERMS[0]}"

    intake = runtime.action_service.handle_raw_text(session=session, raw_text=raw_text)

    assert intake.status == ActionIntakeStatus.REJECTED
    assert intake.rejected is True
    assert intake.action is None
    assert intake.reason == "unknown_target"
    assert [event.type for event in session.events] == [EventType.SESSION_CREATED]


def test_raw_text_intake_rule_precheck_rejects_undiscovered_clue_subject() -> None:
    runtime, _, session = _runtime_session()
    raw_text = (
        f"{ASK_MARKERS[1]} jiang_yanhui "
        f"{COMMON_CLUE_ALIASES['empty_capsules'][0]}"
    )

    intake = runtime.action_service.handle_raw_text(session=session, raw_text=raw_text)

    assert intake.status == ActionIntakeStatus.REJECTED
    assert intake.action is not None
    assert intake.action.type == ActionType.ASK_ABOUT
    assert intake.response is not None
    assert intake.response.accepted is False
    assert [event.type for event in intake.response.new_events] == [EventType.RULE_REJECTED]
    rejection = intake.response.new_events[0]
    assert rejection.payload["action_type"] == "player.ask_about"
    assert rejection.payload["reason"] == "subject clue has not been discovered"
    assert session.events[-1].id == rejection.id


def test_raw_text_intake_accepts_legal_action_only_after_structured_player_action() -> None:
    runtime, _, session = _runtime_session()
    raw_text = f"{INSPECT_MARKERS[1]} medicine_box"

    intake = runtime.action_service.handle_raw_text(session=session, raw_text=raw_text)

    assert intake.status == ActionIntakeStatus.ACCEPTED
    assert intake.action is not None
    assert intake.action == PlayerAction(type=ActionType.INSPECT, target_id="medicine_box")
    assert intake.response is not None
    assert intake.response.accepted is True
    assert intake.response.new_events[0].type == EventType.PLAYER_INSPECTED
    assert intake.response.new_events[0].payload == {"target_id": "medicine_box"}
    assert intake.response.new_events[0].payload.get("text") is None


def test_rule_engine_precheck_rejects_illegal_structured_target() -> None:
    runtime, case, session = _runtime_session()
    action = PlayerAction(type=ActionType.TALK, target_id="not_a_character", text="hello")

    rejection = runtime.rule_engine.precheck_player_action(
        case=case,
        session=session,
        action=action,
    )

    assert rejection is not None
    assert rejection.type == EventType.RULE_REJECTED
    assert rejection.payload["action_type"] == "player.talk"
    assert rejection.payload["reason"] == "target_id is not a known character"
    assert session.events[-1].id == rejection.id
