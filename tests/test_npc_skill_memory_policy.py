from __future__ import annotations

from pathlib import Path

from app.cases.loader import CaseLoader
from app.domain.models import (
    ActionType,
    AgentMemorySnapshot,
    PlayerAction,
    SessionState,
    SubjectType,
)
from app.runtime.service import create_runtime
from app.runtime.tracing import RuntimeTracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "fake_case_001"
BUTLER_SKILL_ID = "butler_drawer_pressure_deflection"


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
