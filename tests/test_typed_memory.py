from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.memory import MemoryRetriever
from app.cases.loader import CaseLoader
from app.domain.models import (
    ActionType,
    AgentMemorySnapshot,
    CasePackage,
    EventType,
    NarrativeState,
    PlayerAction,
    SessionState,
    WorldEvent,
)
from app.runtime.derivations import (
    ASKED_ABOUT_MEMORY_RULE_ID,
    PRESENTED_CLUE_MEMORY_RULE_ID,
    DerivedEventSystem,
)
from app.runtime.events import EventRecorder
from app.runtime.memory_snapshots import MemorySnapshotSystem
from app.runtime.replay import replay_events
from app.runtime.service import create_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"

# Configured in cases/mist_clock_manor/memory_derivation_rules.yaml.
MEDICINE_PRESENTED_CLUE_RULE_ID = (
    "memory_rule.jiang_empty_capsules_medicine_pressure.presented_clue.v1"
)
MEDICINE_ASKED_ABOUT_RULE_ID = (
    "memory_rule.jiang_empty_capsules_medicine_pressure.asked_about.v1"
)
MEDICINE_STRATEGY_ID = "avoid_medicine_topic"

JIANG = "jiang_yanhui"
SHEN = "shen_zhaoye"
EMPTY_CAPSULES = "empty_capsules"
DELAYED_LOCK_MARKS = "delayed_lock_marks"

EPISODIC_MEMORY = f"memory.player.presented_clue.{JIANG}.{EMPTY_CAPSULES}"
BELIEF_MEMORY = f"memory.player.belief.{JIANG}.{EMPTY_CAPSULES}"
RELATIONSHIP_MEMORY = f"memory.player.relationship.{JIANG}.{EMPTY_CAPSULES}"
STRATEGY_MEMORY = f"memory.player.strategy.{JIANG}.{EMPTY_CAPSULES}"
SHEN_ASKED_MEMORY = f"memory.player.asked_about.{SHEN}.clue.{EMPTY_CAPSULES}"
TYPED_MEMORY_IDS = {
    EPISODIC_MEMORY,
    BELIEF_MEMORY,
    RELATIONSHIP_MEMORY,
    STRATEGY_MEMORY,
}


def test_rule_loader_merges_app_default_and_case_memory_derivation_rules() -> None:
    case = CaseLoader().load(CASE_DIR)

    rule_ids = {rule.id for rule in case.memory_derivation_rules}

    assert PRESENTED_CLUE_MEMORY_RULE_ID in rule_ids
    assert ASKED_ABOUT_MEMORY_RULE_ID in rule_ids
    assert MEDICINE_PRESENTED_CLUE_RULE_ID in rule_ids
    assert MEDICINE_ASKED_ABOUT_RULE_ID in rule_ids


def test_configured_rules_derive_all_supported_memory_types_from_presented_clue() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    memory_types = {
        session.memory_snapshots[memory_id].memory_type
        for memory_id in TYPED_MEMORY_IDS
    }
    assert memory_types == {"episodic", "belief", "relationship", "strategy"}


def test_configured_presented_clue_core_memory_matches_python_fallback_semantics() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    source_event = _presented_clue_event(session.events)
    configured_candidate = session.memory_candidates[EPISODIC_MEMORY]
    fallback_case = case.model_copy(update={"memory_derivation_rules": []})
    fallback_session = SessionState(
        id="session.fallback_memory_derivation",
        case_id=case.meta.id,
        narrative=NarrativeState(phase=case.meta.initial_phase),
        relationships={},
    )
    DerivedEventSystem(EventRecorder())._derive_presented_clue_memory_candidate(
        fallback_case,
        fallback_session,
        source_event,
    )

    assert fallback_session.memory_candidates[EPISODIC_MEMORY] == configured_candidate


