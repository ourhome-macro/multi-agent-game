from __future__ import annotations

import json
from pathlib import Path

from app.api.projections import build_public_action_response, build_public_event_stream
from app.cases.loader import CaseLoader
from app.domain.models import ActionType, EventType, PlayerAction, WorldEvent
from app.runtime.service import create_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_CASE_001_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


def test_meeting_verdict_rejected_event_payload_exposes_safe_feedback_only() -> None:
    stream = build_public_event_stream(
        session_id="session.public.meeting",
        case_id="fake_case_001",
        events=[
            WorldEvent(
                id="event.meeting.verdict.rejected",
                case_id="fake_case_001",
                session_id="session.public.meeting",
                actor_id="rule_engine",
                type=EventType.MEETING_VERDICT_REJECTED,
                payload={
                    "meeting_id": "meeting.fake_case_001",
                    "target_id": "butler",
                    "claim_id": "butler_moved_key",
                    "reason": "player knowledge does not cover required world info",
                    "missing_required_evidence": ["torn_note"],
                    "missing_required_world_info": ["secret_meeting_note_exists"],
                    "solution_claim_conditions": {
                        "required_world_info": ["secret_meeting_note_exists"]
                    },
                    "private_memory_refs": ["memory.butler.private"],
                },
                created_at="2026-06-27T00:00:00+00:00",
            )
        ],
        after_count=0,
        limit=10,
    ).model_dump(mode="json")

    assert stream["events"][0]["payload"] == {
        "meeting_id": "meeting.fake_case_001",
        "target_id": "butler",
        "reason": "player knowledge does not cover required world info",
        "missing_required_evidence": ["torn_note"],
        "missing_required_world_info": ["secret_meeting_note_exists"],
    }
    serialized = json.dumps(stream, ensure_ascii=False)
    assert "claim_id" not in serialized
    assert "solution_claim_conditions" not in serialized
    assert "private_memory_refs" not in serialized


def test_public_action_response_meeting_state_carries_rejected_verdict_feedback() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.create_session(case)

    for target_id in ("desk", "carpet", "portrait"):
        runtime.handle_action(
            session_id=session.id,
            action=PlayerAction(type=ActionType.INSPECT, target_id=target_id),
        )
    session.narrative.phase = "reveal"
    session.player_knowledge[
        "player_knowledge.secret_meeting_note_exists"
    ].world_info_id = None
    runtime.handle_action(
        session_id=session.id,
        action=PlayerAction(type=ActionType.MEETING_START, target_id="meeting"),
    )

    response = runtime.handle_action(
        session_id=session.id,
        action=PlayerAction(
            type=ActionType.MEETING_PROPOSE_VERDICT,
            target_id="butler",
            evidence_clue_ids=["scratched_drawer", "dustless_frame", "torn_note"],
            text="The meeting reaches a verdict.",
        ),
    )

    public = build_public_action_response(response).model_dump(mode="json")
    verdict_event = next(
        event
        for event in public["new_events"]
        if event["type"] == "meeting.verdict.rejected"
    )

    assert response.accepted is False
    assert verdict_event["payload"]["missing_required_evidence"] == []
    assert verdict_event["payload"]["missing_required_world_info"] == [
        "secret_meeting_note_exists"
    ]
    assert public["state"]["meeting"]["verdict_status"] == "rejected"
    assert (
        public["state"]["meeting"]["verdict_reason"]
        == "player knowledge does not cover required world info"
    )
    assert public["state"]["meeting"]["missing_required_evidence"] == []
    assert public["state"]["meeting"]["missing_required_world_info"] == [
        "secret_meeting_note_exists"
    ]

    serialized = json.dumps(public, ensure_ascii=False)
    assert "claim_id" not in serialized
    assert "private_memory" not in serialized
