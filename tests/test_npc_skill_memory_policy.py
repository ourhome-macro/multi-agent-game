from __future__ import annotations

from pathlib import Path

from app.cases.loader import CaseLoader
from app.domain.models import (
    ActionType,
    AgentMemorySnapshot,
    PlayerAction,
    PlayerKnowledgeState,
    SessionState,
    SubjectType,
)
from app.runtime.service import create_runtime
from app.runtime.tracing import RuntimeTracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "fake_case_001"
MIST_CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"
BUTLER_SKILL_ID = "butler_drawer_pressure_deflection"
SHEN = "shen_zhaoye"
QI = "qi_yan"
SHEN_RECONSTRUCTION_SKILL_ID = "shen_reconstruction_chain_boundary"
SHEN_RECONSTRUCTION_STRATEGY = (
    "memory.player.strategy.reconstruction.shen_zhaoye.shared_death_chain"
)
QI_RECONSTRUCTION_STRATEGY = (
    "memory.player.strategy.reconstruction.qi_yan.shared_death_chain"
)
RECONSTRUCTION_CLUES = {
    "bitter_wine": "sedative_wine",
    "delayed_lock_marks": "timed_lock_modified",
    "echo_tape": "recording_tape_swapped",
    "empty_capsules": "heart_medicine_replaced",
    "cut_power_trace": "power_cut_by_shen",
}


def test_selected_npc_skill_memory_policy_narrows_final_retrieval_plan() -> None:
    case, runtime, session = _runtime_with_drawer_unlocked()
    action = _ask_about_drawer()

    context = runtime.agent_loop.build_context(case=case, session=session, action=action)
    turn_plan = runtime.agent_loop.plan_turn(
        case=case,
        session=session,
        action=action,
        context=context,
    )
    plan = turn_plan.memory_retrieval_plan

    assert plan is not None
    assert plan.skill_id == "ask_about_clue"
    assert plan.included_memory_types == ("episodic", "belief")
    assert plan.included_scopes == ("npc_private", "scene_shared")
    assert plan.included_layers == ("working",)
    assert plan.included_topic_tags == ("drawer",)
    assert plan.max_memory_items == 3
    assert plan.npc_skill_policy_ids == (BUTLER_SKILL_ID,)
    assert plan.trace_summary(selected_count=0)["final_plan_source"] == {
        "base_memory_skill_id": "ask_about_clue",
        "npc_skill_policy_ids": [BUTLER_SKILL_ID],
    }


def test_selected_npc_skill_memory_policy_controls_actual_retriever_results() -> None:
    case, runtime, session = _runtime_with_drawer_unlocked()
    action = _ask_about_drawer()
    _add_snapshot(
        session,
        memory_id="memory.drawer.selected_private",
        memory_type="belief",
        memory_scope="npc_private",
        memory_layer="working",
        content="The butler remembers the drawer pressure.",
        owner_character_id="butler",
        topic_tags=["drawer"],
    )
    _add_snapshot(
        session,
        memory_id="memory.drawer.filtered_by_scope",
        memory_type="belief",
        memory_scope="case",
        memory_layer="core",
        content="A case-level drawer note should not be pulled by this NPC skill.",
        topic_tags=["drawer"],
    )
    _add_snapshot(
        session,
        memory_id="memory.drawer.filtered_by_tag",
        memory_type="belief",
        memory_scope="npc_private",
        memory_layer="working",
        content="The butler remembers unrelated pressure.",
        owner_character_id="butler",
        topic_tags=["unrelated"],
    )
    _add_snapshot(
        session,
        memory_id="memory.drawer.filtered_by_visibility",
        memory_type="belief",
        memory_scope="npc_private",
        memory_layer="working",
        content="Another NPC remembers the drawer pressure.",
        owner_character_id="maid",
        topic_tags=["drawer"],
    )

    context = runtime.agent_loop.build_context(case=case, session=session, action=action)
    retrieved_ids = [memory.memory_id for memory in context.memory_snapshots]

    assert retrieved_ids == ["memory.drawer.selected_private"]


