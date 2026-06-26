from __future__ import annotations

from pathlib import Path

from app.cases.loader import CaseLoader
from app.domain.models import EventType, NarrativeState, SessionState, WorldEvent
from app.runtime.derivation_utils import (
    accusation_evaluated_memory_id,
    asked_about_memory_id,
    case_thread_metadata_for_claim,
    clue_discovered_memory_id,
    clue_memory_metadata,
    player_accused_memory_id,
    presented_clue_memory_id,
    reconstruction_memory_id,
    scene_shared_presented_clue_memory_id,
    scene_shared_private_memory_id,
)
from app.runtime.derivations import DerivedEventSystem
from app.runtime.events import EventRecorder

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"

JIANG = "jiang_yanhui"
QI = "qi_yan"
LIN = "lin_qichi"
STUDY = "study"
EMPTY_CAPSULES = "empty_capsules"
CLAIM_ID = "shared_death_chain"


def test_memory_derivation_helpers_lock_stable_ids_and_clue_metadata() -> None:
    thread_metadata = case_thread_metadata_for_claim(
        claim_id=CLAIM_ID,
        clue_id=EMPTY_CAPSULES,
        required_evidence=["bitter_wine", EMPTY_CAPSULES, "echo_tape"],
    )
    metadata = clue_memory_metadata(
        clue_id=EMPTY_CAPSULES,
        related_event_ids=["medicine_box"],
        related_character_ids=[JIANG, JIANG],
        world_info_ids=["heart_medicine_replaced"],
        case_thread_metadata=thread_metadata,
    )

    assert clue_discovered_memory_id(EMPTY_CAPSULES) == (
        "memory.player.clue_discovered.empty_capsules"
    )
    assert presented_clue_memory_id(JIANG, EMPTY_CAPSULES) == (
        "memory.player.presented_clue.jiang_yanhui.empty_capsules"
    )
    assert asked_about_memory_id(QI, "clue", EMPTY_CAPSULES) == (
        "memory.player.asked_about.qi_yan.clue.empty_capsules"
    )
    assert scene_shared_presented_clue_memory_id(STUDY, EMPTY_CAPSULES) == (
        "memory.player.scene_shared.presented_clue.study.empty_capsules"
    )
    assert scene_shared_private_memory_id("belief", QI, STUDY, EMPTY_CAPSULES) == (
        "memory.player.scene_shared.belief.qi_yan.study.empty_capsules"
    )
    assert reconstruction_memory_id("strategy", CLAIM_ID, character_id=JIANG) == (
        "memory.player.strategy.reconstruction.jiang_yanhui.shared_death_chain"
    )
    assert player_accused_memory_id(JIANG, "final_accusation") == (
        "memory.player.accused.jiang_yanhui.final_accusation"
    )
    assert accusation_evaluated_memory_id(JIANG, "final_accusation", "correct") == (
        "memory.player.accusation_evaluated.jiang_yanhui.final_accusation.correct"
    )

    assert metadata == {
        "clue_id": EMPTY_CAPSULES,
        "topic_tags": ["empty", "capsules", EMPTY_CAPSULES, "medicine_box", JIANG],
        "world_info_id": "heart_medicine_replaced",
        "case_thread_id": CLAIM_ID,
        "chain_node_id": EMPTY_CAPSULES,
        "adjacent_clue_ids": ["bitter_wine", "echo_tape"],
        "key_clue": True,
        "is_plot_critical": True,
    }


def test_scene_shared_memory_derivation_is_idempotent_for_same_source_event() -> None:
    case = CaseLoader().load(CASE_DIR)
    session = SessionState(
        id="session.memory_derivation_helper_idempotence",
        case_id=case.meta.id,
        narrative=NarrativeState(phase=case.meta.initial_phase),
        relationships={},
    )
    recorder = EventRecorder()
    source_event = recorder.append(
        session,
        actor_id="player",
        event_type=EventType.PLAYER_PRESENTED_CLUE,
        payload={
            "target_id": JIANG,
            "clue_id": EMPTY_CAPSULES,
            "presentation_mode": "scene_shared",
            "scene_id": STUDY,
            "present_character_ids": [JIANG, QI, LIN],
            "text": "publicly present empty capsules",
            "interaction_pressure": 0.6,
        },
    )
    derivation_system = DerivedEventSystem(recorder)

    first_events = derivation_system.derive(
        case=case,
        session=session,
        source_events=[source_event],
    )
    second_events = derivation_system.derive(
        case=case,
        session=session,
        source_events=[source_event],
    )

    shared_memory_id = scene_shared_presented_clue_memory_id(STUDY, EMPTY_CAPSULES)
    qi_belief_id = scene_shared_private_memory_id("belief", QI, STUDY, EMPTY_CAPSULES)
    qi_strategy_id = scene_shared_private_memory_id("strategy", QI, STUDY, EMPTY_CAPSULES)

    assert _memory_candidate_count(first_events, shared_memory_id) == 1
    assert _memory_candidate_count(first_events, qi_belief_id) == 1
    assert _memory_candidate_count(first_events, qi_strategy_id) == 1
    assert _memory_candidate_count(second_events, shared_memory_id) == 0
    assert _memory_candidate_count(second_events, qi_belief_id) == 0
    assert _memory_candidate_count(second_events, qi_strategy_id) == 0


def _memory_candidate_count(events: list[WorldEvent], memory_id: str) -> int:
    return sum(
        1
        for event in events
        if event.type == EventType.MEMORY_CANDIDATE_CREATED
        and event.payload.get("memory_id") == memory_id
    )