def test_configured_asked_about_core_memory_matches_python_fallback_semantics() -> None:
    case = CaseLoader().load(CASE_DIR)
    source_event = _asked_about_event(case, target_id=SHEN, subject_id=EMPTY_CAPSULES)
    configured_session = _empty_session(case, "session.configured_asked_about")
    configured_events = DerivedEventSystem(EventRecorder()).derive(
        case=case,
        session=configured_session,
        source_events=[source_event],
    )
    configured_candidate = configured_session.memory_candidates[SHEN_ASKED_MEMORY]

    fallback_case = case.model_copy(update={"memory_derivation_rules": []})
    fallback_session = _empty_session(case, "session.fallback_asked_about")
    DerivedEventSystem(EventRecorder())._derive_asked_about_memory_candidate(
        fallback_case,
        fallback_session,
        source_event,
    )

    assert _memory_candidate_count(configured_events, SHEN_ASKED_MEMORY) == 1
    assert fallback_session.memory_candidates[SHEN_ASKED_MEMORY] == configured_candidate


def test_configured_asked_about_core_memory_suppresses_python_fallback() -> None:
    case = CaseLoader().load(CASE_DIR)
    session = _empty_session(case, "session.asked_about_no_duplicate")
    source_event = _asked_about_event(case, target_id=SHEN, subject_id=EMPTY_CAPSULES)
    derivation_system = DerivedEventSystem(EventRecorder())

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

    assert _memory_candidate_count(first_events, SHEN_ASKED_MEMORY) == 1
    assert _memory_candidate_count(second_events, SHEN_ASKED_MEMORY) == 0
    assert _session_memory_candidate_count(session, SHEN_ASKED_MEMORY, source_event.id) == 1


def test_asked_about_python_fallback_still_works_when_config_rules_are_disabled() -> None:
    case = CaseLoader().load(CASE_DIR)
    fallback_case = case.model_copy(update={"memory_derivation_rules": []})
    session = _empty_session(case, "session.asked_about_fallback")
    source_event = _asked_about_event(case, target_id=SHEN, subject_id=EMPTY_CAPSULES)

    events = DerivedEventSystem(EventRecorder()).derive(
        case=fallback_case,
        session=session,
        source_events=[source_event],
    )

    assert _memory_candidate_count(events, SHEN_ASKED_MEMORY) == 1
    snapshot = session.memory_candidates[SHEN_ASKED_MEMORY]
    assert snapshot.rule_id == ASKED_ABOUT_MEMORY_RULE_ID
    assert snapshot.memory_type == "episodic"
    assert snapshot.owner_character_id == SHEN


def test_configured_asked_about_core_memory_replays_equivalently() -> None:
    case = CaseLoader().load(CASE_DIR)
    recorder = EventRecorder()
    snapshot_system = MemorySnapshotSystem(recorder)
    session = _empty_session(case, "session.asked_about_replay")
    source_event = recorder.append(
        session,
        actor_id="player",
        event_type=EventType.PLAYER_ASKED_ABOUT,
        payload=_asked_about_payload(target_id=SHEN, subject_id=EMPTY_CAPSULES),
    )

    derived_events = DerivedEventSystem(recorder).derive(
        case=case,
        session=session,
        source_events=[source_event],
    )
    for event in derived_events:
        snapshot_system.apply(session=session, event=event)

    replayed = replay_events(case, session.events)

    assert replayed.memory_candidates[SHEN_ASKED_MEMORY] == session.memory_candidates[
        SHEN_ASKED_MEMORY
    ]
    assert replayed.memory_snapshots[SHEN_ASKED_MEMORY] == session.memory_snapshots[
        SHEN_ASKED_MEMORY
    ]


def test_presenting_empty_capsules_to_jiang_creates_episodic_memory() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    snapshot = session.memory_snapshots[EPISODIC_MEMORY]
    presented_event = _presented_clue_event(session.events)
    assert snapshot.memory_type == "episodic"
    assert snapshot.rule_id == PRESENTED_CLUE_MEMORY_RULE_ID
    assert snapshot.subject_id == "player"
    assert snapshot.owner_character_id == JIANG
    assert snapshot.visible_to_character_ids == [JIANG]
    assert snapshot.source_event_ids == [presented_event.id]


