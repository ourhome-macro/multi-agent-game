from __future__ import annotations

from pathlib import Path

from app.cases.loader import CaseLoader
from app.domain.models import ActionType, AgentMemorySnapshot, EventType, PlayerAction
from app.runtime.events import EventRecorder
from app.runtime.meeting_context import MeetingContextBuilder
from app.runtime.meeting_speakers import MeetingSpeakerSelector
from app.runtime.service import create_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_CASE_001_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


def test_meeting_speaker_selector_only_returns_named_npc() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.MEETING_START, target_id="meeting"),
    )

    speakers = MeetingSpeakerSelector(max_speakers=2).select(
        case=case,
        session=session,
        action=PlayerAction(
            type=ActionType.MEETING_ASK,
            target_id="butler",
            text="Please answer from the meeting record.",
        ),
    )

    assert [speaker.speaker_id for speaker in speakers] == ["butler"]
    assert speakers[0].reason == "directly_asked"


def test_meeting_context_contains_only_public_messages_evidence_and_visible_memory() -> None:
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.MEETING_START, target_id="meeting"),
    )
    proposed_private = EventRecorder().append(
        session,
        actor_id="niece",
        event_type=EventType.MEETING_MESSAGE_PROPOSED,
        payload={
            "meeting_id": session.meeting.meeting_id,
            "speaker_id": "niece",
            "message_kind": "npc_reply",
            "text": "PROPOSED_PRIVATE_SHOULD_NOT_SURFACE",
        },
    )
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.MEETING_PRESENT_EVIDENCE,
            target_id="meeting",
            clue_id="scratched_drawer",
        ),
    )
    session.memory_snapshots = {
        "memory.butler.visible": AgentMemorySnapshot(
            memory_id="memory.butler.visible",
            memory_type="episodic",
            memory_scope="npc_private",
            memory_layer="working",
            subject_id="player",
            owner_character_id="butler",
            visible_to_character_ids=["butler"],
            content="BUTLER_VISIBLE_MEMORY",
            source_event_ids=[session.events[0].id],
            salience=0.9,
            confidence=0.8,
            last_updated_event_id=session.events[0].id,
        ),
        "memory.niece.private": AgentMemorySnapshot(
            memory_id="memory.niece.private",
            memory_type="episodic",
            memory_scope="npc_private",
            memory_layer="working",
            subject_id="player",
            owner_character_id="niece",
            visible_to_character_ids=["niece"],
            content="NIECE_PRIVATE_SHOULD_NOT_SURFACE",
            source_event_ids=[proposed_private.id],
            salience=1.0,
            confidence=0.9,
            last_updated_event_id=proposed_private.id,
        ),
        "memory.director.audit": AgentMemorySnapshot(
            memory_id="memory.director.audit",
            memory_type="belief",
            memory_scope="director_audit",
            memory_layer="working",
            subject_id="case",
            owner_character_id=None,
            visible_to_character_ids=[],
            content="GLOBAL_TRUTH_SHOULD_NOT_SURFACE",
            source_event_ids=[proposed_private.id],
            salience=1.0,
            confidence=1.0,
            last_updated_event_id=proposed_private.id,
        ),
    }

    context = MeetingContextBuilder().build(
        case=case,
        session=session,
        speaker_id="butler",
        action=PlayerAction(
            type=ActionType.MEETING_ASK,
            target_id="butler",
            text="What can you say about the drawer?",
        ),
    )

    assert all(message.event_id != proposed_private.id for message in context.public_messages)
    assert [item.clue_id for item in context.public_evidence] == ["scratched_drawer"]
    assert [item.memory_id for item in context.visible_memories] == [
        "memory.butler.visible"
    ]
    serialized = repr(context)
    assert "BUTLER_VISIBLE_MEMORY" in serialized
    assert "PROPOSED_PRIVATE_SHOULD_NOT_SURFACE" not in serialized
    assert "NIECE_PRIVATE_SHOULD_NOT_SURFACE" not in serialized
    assert "GLOBAL_TRUTH_SHOULD_NOT_SURFACE" not in serialized
    assert "desk_forced_open" not in serialized


def test_meeting_ask_records_npc_proposed_then_posted_message() -> None:
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
            type=ActionType.MEETING_ASK,
            target_id="butler",
            text="Please answer from the meeting record.",
        ),
    )

    assert response.accepted is True
    event_types = [event.type for event in response.new_events]
    assert event_types[:3] == [
        EventType.MEETING_MESSAGE_POSTED,
        EventType.MEETING_MESSAGE_PROPOSED,
        EventType.MEETING_MESSAGE_POSTED,
    ]
    assert event_types.count(EventType.MEMORY_CANDIDATE_CREATED) == 2
    assert event_types.count(EventType.AGENT_MEMORY_SNAPSHOT_UPDATED) == 2
    player_question, proposed, posted = response.new_events[:3]
    assert proposed.actor_id == "butler"
    assert posted.actor_id == "butler"
    assert proposed.caused_by_event_id == player_question.id
    assert posted.caused_by_event_id == proposed.id
    assert proposed.payload["source"] == "deterministic_meeting_speaker_v1"
    assert proposed.payload["question_event_id"] == player_question.id
    assert proposed.payload["context_refs"]["meeting_event_ids"][-1] == player_question.id
