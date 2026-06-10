from __future__ import annotations

from pathlib import Path

from app.agents.context import build_agent_context
from app.agents.memory import MemoryRetriever
from app.cases.loader import CaseLoader
from app.domain.models import ActionType, EventType, PlayerAction
from app.runtime.replay import replay_events
from app.runtime.service import create_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"

JIANG = "jiang_yanhui"
QI = "qi_yan"
SHEN = "shen_zhaoye"
STUDY = "study"
EMPTY_CAPSULES = "empty_capsules"

PRIVATE_PRESENTED_MEMORY = f"memory.player.presented_clue.{JIANG}.{EMPTY_CAPSULES}"
BELIEF_MEMORY = f"memory.player.belief.{JIANG}.{EMPTY_CAPSULES}"
RELATIONSHIP_MEMORY = f"memory.player.relationship.{JIANG}.{EMPTY_CAPSULES}"
STRATEGY_MEMORY = f"memory.player.strategy.{JIANG}.{EMPTY_CAPSULES}"
TYPED_MEMORY_IDS = {
    PRIVATE_PRESENTED_MEMORY,
    BELIEF_MEMORY,
    RELATIONSHIP_MEMORY,
    STRATEGY_MEMORY,
}
SCENE_SHARED_MEMORY = f"memory.player.scene_shared.presented_clue.{STUDY}.{EMPTY_CAPSULES}"
CLUE_DISCOVERY_MEMORY = f"memory.player.clue_discovered.{EMPTY_CAPSULES}"


def test_private_empty_capsules_memory_is_only_visible_to_jiang() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    _present_empty_capsules_to_jiang(runtime, session)

    candidate = session.memory_candidates[PRIVATE_PRESENTED_MEMORY]
    snapshot = session.memory_snapshots[PRIVATE_PRESENTED_MEMORY]

    assert candidate.memory_scope == "npc_private"
    assert candidate.memory_layer == "working"
    assert snapshot.memory_scope == "npc_private"
    assert snapshot.memory_layer == "working"
    assert snapshot.owner_character_id == JIANG
    assert snapshot.visible_to_character_ids == [JIANG]
    for memory_id in TYPED_MEMORY_IDS:
        typed_candidate = session.memory_candidates[memory_id]
        typed_snapshot = session.memory_snapshots[memory_id]
        assert typed_candidate.memory_scope == "npc_private"
        assert typed_candidate.memory_layer == "working"
        assert typed_snapshot.memory_scope == "npc_private"
        assert typed_snapshot.memory_layer == "working"
        assert typed_snapshot.owner_character_id == JIANG
        assert typed_snapshot.visible_to_character_ids == [JIANG]

    jiang_memories = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=_talk_action(JIANG, EMPTY_CAPSULES),
    )
    shen_memories = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=_talk_action(SHEN, EMPTY_CAPSULES),
    )
    assert PRIVATE_PRESENTED_MEMORY in _memory_ids(jiang_memories)
    assert PRIVATE_PRESENTED_MEMORY not in _memory_ids(shen_memories)

    shen_context = build_agent_context(case, session, _talk_action(SHEN, EMPTY_CAPSULES))
    assert PRIVATE_PRESENTED_MEMORY not in _context_memory_ids(shen_context)


def test_public_empty_capsules_memory_is_scene_shared_to_present_npcs() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.PRESENT_CLUE,
            target_id=JIANG,
            clue_id=EMPTY_CAPSULES,
            scene_id=STUDY,
            text="publicly present empty capsules",
        ),
    )

    presented_event = next(
        event for event in session.events if event.type == EventType.PLAYER_PRESENTED_CLUE
    )
    assert presented_event.payload["scene_id"] == STUDY
    assert set(presented_event.payload["present_character_ids"]) == {
        "lin_qichi",
        QI,
        JIANG,
    }

    shared_snapshot = session.memory_snapshots[SCENE_SHARED_MEMORY]
    assert shared_snapshot.memory_scope == "scene_shared"
    assert shared_snapshot.memory_layer == "working"
    assert set(shared_snapshot.visible_to_character_ids) == {"lin_qichi", QI, JIANG}

    qi_memories = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=_talk_action(QI, EMPTY_CAPSULES),
    )
    shen_memories = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=_talk_action(SHEN, EMPTY_CAPSULES),
    )
    assert SCENE_SHARED_MEMORY in _memory_ids(qi_memories)
    assert SCENE_SHARED_MEMORY not in _memory_ids(shen_memories)

    qi_context = build_agent_context(case, session, _talk_action(QI, EMPTY_CAPSULES))
    assert SCENE_SHARED_MEMORY in _context_memory_ids(qi_context)


def test_director_audit_memory_is_visible_to_director_not_npc_context() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id=JIANG,
            text="force forbidden audit",
            force_forbidden=True,
        ),
    )

    assert response.director_blocked is True
    audit_snapshot = next(
        snapshot
        for snapshot in session.memory_snapshots.values()
        if snapshot.memory_scope == "director_audit"
    )
    assert audit_snapshot.memory_layer == "working"

    action = _talk_action(JIANG, "director blocked jiang_yanhui")
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
    npc_context = build_agent_context(case, session, action)

    assert audit_snapshot.memory_id in _memory_ids(director_memories)
    assert audit_snapshot.memory_id not in _memory_ids(npc_memories)
    assert audit_snapshot.memory_id not in _context_memory_ids(npc_context)


def test_replay_preserves_scene_shared_scope_and_layer() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.PRESENT_CLUE,
            target_id=JIANG,
            clue_id=EMPTY_CAPSULES,
            scene_id=STUDY,
            text="publicly present empty capsules",
        ),
    )

    replayed = replay_events(case, session.events)

    assert replayed.memory_candidates[SCENE_SHARED_MEMORY].memory_scope == "scene_shared"
    assert replayed.memory_candidates[SCENE_SHARED_MEMORY].memory_layer == "working"
    assert replayed.memory_snapshots[SCENE_SHARED_MEMORY].memory_scope == "scene_shared"
    assert replayed.memory_snapshots[SCENE_SHARED_MEMORY].memory_layer == "working"


def test_case_core_memory_is_injected_into_npc_context() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)

    _discover_empty_capsules(runtime, session)

    snapshot = session.memory_snapshots[CLUE_DISCOVERY_MEMORY]
    assert snapshot.memory_scope == "case"
    assert snapshot.memory_layer == "core"

    shen_context = build_agent_context(case, session, _talk_action(SHEN, EMPTY_CAPSULES))
    assert CLUE_DISCOVERY_MEMORY in _context_memory_ids(shen_context)


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
            text="privately present empty capsules",
        ),
    )


def _talk_action(target_id: str, text: str) -> PlayerAction:
    return PlayerAction(type=ActionType.TALK, target_id=target_id, text=text)


def _memory_ids(memories: list[object]) -> set[str]:
    return {str(memory.memory_id) for memory in memories}


def _context_memory_ids(context: object) -> set[str]:
    return {memory.memory_id for memory in context.memory_snapshots}
