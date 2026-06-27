from __future__ import annotations

from app.domain.models import (
    CaseMeta,
    CasePackage,
    CharacterConfig,
    ClueConfig,
    EventType,
    MeetingSessionState,
    NarrativeState,
    SceneConfig,
    SessionState,
    WorldEvent,
)
from app.runtime.derivation_meeting_memory import MAX_MEETING_VOTE_CONFIDENCE
from app.runtime.derivation_utils import (
    meeting_npc_message_memory_id,
    meeting_shared_message_memory_id,
    meeting_vote_belief_memory_id,
)
from app.runtime.derivations import DerivedEventSystem
from app.runtime.events import EventRecorder
from app.runtime.memory_snapshots import MemorySnapshotSystem

CASE_ID = "meeting_memory_case"
SESSION_ID = "session.meeting_memory"
MEETING_ID = "meeting.session.meeting_memory.1"
PHASE = "investigation"
JIANG = "jiang_yanhui"
QI = "qi_yan"
EMPTY_CAPSULES = "empty_capsules"
WORLD_INFO_ID = "heart_medicine_replaced"
EVENT_TS = "2026-06-27T00:00:00Z"


def test_player_meeting_evidence_derives_scene_shared_working_memory() -> None:
    case = _case()
    session = _session(discovered_clues={EMPTY_CAPSULES})
    recorder = EventRecorder()
    message_event = _world_event(
        event_id="event.meeting.message.evidence",
        actor_id="player",
        event_type=EventType.MEETING_MESSAGE_POSTED,
        payload={
            "meeting_id": MEETING_ID,
            "speaker_id": "player",
            "message_kind": "evidence",
            "text": "The capsules were empty when found.",
            "clue_id": EMPTY_CAPSULES,
        },
    )
    before_clues = set(session.discovered_clues)
    before_phase = session.narrative.phase

    derived_events, snapshot_events = _derive_and_snapshot(
        case=case,
        session=session,
        recorder=recorder,
        source_event=message_event,
    )

    memory_id = meeting_shared_message_memory_id(MEETING_ID, message_event.id)
    candidate_event = _single_candidate_event(derived_events)
    snapshot = session.memory_snapshots[memory_id]
    metadata = candidate_event.payload["metadata"]

    assert candidate_event.payload["memory_id"] == memory_id
    assert candidate_event.payload["memory_type"] == "episodic"
    assert candidate_event.payload["memory_scope"] == "scene_shared"
    assert candidate_event.payload["memory_layer"] == "working"
    assert candidate_event.payload["owner_character_id"] is None
    assert candidate_event.payload["visible_to_character_ids"] == [JIANG, QI]
    assert metadata["authority_source"] == "player_evidence"
    assert metadata["authority"] == "event_observed"
    assert metadata["clue_id"] == EMPTY_CAPSULES
    assert metadata["world_info_id"] == WORLD_INFO_ID
    assert MEETING_ID in metadata["topic_tags"]
    assert len(snapshot_events) == 1
    assert snapshot.memory_scope == "scene_shared"
    assert snapshot.visible_to_character_ids == [JIANG, QI]
    assert session.discovered_clues == before_clues
    assert session.narrative.phase == before_phase


def test_player_meeting_speech_derives_scene_shared_working_memory() -> None:
    case = _case()
    session = _session()
    recorder = EventRecorder()
    message_event = _world_event(
        event_id="event.meeting.message.player",
        actor_id="player",
        event_type=EventType.MEETING_MESSAGE_POSTED,
        payload={
            "meeting_id": MEETING_ID,
            "speaker_id": "player",
            "message_kind": "speech",
            "text": "I want everyone to compare the timeline.",
        },
    )

    derived_events, snapshot_events = _derive_and_snapshot(
        case=case,
        session=session,
        recorder=recorder,
        source_event=message_event,
    )

    candidate_event = _single_candidate_event(derived_events)
    metadata = candidate_event.payload["metadata"]

    assert candidate_event.payload["memory_id"] == meeting_shared_message_memory_id(
        MEETING_ID,
        message_event.id,
    )
    assert candidate_event.payload["memory_scope"] == "scene_shared"
    assert candidate_event.payload["visible_to_character_ids"] == [JIANG, QI]
    assert metadata["authority_source"] == "player_action"
    assert metadata["authority"] == "player_claim"
    assert "clue_id" not in metadata
    assert len(snapshot_events) == 1


