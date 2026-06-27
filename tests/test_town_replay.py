from __future__ import annotations

from app.domain.models import (
    CaseMeta,
    CasePackage,
    CharacterConfig,
    EventType,
    NarrativeState,
    NpcAutonomyIntent,
    NpcAutonomyIntentType,
    NpcLocationState,
    SceneConfig,
    SessionState,
    WorldEvent,
)
from app.runtime.replay import replay_events


def test_session_state_town_fields_have_compatible_defaults() -> None:
    session = SessionState(
        id="session.town.defaults",
        case_id="case.town",
        narrative=NarrativeState(phase="opening"),
        relationships={},
    )

    assert session.town_clock.tick == 0
    assert session.town_clock.updated_at_event_id is None
    assert session.npc_locations == {}

    location = NpcLocationState.model_validate(
        {"character_id": "butler", "scene_id": "hall"}
    )
    assert location.npc_id == "butler"


def test_replay_restores_town_tick_and_npc_locations_from_fixed_event_sequence() -> None:
    case = _case_package()
    events = [
        _event(
            event_id="event.session.created",
            actor_id="system",
            event_type=EventType.SESSION_CREATED,
            payload={"case_id": case.meta.id, "initial_phase": case.meta.initial_phase},
        ),
        _event(
            event_id="event.tick.1",
            actor_id="system",
            event_type=EventType.TOWN_TICK_ADVANCED,
            payload={"current": {"tick": 1}},
        ),
        _event(
            event_id="event.butler.location.hall",
            actor_id="butler",
            event_type=EventType.NPC_LOCATION_CHANGED,
            payload={
                "current": {
                    "npc_id": "butler",
                    "scene_id": "hall",
                    "updated_at_tick": 1,
                }
            },
        ),
        _event(
            event_id="event.butler.observed",
            actor_id="butler",
            event_type=EventType.NPC_OBSERVED,
            payload={"observer_id": "butler", "target_id": "niece", "scene_id": "hall"},
        ),
        _event(
            event_id="event.niece.hearsay",
            actor_id="niece",
            event_type=EventType.NPC_HEARSAY_RECEIVED,
            payload={"source_npc_id": "butler", "subject_id": "player"},
        ),
        _event(
            event_id="event.butler.intent.proposed",
            actor_id="butler",
            event_type=EventType.NPC_AUTONOMY_INTENT_PROPOSED,
            payload={
                "intent": NpcAutonomyIntent(
                    npc_id="butler",
                    type=NpcAutonomyIntentType.MOVE,
                    target_scene_id="library",
                    rationale="Check the locked cabinet.",
                ).model_dump(mode="json")
            },
        ),
        _event(
            event_id="event.butler.intent.rejected",
            actor_id="rule_engine",
            event_type=EventType.NPC_AUTONOMY_INTENT_REJECTED,
            payload={"npc_id": "butler", "reason": "target scene is locked"},
        ),
        _event(
            event_id="event.tick.2",
            actor_id="system",
            event_type=EventType.TOWN_TICK_ADVANCED,
            payload={"current": {"tick": 2}},
        ),
        _event(
            event_id="event.butler.location.library",
            actor_id="butler",
            event_type=EventType.NPC_LOCATION_CHANGED,
            payload={
                "current": {
                    "npc_id": "butler",
                    "scene_id": "library",
                    "position_x": 4.0,
                    "position_y": 2.5,
                    "updated_at_tick": 2,
                }
            },
        ),
    ]

    session = replay_events(case, events)

    assert session.town_clock.tick == 2
    assert session.town_clock.updated_at_event_id == "event.tick.2"
    assert session.npc_locations["butler"].scene_id == "library"
    assert session.npc_locations["butler"].position_x == 4.0
    assert session.npc_locations["butler"].position_y == 2.5
    assert session.npc_locations["butler"].updated_at_tick == 2
    assert session.npc_locations["butler"].updated_at_event_id == (
        "event.butler.location.library"
    )
    assert session.discovered_clues == set()
    assert session.player_knowledge == {}
    assert session.memory_candidates == {}
    assert session.memory_snapshots == {}
    assert session.character_impressions == {}
    assert len(session.events) == len(events)


def _case_package() -> CasePackage:
    return CasePackage(
        meta=CaseMeta(
            id="case.town",
            title="Town Case",
            initial_phase="opening",
        ),
        characters=[
            CharacterConfig(
                id="butler",
                display_name="Butler",
                public_role="Witness",
            ),
            CharacterConfig(
                id="niece",
                display_name="Niece",
                public_role="Witness",
            ),
        ],
        scenes=[
            SceneConfig(id="hall", name="Hall", characters=["butler", "niece"]),
            SceneConfig(id="library", name="Library", characters=[]),
        ],
        clues=[],
    )


def _event(
    *,
    event_id: str,
    actor_id: str,
    event_type: EventType,
    payload: dict[str, object],
) -> WorldEvent:
    return WorldEvent(
        id=event_id,
        case_id="case.town",
        session_id="session.town",
        actor_id=actor_id,
        type=event_type,
        payload=payload,
        created_at="2026-06-27T00:00:00Z",
    )
