from __future__ import annotations

import json
from pathlib import Path

from app.agents.context import build_agent_context
from app.agents.gateway import AgentGateway
from app.agents.memory import MemoryRetriever
from app.agents.retrieval_planner import RetrievalPlanner
from app.agents.tools.runtime import ToolRuntime
from app.cases.loader import CaseLoader
from app.domain.models import (
    ActionType,
    AgentIntent,
    AgentIntentType,
    AgentMemorySnapshot,
    PlayerAction,
    SessionState,
    SubjectType,
)
from app.runtime.service import create_runtime
from app.runtime.tracing import RuntimeTracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"
JIANG = "jiang_yanhui"
EMPTY_CAPSULES = "empty_capsules"


class QuietAgent:
    backend_name = "mock"
    model_name = "quiet-agent"

    def generate(self, context: object) -> AgentIntent:
        return AgentIntent(
            speech="I will answer within limits.",
            intent=AgentIntentType.ANSWER,
            proposed_actions=[],
            memory_refs=[],
        )


def test_unknown_clue_progressive_rule_blocks_memory_projection() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="seed event"),
    )
    _add_memory_set(session)
    action = _ask_empty_capsules()

    plan = RetrievalPlanner().plan(case=case, session=session, action=action)
    memories = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=action,
        plan=plan,
    )
    context = build_agent_context(case, session, action, retrieval_plan=plan)

    assert plan.handoff_to_director is True
    assert plan.max_memory_items == 0
    assert plan.included_memory_types == ()
    assert plan.inject_portrait_summary is False
    assert plan.allow_recent_events is False
    assert len(session.events) > 0
    assert memories == []
    assert context.memory_snapshots == []
    assert context.recent_events == []
    assert (
        ToolRuntime()
        .call(
            "get_recent_events",
            case=case,
            session=session,
            action=action,
            plan=plan,
        )
        .result_count
        == 0
    )


def test_opening_phase_uses_low_clue_disclosure_projection() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    session.discovered_clues.add(EMPTY_CAPSULES)
    _add_memory_set(session)
    action = _ask_empty_capsules()

    plan = RetrievalPlanner().plan(case=case, session=session, action=action)
    memories = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=action,
        plan=plan,
    )

    assert session.narrative.phase == "opening"
    assert plan.disclosure_level == "low"
    assert plan.included_memory_types == ("episodic",)
    assert plan.max_memory_items == 2
    assert len(memories) <= 2
    assert {memory.memory_type for memory in memories} <= {"episodic"}


def test_late_phase_allows_deeper_memory_projection() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    session.narrative.phase = "reconstruction"
    session.discovered_clues.add(EMPTY_CAPSULES)
    _add_memory_set(session)
    action = _ask_empty_capsules()

    plan = RetrievalPlanner().plan(case=case, session=session, action=action)
    memories = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=action,
        plan=plan,
    )

    assert plan.disclosure_level == "deep"
    assert "belief" in plan.included_memory_types
    assert "strategy" in plan.included_memory_types
    assert {memory.memory_type for memory in memories} >= {"episodic", "belief", "strategy"}


def test_completed_beat_unlocks_belief_and_strategy_projection() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    session.narrative.phase = "investigation"
    session.narrative.completed_beats.add("mechanism_exposed")
    session.discovered_clues.add(EMPTY_CAPSULES)
    _add_memory_set(session)
    action = _ask_empty_capsules()

    plan = RetrievalPlanner().plan(case=case, session=session, action=action)

    assert plan.disclosure_level == "beat_unlocked"
    assert "belief" in plan.included_memory_types
    assert "strategy" in plan.included_memory_types


def test_forbidden_fact_memory_content_is_never_injected_by_skill() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    forbidden_text = case.forbidden_facts[0].text
    _add_snapshot(
        session,
        memory_id="memory.player.case.forbidden_fact_fixture",
        memory_type="episodic",
        memory_scope="case",
        memory_layer="core",
        content=f"Unsafe memory says {forbidden_text}",
    )
    action = PlayerAction(type=ActionType.TALK, target_id=JIANG, text="tell me")

    context = build_agent_context(case, session, action)
    memories = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=action,
        plan=RetrievalPlanner().plan(case=case, session=session, action=action),
    )

    assert "memory.player.case.forbidden_fact_fixture" not in {
        memory.memory_id for memory in context.memory_snapshots
    }
    assert "memory.player.case.forbidden_fact_fixture" not in {
        memory.memory_id for memory in memories
    }
    assert forbidden_text not in context.model_dump_json()


def test_trace_memory_projection_records_skill_summary_without_memory_content(
    tmp_path: Path,
) -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=QuietAgent()),
        runtime_tracer=RuntimeTracer(
            jsonl_path=tmp_path / "trace.jsonl",
            log_path=tmp_path / "trace.log",
        ),
    )
    session = runtime.session_store.create(case)
    _add_snapshot(
        session,
        memory_id="memory.player.case.trace_fixture",
        memory_type="episodic",
        memory_scope="case",
        memory_layer="core",
        content="TRACE_CONTENT_MUST_NOT_APPEAR jiang_yanhui",
    )

    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="trace fixture"),
    )

    record = json.loads((tmp_path / "trace.jsonl").read_text(encoding="utf-8"))
    projection = record["memory_projection"]
    serialized_projection = json.dumps(projection, ensure_ascii=False)

    assert projection["skill_id"] == "talk"
    assert projection["included_memory_types"]
    assert projection["included_scopes"]
    assert projection["included_layers"]
    assert "director_audit" in projection["forbidden_scopes"]
    assert "archival" in projection["forbidden_layers"]
    assert projection["selected_count"] == len(projection["items"])
    assert "TRACE_CONTENT_MUST_NOT_APPEAR" not in serialized_projection
    assert all("content" not in item for item in projection["items"])


def _ask_empty_capsules() -> PlayerAction:
    return PlayerAction(
        type=ActionType.ASK_ABOUT,
        target_id=JIANG,
        subject_type=SubjectType.CLUE,
        subject_id=EMPTY_CAPSULES,
        text="What about the empty capsules?",
    )


def _add_memory_set(session: SessionState) -> None:
    for memory_type in ("episodic", "belief", "relationship", "strategy"):
        _add_snapshot(
            session,
            memory_id=f"memory.player.{memory_type}.fixture.{EMPTY_CAPSULES}",
            memory_type=memory_type,
            memory_scope="npc_private",
            memory_layer="working",
            content=f"{memory_type} fixture {EMPTY_CAPSULES} {JIANG}",
        )


def _add_snapshot(
    session: SessionState,
    *,
    memory_id: str,
    memory_type: str,
    memory_scope: str,
    memory_layer: str,
    content: str,
) -> None:
    session.memory_snapshots[memory_id] = AgentMemorySnapshot(
        memory_id=memory_id,
        rule_id="test.progressive_disclosure",
        memory_type=memory_type,  # type: ignore[arg-type]
        memory_scope=memory_scope,  # type: ignore[arg-type]
        memory_layer=memory_layer,  # type: ignore[arg-type]
        subject_id="player",
        owner_character_id=JIANG if memory_scope == "npc_private" else None,
        visible_to_character_ids=[JIANG] if memory_scope == "npc_private" else [],
        content=content,
        source_event_ids=["test_event"],
        salience=1.0,
        last_updated_event_id="test_event",
    )