def test_empty_capsules_derives_jiang_belief_memory() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    snapshot = session.memory_snapshots[BELIEF_MEMORY]
    presented_event = _presented_clue_event(session.events)
    assert snapshot.memory_type == "belief"
    assert snapshot.rule_id == MEDICINE_PRESENTED_CLUE_RULE_ID
    assert snapshot.owner_character_id == JIANG
    assert snapshot.visible_to_character_ids == [JIANG]
    assert snapshot.source_event_ids == [presented_event.id]
    assert EPISODIC_MEMORY in snapshot.source_memory_ids
    assert snapshot.metadata["belief_subject"] == "player_approaching_medicine_truth"
    assert snapshot.metadata["belief_polarity"] == "believes"


def test_empty_capsules_derives_jiang_relationship_memory() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    snapshot = session.memory_snapshots[RELATIONSHIP_MEMORY]
    presented_event = _presented_clue_event(session.events)
    assert snapshot.memory_type == "relationship"
    assert snapshot.rule_id == MEDICINE_PRESENTED_CLUE_RULE_ID
    assert snapshot.source_event_ids == [presented_event.id]
    assert snapshot.metadata["relationship_delta"] == {"suspicion": 0.2, "trust": -0.1}
    assert EPISODIC_MEMORY in snapshot.source_memory_ids


def test_empty_capsules_derives_jiang_strategy_memory() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    snapshot = session.memory_snapshots[STRATEGY_MEMORY]
    presented_event = _presented_clue_event(session.events)
    assert snapshot.memory_type == "strategy"
    assert snapshot.rule_id == MEDICINE_PRESENTED_CLUE_RULE_ID
    assert snapshot.source_event_ids == [presented_event.id]
    assert snapshot.metadata["strategy_id"] == MEDICINE_STRATEGY_ID
    assert EPISODIC_MEMORY in snapshot.source_memory_ids


def test_memory_retriever_scoring_v1_hits_configured_derivation_by_anchor() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    memories = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=PlayerAction(
            type=ActionType.ASK_ABOUT,
            target_id=JIANG,
            subject_type="clue",
            subject_id=EMPTY_CAPSULES,
            text="continue asking about empty capsules",
        ),
    )

    assert {BELIEF_MEMORY, RELATIONSHIP_MEMORY, STRATEGY_MEMORY} <= _memory_ids(memories)


def test_default_asked_about_rule_creates_core_episodic_memory() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.ASK_ABOUT,
            target_id=SHEN,
            subject_type="clue",
            subject_id=EMPTY_CAPSULES,
            text="ask Shen about empty capsules",
        ),
    )

    snapshot = session.memory_snapshots[SHEN_ASKED_MEMORY]
    assert snapshot.rule_id == ASKED_ABOUT_MEMORY_RULE_ID
    assert snapshot.memory_type == "episodic"
    assert snapshot.owner_character_id == SHEN


def test_shen_cannot_retrieve_jiang_empty_capsule_typed_memories() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    memories = MemoryRetriever().retrieve(
        case=case,
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=SHEN, text="空胶囊"),
    )

    assert not (TYPED_MEMORY_IDS & _memory_ids(memories))


def test_replay_preserves_empty_capsule_typed_memories() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    replayed = replay_events(case, session.events)

    for memory_id in TYPED_MEMORY_IDS:
        assert replayed.memory_snapshots[memory_id] == session.memory_snapshots[memory_id]


def test_replaying_same_events_twice_does_not_reapply_portrait_deltas() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    replayed_once = replay_events(case, session.events)
    replayed_twice = replay_events(case, [*session.events, *session.events])

    assert replayed_once.character_impressions[JIANG]["player"].suspicion == (
        replayed_twice.character_impressions[JIANG]["player"].suspicion
    )
    assert replayed_once.character_impressions[JIANG]["player"].trust == (
        replayed_twice.character_impressions[JIANG]["player"].trust
    )