def test_selected_npc_skill_memory_policy_blocks_archival_cold_recall() -> None:
    case, runtime, session = _runtime_with_drawer_unlocked()
    action = _ask_about_drawer()
    _add_snapshot(
        session,
        memory_id="memory.drawer.archival",
        memory_type="belief",
        memory_scope="npc_private",
        memory_layer="archival",
        content="The butler archived a drawer pressure memory.",
        owner_character_id="butler",
        topic_tags=["drawer"],
    )

    context = runtime.agent_loop.build_context(case=case, session=session, action=action)

    assert [memory.memory_id for memory in context.memory_snapshots] == []


def test_no_selected_npc_skill_keeps_base_memory_projection_plan() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    action = PlayerAction(type=ActionType.TALK, target_id="butler", text="Just chatting.")

    plan = runtime.agent_loop.plan_turn(
        case=case,
        session=session,
        action=action,
    ).memory_retrieval_plan

    assert plan is not None
    assert plan.skill_id == "talk"
    assert plan.npc_skill_policy_ids == ()
    assert plan.included_topic_tags == ()
    assert "case" in plan.included_scopes


def test_shen_reconstruction_talk_keeps_case_session_chain_memories() -> None:
    case = CaseLoader().load(MIST_CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    _unlock_shen_reconstruction_chain(session)
    expected_memory_ids = {
        "memory.player.clue_discovered.bitter_wine",
        "memory.player.clue_discovered.echo_tape",
        "memory.player.clue_discovered.empty_capsules",
        "memory.player.clue_discovered.cut_power_trace",
    }
    for clue_id in expected_memory_ids:
        _add_reconstruction_chain_snapshot(session, clue_id=clue_id.rsplit(".", 1)[-1])

    action = PlayerAction(
        type=ActionType.TALK,
        target_id=SHEN,
        text=(
            "Connect bitter_wine, echo_tape, empty_capsules, "
            "cut_power_trace, and delayed_lock_marks."
        ),
    )
    context = runtime.agent_loop.build_context(case=case, session=session, action=action)
    plan = runtime.agent_loop.plan_turn(
        case=case,
        session=session,
        action=action,
        context=context,
    ).memory_retrieval_plan

    assert plan is not None
    assert plan.skill_id == "talk"
    assert plan.npc_skill_policy_ids == (SHEN_RECONSTRUCTION_SKILL_ID,)
    assert {"case", "session"}.issubset(plan.included_scopes)
    assert SHEN_RECONSTRUCTION_SKILL_ID in {
        skill.skill_id for skill in context.npc_skill_projections
    }
    assert expected_memory_ids.issubset(
        {memory.memory_id for memory in context.memory_snapshots}
    )


def test_shen_reconstruction_talk_expands_from_power_node_to_case_thread() -> None:
    case = CaseLoader().load(MIST_CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    _unlock_shen_reconstruction_chain(session)
    for clue_id in RECONSTRUCTION_CLUES:
        _add_reconstruction_thread_snapshot(session, clue_id=clue_id)
    _add_reconstruction_thread_typed_snapshot(
        session,
        memory_id="memory.player.strategy.reconstruction.shared_death_chain",
        memory_type="strategy",
        content="When reconstruction is unlocked, connect discovered evidence as chain nodes.",
    )

    context = runtime.agent_loop.build_context(
        case=case,
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id=SHEN,
            text="How does cut_power_trace matter in the reconstruction?",
        ),
    )

    retrieved_ids = {memory.memory_id for memory in context.memory_snapshots}
    assert {
        "memory.player.clue_discovered.bitter_wine",
        "memory.player.clue_discovered.delayed_lock_marks",
        "memory.player.clue_discovered.echo_tape",
        "memory.player.clue_discovered.empty_capsules",
        "memory.player.clue_discovered.cut_power_trace",
        "memory.player.strategy.reconstruction.shared_death_chain",
    }.issubset(retrieved_ids)


def test_case_thread_expansion_is_not_used_before_reconstruction() -> None:
    case = CaseLoader().load(MIST_CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    session.narrative.phase = "investigation"
    session.discovered_clues.update(RECONSTRUCTION_CLUES)
    for clue_id in RECONSTRUCTION_CLUES:
        _add_reconstruction_thread_snapshot(session, clue_id=clue_id)

    context = runtime.agent_loop.build_context(
        case=case,
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id=SHEN,
            text="How does cut_power_trace matter right now?",
        ),
    )

    retrieved_ids = {memory.memory_id for memory in context.memory_snapshots}
    assert "memory.player.clue_discovered.cut_power_trace" in retrieved_ids
    assert "memory.player.clue_discovered.empty_capsules" not in retrieved_ids
    assert "memory.player.clue_discovered.echo_tape" not in retrieved_ids
    assert "memory.player.clue_discovered.bitter_wine" not in retrieved_ids


def test_shen_reconstruction_talk_uses_shen_private_strategy_not_qi_strategy() -> None:
    case = CaseLoader().load(MIST_CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)

    for target_id in (
        "wine_table",
        "study_lock",
        "tape_recorder",
        "burned_letter",
        "medicine_box",
        "breaker_box",
    ):
        runtime.action_service.handle(
            session=session,
            action=PlayerAction(type=ActionType.INSPECT, target_id=target_id),
        )

    context = runtime.agent_loop.build_context(
        case=case,
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id=SHEN,
            text="How does cut_power_trace matter in reconstruction?",
        ),
    )

    retrieved_ids = {memory.memory_id for memory in context.memory_snapshots}
    assert {
        "memory.player.clue_discovered.bitter_wine",
        "memory.player.clue_discovered.delayed_lock_marks",
        "memory.player.clue_discovered.echo_tape",
        "memory.player.clue_discovered.empty_capsules",
        "memory.player.clue_discovered.cut_power_trace",
    }.issubset(retrieved_ids)
    assert SHEN_RECONSTRUCTION_STRATEGY in retrieved_ids
    assert QI_RECONSTRUCTION_STRATEGY not in retrieved_ids


