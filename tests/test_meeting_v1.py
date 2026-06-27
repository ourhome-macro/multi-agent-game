from __future__ import annotations

from pathlib import Path

from app.api.projections import build_public_action_response
from app.cases.loader import CaseLoader
from app.domain.models import ActionType, EventType, MeetingVoteChoice, PlayerAction
from app.runtime.replay import replay_events
from app.runtime.service import create_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_CASE_001_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


def test_meeting_start_ask_vote_and_replay_projection() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    start = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.MEETING_START,
            target_id="meeting",
            text="公开讨论书房案",
        ),
    )

    assert start.accepted is True
    assert [event.type for event in start.new_events] == [
        EventType.MEETING_SESSION_STARTED,
        EventType.MEETING_TURN_OPENED,
        EventType.MEETING_MESSAGE_POSTED,
    ]
    assert session.meeting.active is True
    assert session.meeting.participant_ids == ["butler", "niece"]
    public_start = build_public_action_response(start)
    assert public_start.state.meeting.active is True
    assert public_start.new_events[0].type == EventType.MEETING_SESSION_STARTED
    assert public_start.new_events[0].payload["participant_ids"] == ["butler", "niece"]

    asked = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.MEETING_ASK,
            target_id="butler",
            text="请管家说明书桌抽屉。",
        ),
    )

    assert asked.accepted is True
    asked_event_types = [event.type for event in asked.new_events]
    assert asked_event_types[:3] == [
        EventType.MEETING_MESSAGE_POSTED,
        EventType.MEETING_MESSAGE_PROPOSED,
        EventType.MEETING_MESSAGE_POSTED,
    ]
    assert asked_event_types.count(EventType.MEMORY_CANDIDATE_CREATED) == 2
    assert asked_event_types.count(EventType.AGENT_MEMORY_SNAPSHOT_UPDATED) == 2
    assert asked.new_events[1].actor_id == "butler"
    assert asked.new_events[2].actor_id == "butler"

    voted = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.MEETING_OPEN_VOTE,
            target_id="butler",
            text="是否认为管家嫌疑最高？",
        ),
    )

    assert voted.accepted is True
    voted_event_types = [event.type for event in voted.new_events]
    assert voted_event_types[:3] == [
        EventType.MEETING_VOTE_OPENED,
        EventType.MEETING_VOTE_CAST,
        EventType.MEETING_VOTE_CAST,
    ]
    assert voted_event_types.count(EventType.MEMORY_CANDIDATE_CREATED) == 2
    assert voted_event_types.count(EventType.AGENT_MEMORY_SNAPSHOT_UPDATED) == 2
    assert session.meeting.vote_open is True
    assert session.meeting.vote_target_id == "butler"
    assert session.meeting.votes["butler"].choice == MeetingVoteChoice.DEFEND

    replayed = replay_events(case, session.events)
    assert replayed.meeting.active is True
    assert replayed.meeting.vote_open is True
    assert replayed.meeting.vote_target_id == "butler"
    assert replayed.meeting.votes["butler"].choice == MeetingVoteChoice.DEFEND


def test_meeting_verdict_rejects_when_evidence_chain_is_incomplete() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.MEETING_START, target_id="meeting"),
    )

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.MEETING_PROPOSE_VERDICT,
            target_id="butler",
            evidence_clue_ids=[],
            text="会议认为管家有罪。",
        ),
    )

    assert response.accepted is False
    assert [event.type for event in response.new_events] == [
        EventType.MEETING_VERDICT_PROPOSED,
        EventType.MEETING_VERDICT_REJECTED,
        EventType.RULE_REJECTED,
    ]
    assert EventType.PLAYER_ACCUSED not in {event.type for event in session.events}
    assert session.meeting.verdict_status == "rejected"


def test_meeting_verdict_can_feed_formal_accusation_after_rule_validation() -> None:
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
            evidence_clue_ids=["scratched_drawer", "dustless_frame", "torn_note"],
            text="会议裁定管家移动了关键物证。",
        ),
    )

    assert response.accepted is True
    assert [event.type for event in response.new_events[:4]] == [
        EventType.MEETING_VERDICT_PROPOSED,
        EventType.MEETING_VERDICT_ACCEPTED,
        EventType.PLAYER_ACCUSED,
        EventType.ACCUSATION_EVALUATED,
    ]
    event_types = [event.type for event in response.new_events]
    assert EventType.NARRATIVE_BEAT_COMPLETED in event_types
    assert EventType.NARRATIVE_PHASE_CHANGED in event_types
    narrations = [
        event
        for event in response.new_events
        if event.type == EventType.MEETING_MESSAGE_POSTED
        and event.payload.get("message_kind") == "narration"
    ]
    assert len(narrations) >= 2
    assert all(event.actor_id == "director" for event in narrations)
    assert any(
        event.caused_by_event_id
        for event in narrations
        if event.payload.get("narrates_event_type") == EventType.NARRATIVE_PHASE_CHANGED.value
    )
    public_response = build_public_action_response(response)
    assert any(
        event.type == EventType.MEETING_MESSAGE_POSTED
        and event.payload.get("message_kind") == "narration"
        for event in public_response.new_events
    )
    assert session.meeting.verdict_status == "accepted"
    assert session.meeting.verdict_result == "correct"
    assert session.narrative.phase == "resolved"
