from __future__ import annotations

from pathlib import Path
from typing import Any

from app.cases.loader import CaseLoader
from app.director.narrative_director import NarrativeDirector
from app.domain.models import (
    ActionType,
    EventType,
    PlayerAction,
    PresentationMode,
    SceneConfig,
)
from app.rules.engine import RuleEngine
from app.runtime.affordances import build_session_affordances
from app.runtime.events import EventRecorder
from app.runtime.npc_autonomy import (
    NPC_LOCATION_CHANGED_EVENT_TYPE,
    NpcAutonomyIntent,
    current_npc_scene_id,
)
from app.runtime.service import create_runtime
from app.storage.memory import InMemorySessionStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_CASE_001_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


def test_rule_engine_applies_legal_npc_autonomy_move() -> None:
    case = _case_with_hall()
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)

    events = RuleEngine(recorder).apply_npc_autonomy_intent(
        case=case,
        session=session,
        intent=NpcAutonomyIntent(
            type="move",
            actor_id="butler",
            from_scene_id="study",
            to_scene_id="hall",
        ),
        caused_by_event_id=session.events[0].id,
    )

    assert len(events) == 1
    assert str(events[0].type) == NPC_LOCATION_CHANGED_EVENT_TYPE
    assert events[0].payload["current"]["npc_id"] == "butler"
    assert events[0].payload["current"]["from_scene_id"] == "study"
    assert events[0].payload["current"]["scene_id"] == "hall"
    assert current_npc_scene_id(case, session, "butler") == "hall"
    assert _event_type_values(events).isdisjoint(
        {"clue.discovered", "narrative.phase.changed"}
    )


def test_rule_engine_rejects_npc_autonomy_move_to_unknown_scene() -> None:
    case = _case_with_hall()
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)

    events = RuleEngine(recorder).apply_npc_autonomy_intent(
        case=case,
        session=session,
        intent=NpcAutonomyIntent(
            type="move",
            actor_id="butler",
            from_scene_id="study",
            to_scene_id="cellar",
        ),
        caused_by_event_id=session.events[0].id,
    )

    assert events[0].type == EventType.RULE_REJECTED
    assert events[0].payload["reason"] == "to_scene_id is not a known scene"
    assert current_npc_scene_id(case, session, "butler") == "study"
    assert NPC_LOCATION_CHANGED_EVENT_TYPE not in _event_type_values(session.events)


def test_rule_engine_rejects_npc_autonomy_talk_to_target_in_other_scene() -> None:
    case = _case_with_hall()
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)
    engine = RuleEngine(recorder)
    engine.apply_npc_autonomy_intent(
        case=case,
        session=session,
        intent=NpcAutonomyIntent(
            type="move",
            actor_id="butler",
            from_scene_id="study",
            to_scene_id="hall",
        ),
        caused_by_event_id=session.events[0].id,
    )

    events = engine.apply_npc_autonomy_intent(
        case=case,
        session=session,
        intent=NpcAutonomyIntent(
            type="talk_to",
            actor_id="butler",
            target_id="niece",
        ),
        caused_by_event_id=session.events[-1].id,
    )

    assert events[0].type == EventType.RULE_REJECTED
    assert events[0].payload["reason"] == "target_id is not in actor current scene"
    assert "npc.talked_to" not in _event_type_values(session.events)


def test_director_precheck_rejects_npc_autonomy_forbidden_side_effect_flag() -> None:
    case = _case_with_hall()
    recorder = EventRecorder()
    session = InMemorySessionStore(recorder).create(case)

    decision = NarrativeDirector().precheck_npc_autonomy(
        case,
        session,
        NpcAutonomyIntent(
            type="wait",
            actor_id="butler",
            flags=["phase_change"],
        ),
    )

    assert decision.allowed is False
    assert decision.reason == "npc_autonomy_forbidden_side_effect"


def test_session_affordances_follow_runtime_npc_locations() -> None:
    case = _case_with_hall()
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )

    runtime.rule_engine.apply_npc_autonomy_intent(
        case=case,
        session=session,
        intent=NpcAutonomyIntent(
            type="move",
            actor_id="butler",
            from_scene_id="study",
            to_scene_id="hall",
        ),
        caused_by_event_id=session.events[-1].id,
    )

    affordances = build_session_affordances(
        case=case,
        session=session,
        rule_engine=runtime.rule_engine,
    )
    present_clue = next(
        item
        for item in affordances.present_clue
        if item.target_id == "butler" and item.clue_id == "scratched_drawer"
    )
    talk = next(item for item in affordances.talk if item.target_id == "butler")

    assert PresentationMode.SCENE_SHARED in present_clue.presentation_modes
    assert present_clue.scene_ids == ["hall"]
    assert talk.scene_ids == ["hall"]


def _case_with_hall():
    case = CaseLoader().load(FAKE_CASE_001_DIR)
    if any(scene.id == "hall" for scene in case.scenes):
        return case
    return case.model_copy(
        update={
            "scenes": [
                *case.scenes,
                SceneConfig(
                    id="hall",
                    name="Hall",
                    description="Secondary scene for autonomy movement tests.",
                ),
            ]
        }
    )


def _event_type_values(events: list[Any]) -> set[str]:
    return {str(event.type) for event in events}