def _runtime_with_drawer_unlocked() -> tuple[object, object, SessionState]:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="desk"),
    )
    return case, runtime, session


def _ask_about_drawer() -> PlayerAction:
    return PlayerAction(
        type=ActionType.ASK_ABOUT,
        target_id="butler",
        subject_type=SubjectType.CLUE,
        subject_id="scratched_drawer",
        text="What about the drawer scratches?",
    )


def _unlock_shen_reconstruction_chain(session: SessionState) -> None:
    session.narrative.phase = "reconstruction"
    session.narrative.completed_beats.add("motive_chain_exposed")
    session.discovered_clues.update(RECONSTRUCTION_CLUES)
    for clue_id, world_info_id in RECONSTRUCTION_CLUES.items():
        knowledge_id = f"player_knowledge.{world_info_id}"
        session.player_knowledge[knowledge_id] = PlayerKnowledgeState(
            knowledge_id=knowledge_id,
            clue_id=clue_id,
            world_info_id=world_info_id,
            title=f"Fixture knowledge for {world_info_id}",
            summary=f"Player has established {world_info_id}.",
            source_event_id=f"event.{clue_id}",
        )


def _add_reconstruction_chain_snapshot(
    session: SessionState,
    *,
    clue_id: str,
) -> None:
    topic_tags_by_clue = {
        "bitter_wine": ["bitter_wine", "sedative", "reconstruction"],
        "echo_tape": ["echo_tape", "tape_swapped", "reconstruction"],
        "empty_capsules": ["empty_capsules", "reconstruction"],
        "cut_power_trace": ["cut_power_trace", "power_cut", "reconstruction"],
    }
    session.memory_snapshots[f"memory.player.clue_discovered.{clue_id}"] = (
        AgentMemorySnapshot(
            memory_id=f"memory.player.clue_discovered.{clue_id}",
            rule_id="test.shen_reconstruction_chain",
            memory_type="episodic",
            memory_scope="case" if clue_id in {"bitter_wine", "empty_capsules"} else "session",
            memory_layer="core" if clue_id in {"bitter_wine", "empty_capsules"} else "working",
            subject_id="player",
            owner_character_id=None,
            visible_to_character_ids=[],
            content=f"Player discovered {clue_id} during the case chain.",
            source_event_ids=[f"event.{clue_id}"],
            salience=1.0,
            confidence=1.0,
            metadata={
                "clue_id": clue_id,
                "phase_ids": ["reconstruction"],
                "topic_tags": topic_tags_by_clue[clue_id],
            },
            last_updated_event_id=f"event.{clue_id}",
            created_at="2026-06-17T00:00:00Z",
            updated_at="2026-06-17T00:00:00Z",
        )
    )


