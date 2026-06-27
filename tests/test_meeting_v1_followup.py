from __future__ import annotations

from pathlib import Path

from app.api.projections import build_public_action_response
from app.cases.loader import CaseLoader
from app.domain.models import ActionType, EventType, PlayerAction
from app.runtime.replay import replay_events
from app.runtime.service import create_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_CASE_001_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


def test_meeting_partial_multi_evidence_verdict_reports_missing_evidence() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    for target_id in ("desk", "carpet", "portrait"):
        runtime.action_service.handle(
            session=session,
            action=PlayerAction(type=ActionType.INSPECT, target_id=target_id),
        )
    session.narrative.phase = "reveal"
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.MEETING_START, target_id="meeting"),
    )

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.MEETING_PROPOSE_VERDICT,
            target_id="butler",
            evidence_clue_ids=["scratched_drawer", "torn_note"],
            text="The meeting has selected only part of the evidence chain.",
        ),
    )

    assert response.accepted is False
    assert [event.type for event in response.new_events] == [
        EventType.MEETING_VERDICT_PROPOSED,
        EventType.MEETING_VERDICT_REJECTED,
        EventType.RULE_REJECTED,
    ]
    assert EventType.PLAYER_ACCUSED not in {event.type for event in session.events}

    rejected = response.new_events[1]
    assert rejected.payload["reason"] == "evidence does not cover required claim evidence"
    assert rejected.payload["missing_required_evidence"] == ["dustless_frame"]

    rule_rejected = response.new_events[2]
    assert rule_rejected.payload["proposed_payload"]["missing_required_evidence"] == [
        "dustless_frame"
    ]

    public_response = build_public_action_response(response)
    public_rejected = public_response.new_events[1]
    assert public_rejected.type == EventType.MEETING_VERDICT_REJECTED
    assert public_rejected.payload["missing_required_evidence"] == ["dustless_frame"]

    replayed = replay_events(case, session.events)
    assert replayed.meeting.verdict_status == "rejected"
    assert replayed.meeting.verdict_target_id == "butler"
    assert replayed.meeting.verdict_result is None
