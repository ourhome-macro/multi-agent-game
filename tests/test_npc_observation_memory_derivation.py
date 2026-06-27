from __future__ import annotations

from app.domain.models import (
    CaseMeta,
    CasePackage,
    CharacterConfig,
    ClueConfig,
    EventType,
    NarrativeState,
    SceneConfig,
    SessionState,
    WorldEvent,
)
from app.runtime.derivation_npc_observation_memory import (
    MAX_HEARSAY_CONFIDENCE,
    NPC_HEARSAY_RECEIVED_EVENT_TYPE,
    NPC_OBSERVED_EVENT_TYPE,
)
from app.runtime.derivation_utils import (
    npc_hearsay_memory_id,
    npc_observed_memory_id,
)
from app.runtime.derivations import DerivedEventSystem
from app.runtime.events import EventRecorder
from app.runtime.memory_snapshots import MemorySnapshotSystem

CASE_ID = "npc_observation_memory_case"
SESSION_ID = "session.npc_observation_memory"
PHASE = "opening"
STUDY = "study"
JIANG = "jiang_yanhui"
QI = "qi_yan"
EMPTY_CAPSULES = "empty_capsules"
WORLD_INFO_ID = "heart_medicine_replaced"
EVENT_TS = "2026-06-27T00:00:00Z"


def test_npc_observed_derives_private_episodic_memory_candidate_and_snapshot() -> None:
    case = _case()
    session = _session()
    recorder = EventRecorder()
    observed_event = recorder.append(
        session,
        actor_id="player",
        event_type=EventType.PLAYER_TALKED,
        payload={"target_id": JIANG, "text": "ask Jiang about the medicine box"},
    )
    observation_event = _world_event(
        event_id="event.npc_observed.1",
        actor_id=QI,
        event_type=NPC_OBSERVED_EVENT_TYPE,
        payload={
            "observer_id": QI,
            "observed_event_id": observed_event.id,
            "summary": "Qi saw the player question Jiang about the medicine box.",
            "scene_id": STUDY,
        },
    )
    session.events.append(observation_event)

    derived_events, snapshot_events = _derive_and_snapshot(
        case=case,
        session=session,
        recorder=recorder,
        source_event=observation_event,
    )

    memory_id = npc_observed_memory_id(QI, observed_event.id)
    candidate_event = _single_candidate_event(derived_events)
    snapshot = session.memory_snapshots[memory_id]

    assert candidate_event.payload["memory_id"] == memory_id
    assert candidate_event.payload["memory_type"] == "episodic"
    assert candidate_event.payload["memory_scope"] == "npc_private"
    assert candidate_event.payload["memory_layer"] == "working"
    assert candidate_event.payload["owner_character_id"] == QI
    assert candidate_event.payload["visible_to_character_ids"] == [QI]
    assert candidate_event.payload["source_event_ids"] == [
        observation_event.id,
        observed_event.id,
    ]
    assert candidate_event.payload["metadata"]["authority_source"] == "world_event"
    assert candidate_event.payload["metadata"]["authority"] == "event_observed"

    assert len(snapshot_events) == 1
    assert snapshot_events[0].type == EventType.AGENT_MEMORY_SNAPSHOT_UPDATED
    assert snapshot.memory_scope == "npc_private"
    assert snapshot.owner_character_id == QI
    assert snapshot.visible_to_character_ids == [QI]
    assert snapshot.source_event_ids == [observation_event.id, observed_event.id]
    assert snapshot.metadata["authority_source"] == "world_event"
    assert snapshot.metadata["authority"] == "event_observed"


def test_npc_hearsay_derives_low_authority_belief_without_unlocking_clue_or_phase() -> None:
    case = _case()
    session = _session()
    recorder = EventRecorder()
    hearsay_event = _world_event(
        event_id="event.npc_hearsay.1",
        actor_id=QI,
        event_type=NPC_HEARSAY_RECEIVED_EVENT_TYPE,
        payload={
            "receiver_id": QI,
            "speaker_id": JIANG,
            "belief_subject": "jiang_claims_capsules_are_irrelevant",
            "belief_polarity": "believes",
            "summary": "Qi heard Jiang claim the empty capsules are irrelevant.",
            "confidence": 0.95,
            "clue_id": EMPTY_CAPSULES,
            "phase_id": "resolved",
        },
    )
    session.events.append(hearsay_event)

    derived_events, snapshot_events = _derive_and_snapshot(
        case=case,
        session=session,
        recorder=recorder,
        source_event=hearsay_event,
    )

    memory_id = npc_hearsay_memory_id(QI, hearsay_event.id)
    candidate_event = _single_candidate_event(derived_events)
    snapshot = session.memory_snapshots[memory_id]
    metadata = candidate_event.payload["metadata"]

    assert candidate_event.payload["memory_id"] == memory_id
    assert candidate_event.payload["memory_type"] == "belief"
    assert candidate_event.payload["memory_scope"] == "npc_private"
    assert candidate_event.payload["memory_layer"] == "working"
    assert candidate_event.payload["owner_character_id"] == QI
    assert candidate_event.payload["visible_to_character_ids"] == [QI]
    assert candidate_event.payload["confidence"] == MAX_HEARSAY_CONFIDENCE
    assert metadata["authority_source"] == "npc_hearsay"
    assert metadata["authority"] == "non_authoritative"
    assert metadata["non_authoritative"] is True
    assert "clue_id" not in metadata
    assert "world_info_id" not in metadata
    assert "phase_id" not in metadata
    assert "phase_ids" not in metadata

    assert len(snapshot_events) == 1
    assert snapshot.memory_type == "belief"
    assert snapshot.confidence <= MAX_HEARSAY_CONFIDENCE
    assert snapshot.metadata["authority_source"] == "npc_hearsay"
    assert snapshot.metadata["authority"] == "non_authoritative"
    assert snapshot.metadata["non_authoritative"] is True
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
    event_type: str,
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
        meta=CaseMeta(id=CASE_ID, title="NPC Observation Memory", initial_phase=PHASE),
        characters=[
            CharacterConfig(id=JIANG, display_name="Jiang", public_role="Doctor"),
            CharacterConfig(id=QI, display_name="Qi", public_role="Archivist"),
        ],
        scenes=[SceneConfig(id=STUDY, name="Study")],
        clues=[
            ClueConfig(
                id=EMPTY_CAPSULES,
                title="Empty capsules",
                description="Empty capsules in the medicine box.",
                reveals_world_info=[WORLD_INFO_ID],
            )
        ],
    )


def _session() -> SessionState:
    return SessionState(
        id=SESSION_ID,
        case_id=CASE_ID,
        narrative=NarrativeState(phase=PHASE),
        relationships={},
    )