def _add_reconstruction_thread_snapshot(
    session: SessionState,
    *,
    clue_id: str,
) -> None:
    session.memory_snapshots[f"memory.player.clue_discovered.{clue_id}"] = (
        AgentMemorySnapshot(
            memory_id=f"memory.player.clue_discovered.{clue_id}",
            rule_id="test.shen_reconstruction_thread",
            memory_type="episodic",
            memory_scope="case",
            memory_layer="core",
            subject_id="player",
            owner_character_id=None,
            visible_to_character_ids=[],
            content=f"Player discovered a case-critical clue node: {clue_id}.",
            source_event_ids=[f"event.{clue_id}"],
            salience=1.0,
            confidence=1.0,
            metadata={
                "clue_id": clue_id,
                "world_info_id": RECONSTRUCTION_CLUES[clue_id],
                "case_thread_id": "shared_death_chain",
                "chain_node_id": clue_id,
                "key_clue": True,
                "topic_tags": [clue_id],
            },
            last_updated_event_id=f"event.{clue_id}",
            created_at="2026-06-17T00:00:00Z",
            updated_at="2026-06-17T00:00:00Z",
        )
    )


def _add_reconstruction_thread_typed_snapshot(
    session: SessionState,
    *,
    memory_id: str,
    memory_type: str,
    content: str,
) -> None:
    session.memory_snapshots[memory_id] = AgentMemorySnapshot(
        memory_id=memory_id,
        rule_id="test.shen_reconstruction_thread_typed",
        memory_type=memory_type,  # type: ignore[arg-type]
        memory_scope="case",
        memory_layer="core",
        subject_id="player",
        owner_character_id=None,
        visible_to_character_ids=[],
        content=content,
        source_event_ids=["event.cut_power_trace"],
        source_memory_ids=["memory.player.clue_discovered.cut_power_trace"],
        salience=0.9,
        confidence=0.9,
        metadata={
            "case_thread_id": "shared_death_chain",
            "chain_node_id": "reconstruction_strategy",
            "key_clue": True,
            "topic_tags": ["cut_power_trace"],
        },
        last_updated_event_id="event.cut_power_trace",
        created_at="2026-06-17T00:00:00Z",
        updated_at="2026-06-17T00:00:00Z",
    )


def _add_snapshot(
    session: SessionState,
    *,
    memory_id: str,
    memory_type: str,
    memory_scope: str,
    memory_layer: str,
    content: str,
    owner_character_id: str | None = None,
    topic_tags: list[str] | None = None,
) -> None:
    session.memory_snapshots[memory_id] = AgentMemorySnapshot(
        memory_id=memory_id,
        rule_id="test.npc_skill_memory_policy",
        memory_type=memory_type,  # type: ignore[arg-type]
        memory_scope=memory_scope,  # type: ignore[arg-type]
        memory_layer=memory_layer,  # type: ignore[arg-type]
        subject_id="player",
        owner_character_id=owner_character_id,
        visible_to_character_ids=[],
        content=content,
        source_event_ids=["event.drawer"],
        salience=1.0,
        confidence=1.0,
        metadata={"topic_tags": topic_tags or []},
        last_updated_event_id="event.drawer",
        created_at="2026-06-17T00:00:00Z",
        updated_at="2026-06-17T00:00:00Z",
    )
