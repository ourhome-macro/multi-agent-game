from __future__ import annotations

from app.domain.models import (
    CaseMeta,
    CasePackage,
    CharacterConfig,
    EventType,
    NarrativeState,
    SceneConfig,
    SessionState,
)
from app.runtime.events import EventRecorder
from app.runtime.memory_snapshots import MemorySnapshotSystem
from app.runtime.replay import replay_events
from app.runtime.town_orchestrator import TownOrchestrator


def test_tick_once_closes_deterministic_town_observation_memory_loop() -> None:
    case = _town_case()
    session = _session(case)
    orchestrator = TownOrchestrator(recorder=EventRecorder())

    result = orchestrator.tick_once(case=case, session=session)

    event_types = [event.type for event in result.new_events]
    assert event_types == [
        EventType.TOWN_TICK_ADVANCED,
        EventType.NPC_LOCATION_CHANGED,
        EventType.NPC_OBSERVED,
        EventType.MEMORY_CANDIDATE_CREATED,
        EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
    ]
    assert len(result.candidate_intents) == 1
    assert result.candidate_intents[0].type == "move"
    assert result.candidate_intents[0].proposed_actions == []

    location_event = result.new_events[1]
    assert location_event.payload["from_scene_id"] == "foyer"
    assert location_event.payload["to_scene_id"] == "library"
    assert location_event.payload["current"]["scene_id"] == "library"
    assert session.npc_locations["butler"].scene_id == "library"

    observed_event = result.new_events[2]
    assert observed_event.actor_id == "heiress"
    assert observed_event.payload["observer_id"] == "heiress"
    assert observed_event.payload["observed_event_id"] == location_event.id
    assert "redacted_payload_ref" in observed_event.payload

    memory_event = result.new_events[3]
    assert memory_event.payload["rule_id"] == "memory_rule.core.npc_observed.episodic.v1"
    assert memory_event.payload["memory_scope"] == "npc_private"
    assert memory_event.payload["owner_character_id"] == "heiress"
    assert memory_event.payload["visible_to_character_ids"] == ["heiress"]
    assert memory_event.payload["source_event_ids"] == [observed_event.id, location_event.id]

    snapshot_event = result.new_events[4]
    memory_id = snapshot_event.payload["memory_id"]
    assert memory_id in session.memory_snapshots
    assert session.memory_snapshots[memory_id].source_event_ids == [
        observed_event.id,
        location_event.id,
    ]
    assert session.narrative.phase == "opening"
    assert session.discovered_clues == set()

    replayed = replay_events(case, session.events)
    assert [event.type for event in replayed.events] == event_types
    assert replayed.town_clock.tick == 1
    assert replayed.npc_locations["butler"].scene_id == "library"
    assert replayed.memory_snapshots[memory_id].source_event_ids == [
        observed_event.id,
        location_event.id,
    ]
    assert replayed.narrative.phase == "opening"
    assert replayed.discovered_clues == set()


def test_memory_snapshot_system_accepts_npc_private_non_player_subject() -> None:
    case = _town_case()
    session = _session(case)
    recorder = EventRecorder()
    source_event = recorder.append(
        session,
        actor_id="heiress",
        event_type=EventType.NPC_OBSERVED,
        payload={
            "observer_id": "heiress",
            "observed_event_id": "world-event-1",
            "scene_id": "library",
            "visibility": "public",
            "perception_quality": "direct",
            "redacted_payload_ref": "world_event:world-event-1:payload",
        },
    )
    candidate_event = recorder.append(
        session,
        actor_id="derived_event_system",
        event_type=EventType.MEMORY_CANDIDATE_CREATED,
        payload={
            "memory_id": "memory.npc_private.heiress.butler.observed",
            "rule_id": "memory_rule.test.npc_subject",
            "memory_type": "episodic",
            "memory_scope": "npc_private",
            "memory_layer": "working",
            "operation": "create",
            "subject_id": "butler",
            "owner_character_id": "heiress",
            "visible_to_character_ids": ["heiress"],
            "content": "Heiress saw Butler move through the library.",
            "source_event_id": source_event.id,
            "source_event_ids": [source_event.id],
            "source_memory_ids": [],
            "visibility": ["heiress"],
            "salience": 0.5,
            "confidence": 1.0,
            "metadata": {
                "authority_source": "world_event",
                "authority": "event_observed",
            },
        },
    )

    events = MemorySnapshotSystem(recorder).apply(
        session=session,
        event=candidate_event,
    )

    assert [event.type for event in events] == [EventType.AGENT_MEMORY_SNAPSHOT_UPDATED]
    snapshot = session.memory_snapshots["memory.npc_private.heiress.butler.observed"]
    assert snapshot.subject_id == "butler"
    assert snapshot.owner_character_id == "heiress"
    assert snapshot.visible_to_character_ids == ["heiress"]


def _town_case() -> CasePackage:
    return CasePackage(
        meta=CaseMeta(
            id="town_case",
            title="Town Case",
            initial_phase="opening",
        ),
        characters=[
            CharacterConfig(
                id="butler",
                display_name="Butler",
                public_role="Butler",
            ),
            CharacterConfig(
                id="heiress",
                display_name="Heiress",
                public_role="Heiress",
            ),
        ],
        scenes=[
            SceneConfig(
                id="foyer",
                name="Foyer",
                characters=["butler"],
            ),
            SceneConfig(
                id="library",
                name="Library",
                characters=["heiress"],
            ),
        ],
        clues=[],
    )


def _session(case: CasePackage) -> SessionState:
    return SessionState(
        id="town-session",
        case_id=case.meta.id,
        narrative=NarrativeState(phase=case.meta.initial_phase),
        relationships={},
    )