def test_npc_meeting_message_derives_only_that_npc_private_working_memory() -> None:
    case = _case()
    session = _session()
    recorder = EventRecorder()
    message_event = _world_event(
        event_id="event.meeting.message.npc",
        actor_id=QI,
        event_type=EventType.MEETING_MESSAGE_POSTED,
        payload={
            "meeting_id": MEETING_ID,
            "speaker_id": QI,
            "message_kind": "npc_reply",
            "text": "I can only speak to what was logged.",
        },
    )

    derived_events, snapshot_events = _derive_and_snapshot(
        case=case,
        session=session,
        recorder=recorder,
        source_event=message_event,
    )

    memory_id = meeting_npc_message_memory_id(QI, message_event.id)
    candidate_event = _single_candidate_event(derived_events)
    snapshot = session.memory_snapshots[memory_id]
    metadata = candidate_event.payload["metadata"]

    assert candidate_event.payload["memory_id"] == memory_id
    assert candidate_event.payload["memory_scope"] == "npc_private"
    assert candidate_event.payload["memory_layer"] == "working"
    assert candidate_event.payload["owner_character_id"] == QI
    assert candidate_event.payload["visible_to_character_ids"] == [QI]
    assert metadata["authority_source"] == "world_event"
    assert metadata["authority"] == "event_observed"
    assert metadata["privacy_reason"] == "meeting_npc_private"
    assert len(snapshot_events) == 1
    assert snapshot.owner_character_id == QI
    assert snapshot.visible_to_character_ids == [QI]


def test_director_meeting_narration_derives_rule_verified_scene_shared_memory() -> None:
    case = _case()
    session = _session()
    recorder = EventRecorder()
    narration_event = _world_event(
        event_id="event.meeting.message.narration",
        actor_id="director",
        event_type=EventType.MEETING_MESSAGE_POSTED,
        payload={
            "meeting_id": MEETING_ID,
            "speaker_id": "director",
            "message_kind": "narration",
            "text": "Narrator: The meeting moves the case into phase 'resolved'.",
            "phase": "resolved",
            "narrates_event_type": "narrative.phase.changed",
        },
    )

    derived_events, snapshot_events = _derive_and_snapshot(
        case=case,
        session=session,
        recorder=recorder,
        source_event=narration_event,
    )

    memory_id = meeting_shared_message_memory_id(MEETING_ID, narration_event.id)
    candidate_event = _single_candidate_event(derived_events)
    snapshot = session.memory_snapshots[memory_id]
    metadata = candidate_event.payload["metadata"]

    assert candidate_event.payload["memory_id"] == memory_id
    assert candidate_event.payload["memory_scope"] == "scene_shared"
    assert candidate_event.payload["memory_layer"] == "working"
    assert candidate_event.payload["visible_to_character_ids"] == [JIANG, QI]
    assert candidate_event.payload["content"].startswith("Director narrated")
    assert metadata["authority_source"] == "system_rule"
    assert metadata["authority"] == "rule_verified"
    assert metadata["phase_id"] == "resolved"
    assert "narration" in metadata["topic_tags"]
    assert len(snapshot_events) == 1
    assert snapshot.metadata["authority_source"] == "system_rule"
    assert session.narrative.phase == PHASE