def test_memory_derivation_rule_does_not_fire_for_other_character_or_other_clue() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_shen(runtime, session)
    _discover_delayed_lock_marks(runtime, session)
    _present_delayed_lock_marks_to_jiang(runtime, session)

    assert BELIEF_MEMORY not in session.memory_snapshots
    assert RELATIONSHIP_MEMORY not in session.memory_snapshots
    assert STRATEGY_MEMORY not in session.memory_snapshots
    assert not any(
        snapshot.rule_id == MEDICINE_PRESENTED_CLUE_RULE_ID
        for snapshot in session.memory_snapshots.values()
    )


def test_memory_metadata_rejects_unstable_keys() -> None:
    with pytest.raises(ValueError, match="Unsupported memory metadata keys"):
        AgentMemorySnapshot(
            memory_id="memory.player.strategy.test",
            memory_type="strategy",
            subject_id="player",
            content="Test memory.",
            metadata={"strategy": "avoid_topic"},
            last_updated_event_id="event_1",
        )


def test_director_can_audit_typed_memories_without_injecting_them_into_shen_context() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    action = PlayerAction(type=ActionType.TALK, target_id=SHEN, text="空胶囊")
    director_memories = MemoryRetriever(max_results=20).retrieve_for_director(
        case=case,
        session=session,
        action=action,
    )
    npc_memories = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=action,
    )

    assert TYPED_MEMORY_IDS <= _memory_ids(director_memories)
    assert not (TYPED_MEMORY_IDS & _memory_ids(npc_memories))


def _discover_empty_capsules(runtime: object, session: object) -> None:
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="medicine_box"),
    )


def _present_empty_capsules_to_jiang(runtime: object, session: object) -> None:
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.PRESENT_CLUE,
            target_id=JIANG,
            clue_id=EMPTY_CAPSULES,
            text="把空胶囊给江医生看",
        ),
    )


def _present_empty_capsules_to_shen(runtime: object, session: object) -> None:
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.PRESENT_CLUE,
            target_id=SHEN,
            clue_id=EMPTY_CAPSULES,
            text="把空胶囊给沈照夜看",
        ),
    )


def _discover_delayed_lock_marks(runtime: object, session: object) -> None:
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="study_lock"),
    )


def _present_delayed_lock_marks_to_jiang(runtime: object, session: object) -> None:
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.PRESENT_CLUE,
            target_id=JIANG,
            clue_id=DELAYED_LOCK_MARKS,
            text="把门锁痕迹给江医生看",
        ),
    )


def _presented_clue_event(events: list[object]) -> object:
    return next(event for event in events if event.type == EventType.PLAYER_PRESENTED_CLUE)


def _asked_about_event(
    case: CasePackage,
    *,
    target_id: str,
    subject_id: str,
) -> WorldEvent:
    session = _empty_session(case, "session.source_asked_about")
    return EventRecorder().append(
        session,
        actor_id="player",
        event_type=EventType.PLAYER_ASKED_ABOUT,
        payload=_asked_about_payload(target_id=target_id, subject_id=subject_id),
    )


def _asked_about_payload(*, target_id: str, subject_id: str) -> dict[str, object]:
    return {
        "target_id": target_id,
        "subject_type": "clue",
        "subject_id": subject_id,
        "text": "ask about clue",
        "interaction_pressure": 0.5,
        "knowledge_id": f"player_knowledge.{subject_id}",
    }


def _empty_session(case: CasePackage, session_id: str) -> SessionState:
    return SessionState(
        id=session_id,
        case_id=case.meta.id,
        narrative=NarrativeState(phase=case.meta.initial_phase),
        relationships={},
    )


def _memory_ids(memories: list[object]) -> set[str]:
    return {str(memory.memory_id) for memory in memories}


def _memory_candidate_count(events: list[object], memory_id: str) -> int:
    return sum(
        1
        for event in events
        if event.type == EventType.MEMORY_CANDIDATE_CREATED
        and event.payload.get("memory_id") == memory_id
    )


def _session_memory_candidate_count(
    session: SessionState,
    memory_id: str,
    source_event_id: str,
) -> int:
    return sum(
        1
        for event in session.events
        if event.type == EventType.MEMORY_CANDIDATE_CREATED
        and event.payload.get("memory_id") == memory_id
        and source_event_id in event.payload.get("source_event_ids", [])
    )