def test_meeting_vote_derives_low_authority_belief_without_unlocking_clue_or_phase() -> None:
    case = _case()
    session = _session()
    recorder = EventRecorder()
    vote_event = _world_event(
        event_id="event.meeting.vote.1",
        actor_id=QI,
        event_type=EventType.MEETING_VOTE_CAST,
        payload={
            "meeting_id": MEETING_ID,
            "voter_id": QI,
            "target_id": JIANG,
            "choice": "accuse",
            "reason": "The vote is only a stance.",
            "clue_id": EMPTY_CAPSULES,
            "phase_id": "resolved",
        },
    )

    derived_events, snapshot_events = _derive_and_snapshot(
        case=case,
        session=session,
        recorder=recorder,
        source_event=vote_event,
    )

    memory_id = meeting_vote_belief_memory_id(MEETING_ID, vote_event.id)
    candidate_event = _single_candidate_event(derived_events)
    snapshot = session.memory_snapshots[memory_id]
    metadata = candidate_event.payload["metadata"]

    assert candidate_event.payload["memory_id"] == memory_id
    assert candidate_event.payload["memory_type"] == "belief"
    assert candidate_event.payload["memory_scope"] == "scene_shared"
    assert candidate_event.payload["memory_layer"] == "working"
    assert candidate_event.payload["confidence"] <= MAX_MEETING_VOTE_CONFIDENCE
    assert candidate_event.payload["visible_to_character_ids"] == [JIANG, QI]
    assert metadata["authority_source"] == "npc_hearsay"
    assert metadata["authority"] == "non_authoritative"
    assert metadata["non_authoritative"] is True
    assert metadata["belief_polarity"] == "suspects"
    assert "clue_id" not in metadata
    assert "world_info_id" not in metadata
    assert "phase_id" not in metadata
    assert "phase_ids" not in metadata

    assert len(snapshot_events) == 1
    assert snapshot.memory_type == "belief"
    assert snapshot.confidence <= MAX_MEETING_VOTE_CONFIDENCE
    assert snapshot.metadata["authority_source"] == "npc_hearsay"
    assert EMPTY_CAPSULES not in session.discovered_clues
    assert session.narrative.phase == PHASE


def _derive_and_snapshot(
    *,
    case: CasePackage,
    session: SessionState,
    recorder: EventRecorder,
    source_event: WorldEvent,
) -> tuple[list[WorldEvent], list[WorldEvent]]:
    derived_events = DerivedEventSystem(recorder).derive(
        case=case,
        session=session,
        source_events=[source_event],
    )
    snapshot_system = MemorySnapshotSystem(recorder)
    snapshot_events: list[WorldEvent] = []
    for event in derived_events:
        snapshot_events.extend(snapshot_system.apply(session=session, event=event))
    return derived_events, snapshot_events


def _single_candidate_event(events: list[WorldEvent]) -> WorldEvent:
    candidates = [
        event
        for event in events
        if event.type == EventType.MEMORY_CANDIDATE_CREATED
    ]
    assert len(candidates) == 1
    return candidates[0]


def _world_event(
    *,
    event_id: str,
    actor_id: str,
    event_type: EventType,
    payload: dict[str, object],
) -> WorldEvent:
    return WorldEvent.model_construct(
        id=event_id,
        case_id=CASE_ID,
        session_id=SESSION_ID,
        actor_id=actor_id,
        type=event_type,
        payload=payload,
        caused_by_event_id=None,
        created_at=EVENT_TS,
    )


def _case() -> CasePackage:
    return CasePackage(
        meta=CaseMeta(id=CASE_ID, title="Meeting Memory", initial_phase=PHASE),
        characters=[
            CharacterConfig(id=JIANG, display_name="Jiang", public_role="Doctor"),
            CharacterConfig(id=QI, display_name="Qi", public_role="Archivist"),
        ],
        scenes=[SceneConfig(id="meeting_room", name="Meeting Room")],
        clues=[
            ClueConfig(
                id=EMPTY_CAPSULES,
                title="Empty capsules",
                description="Empty capsules in the medicine box.",
                reveals_world_info=[WORLD_INFO_ID],
            )
        ],
    )


def _session(*, discovered_clues: set[str] | None = None) -> SessionState:
    return SessionState(
        id=SESSION_ID,
        case_id=CASE_ID,
        narrative=NarrativeState(phase=PHASE),
        meeting=MeetingSessionState(
            active=True,
            meeting_id=MEETING_ID,
            topic="Public case meeting",
            participant_ids=[JIANG, QI],
        ),
        relationships={},
        discovered_clues=discovered_clues or set(),
    )
