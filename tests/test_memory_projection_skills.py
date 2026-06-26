from __future__ import annotations

from pathlib import Path

from app.agents.context import build_agent_context
from app.agents.memory import MemoryRetriever
from app.agents.retrieval_planner import (
    MemoryRetrievalPlan,
    RetrievalPlanner,
    SkillLoader,
)
from app.cases.loader import CaseLoader
from app.domain.models import (
    ActionType,
    AgentMemorySnapshot,
    PlayerAction,
    PresentationMode,
    SessionState,
    SubjectType,
)
from app.runtime.service import RuntimeContainer, create_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"
JIANG = "jiang_yanhui"
EMPTY_CAPSULES = "empty_capsules"


def test_skill_selector_maps_actions_to_default_projection_skills() -> None:
    case = CaseLoader().load(CASE_DIR)
    planner = RetrievalPlanner()

    talk = planner.select_skill(
        case=case,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="hello"),
    )
    ask_clue = planner.select_skill(
        case=case,
        action=PlayerAction(
            type=ActionType.ASK_ABOUT,
            target_id=JIANG,
            subject_type=SubjectType.CLUE,
            subject_id=EMPTY_CAPSULES,
        ),
    )
    accuse = planner.select_skill(
        case=case,
        action=PlayerAction(
            type=ActionType.ACCUSE,
            target_id=JIANG,
            claim_id="shared_death_chain",
            evidence_clue_ids=[EMPTY_CAPSULES],
        ),
    )

    assert talk.id == "talk"
    assert ask_clue.id == "ask_about_clue"
    assert accuse.id == "accuse"


def test_default_skill_plan_forbids_director_audit_and_archival() -> None:
    case = CaseLoader().load(CASE_DIR)
    session = create_runtime([case]).session_store.create(case)
    plan = RetrievalPlanner().plan(
        case=case,
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="hello"),
    )

    assert "director_audit" in plan.forbidden_scopes
    assert "director_audit" not in plan.included_scopes
    assert "archival" in plan.forbidden_layers
    assert "archival" not in plan.included_layers


def test_skill_max_memory_items_limits_retriever_results(tmp_path: Path) -> None:
    case, runtime, session = _runtime()
    _write_case_skill_override(
        tmp_path,
        case_id=case.meta.id,
        skill_id="talk",
        max_memory_items=2,
    )
    for index in range(4):
        _add_snapshot(
            session,
            memory_id=f"memory.player.case.fixture.{index}",
            memory_type="episodic",
            memory_scope="case",
            memory_layer="core",
            content=f"fixture memory {index} jiang_yanhui",
        )

    plan = _planner_with_case_root(tmp_path).plan(
        case=case,
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="fixture"),
    )
    memories = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="fixture"),
        plan=plan,
    )

    assert plan.max_memory_items == 2
    assert len(memories) == 2


def test_base_skill_plan_includes_topic_tags_from_skill_include(tmp_path: Path) -> None:
    case, _, session = _runtime()
    _write_case_skill_override(
        tmp_path,
        case_id=case.meta.id,
        skill_id="talk",
        topic_tags=["medicine_replaced", "pressure"],
    )

    plan = _planner_with_case_root(tmp_path).plan(
        case=case,
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="capsules"),
    )

    assert plan.included_topic_tags == ("medicine_replaced", "pressure")
    assert plan.trace_summary(selected_count=0)["included_topic_tags"] == [
        "medicine_replaced",
        "pressure",
    ]


def test_progressive_rule_include_topic_tags_updates_retrieval_plan(
    tmp_path: Path,
) -> None:
    case, _, session = _runtime()
    _write_case_skill_override(
        tmp_path,
        case_id=case.meta.id,
        skill_id="talk",
        topic_tags=["base_topic"],
        progressive_lines=[
            "    - when:",
            "        phase: opening",
            "      include:",
            "        topic_tags: [opening_topic, clue_pressure]",
        ],
    )

    plan = _planner_with_case_root(tmp_path).plan(
        case=case,
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="capsules"),
    )

    assert plan.included_topic_tags == ("opening_topic", "clue_pressure")


def test_memory_retriever_filters_skill_plan_topic_tags(tmp_path: Path) -> None:
    case, _, session = _runtime()
    _write_case_skill_override(
        tmp_path,
        case_id=case.meta.id,
        skill_id="talk",
        topic_tags=["medicine_replaced"],
    )
    _add_snapshot(
        session,
        memory_id="memory.topic_tags.allowed",
        memory_type="episodic",
        memory_scope="case",
        memory_layer="core",
        content="fixture topic recall about empty capsules and medicine pressure",
        topic_tags=["medicine_replaced"],
    )
    _add_snapshot(
        session,
        memory_id="memory.topic_tags.filtered",
        memory_type="episodic",
        memory_scope="case",
        memory_layer="core",
        content="fixture topic recall about empty capsules and medicine pressure",
        topic_tags=["unrelated"],
    )

    action = PlayerAction(
        type=ActionType.TALK,
        target_id=JIANG,
        text="fixture topic recall empty capsules medicine pressure",
    )
    plan = _planner_with_case_root(tmp_path).plan(
        case=case,
        session=session,
        action=action,
    )
    memories = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=action,
        plan=plan,
    )

    assert plan.included_topic_tags == ("medicine_replaced",)
    assert [memory.memory_id for memory in memories] == ["memory.topic_tags.allowed"]


def test_case_level_memory_projection_skill_overrides_app_default(tmp_path: Path) -> None:
    case, _, session = _runtime()
    _write_case_skill_override(
        tmp_path,
        case_id=case.meta.id,
        skill_id="talk",
        max_memory_items=1,
        portrait_summary=False,
    )

    plan = _planner_with_case_root(tmp_path).plan(
        case=case,
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="hello"),
    )

    assert plan.skill_id == "talk"
    assert plan.max_memory_items == 1
    assert plan.inject_portrait_summary is False


def test_case_level_skill_cannot_unforbid_director_audit_scope(tmp_path: Path) -> None:
    case, _, session = _runtime()
    _write_case_skill_override(
        tmp_path,
        case_id=case.meta.id,
        skill_id="talk",
        memory_scopes=["director_audit", "npc_private"],
        forbidden_scopes=[],
    )

    plan = _planner_with_case_root(tmp_path).plan(
        case=case,
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="hello"),
    )

    assert "director_audit" in plan.forbidden_scopes
    assert "director_audit" not in plan.included_scopes
    assert plan.included_scopes == ("npc_private",)


def test_portrait_summary_projection_switch_is_applied() -> None:
    case, runtime, session = _runtime()
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(type=ActionType.INSPECT, target_id="medicine_box"),
    )
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.PRESENT_CLUE,
            target_id=JIANG,
            clue_id=EMPTY_CAPSULES,
            presentation_mode=PresentationMode.PRIVATE,
            text="private pressure",
        ),
    )

    action = PlayerAction(type=ActionType.TALK, target_id=JIANG, text="capsules")
    with_portrait = build_agent_context(case, session, action)
    without_portrait = build_agent_context(
        case,
        session,
        action,
        retrieval_plan=MemoryRetrievalPlan(
            skill_id="test.no_portrait",
            included_memory_types=("episodic", "belief", "relationship", "strategy"),
            included_scopes=("case", "session", "npc_private", "scene_shared"),
            included_layers=("core", "working"),
            forbidden_scopes=("director_audit",),
            forbidden_layers=("archival",),
            max_memory_items=8,
            inject_portrait_summary=False,
            allow_recent_events=True,
        ),
    )

    assert with_portrait.portrait_summary is not None
    assert without_portrait.portrait_summary is None


def _runtime() -> tuple[object, RuntimeContainer, SessionState]:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    return case, runtime, runtime.session_store.create(case)


def _planner_with_case_root(tmp_path: Path) -> RetrievalPlanner:
    return RetrievalPlanner(skill_loader=SkillLoader(cases_root=tmp_path / "cases"))


def _write_case_skill_override(
    tmp_path: Path,
    *,
    case_id: str,
    skill_id: str,
    max_memory_items: int = 8,
    portrait_summary: bool = True,
    memory_scopes: list[str] | None = None,
    forbidden_scopes: list[str] | None = None,
    topic_tags: list[str] | None = None,
    progressive_lines: list[str] | None = None,
) -> None:
    skill_dir = tmp_path / "cases" / case_id / "skills" / "memory_projection"
    skill_dir.mkdir(parents=True)
    scopes = memory_scopes or ["case", "session", "npc_private", "scene_shared"]
    forbids = ["director_audit"] if forbidden_scopes is None else forbidden_scopes
    include_lines = [
        "include:",
        "  memory_types: [episodic, belief, relationship, strategy]",
        f"  memory_scopes: [{', '.join(scopes)}]",
        "  memory_layers: [core, working]",
    ]
    if topic_tags is not None:
        include_lines.append(f"  topic_tags: [{', '.join(topic_tags)}]")
    progressive = ["  progressive: []"] if progressive_lines is None else [
        "  progressive:",
        *progressive_lines,
    ]
    (skill_dir / f"{skill_id}.md").write_text(
        "\n".join(
            [
                "---",
                f"id: {skill_id}",
                "description: test override",
                "trigger:",
                "  action_type: talk",
                *include_lines,
                "forbid:",
                f"  memory_scopes: [{', '.join(forbids)}]",
                "  memory_layers: [archival]",
                "projection:",
                f"  max_memory_items: {max_memory_items}",
                f"  portrait_summary: {str(portrait_summary).lower()}",
                "  recent_events: true",
                "disclosure:",
                "  level: test",
                *progressive,
                "---",
                "test override",
            ]
        ),
        encoding="utf-8",
    )


def _add_snapshot(
    session: SessionState,
    *,
    memory_id: str,
    memory_type: str,
    memory_scope: str,
    memory_layer: str,
    content: str,
    topic_tags: list[str] | None = None,
) -> None:
    session.memory_snapshots[memory_id] = AgentMemorySnapshot(
        memory_id=memory_id,
        rule_id="test.memory_projection",
        memory_type=memory_type,  # type: ignore[arg-type]
        memory_scope=memory_scope,  # type: ignore[arg-type]
        memory_layer=memory_layer,  # type: ignore[arg-type]
        subject_id="player",
        owner_character_id=None,
        visible_to_character_ids=[],
        content=content,
        source_event_ids=["test_event"],
        salience=1.0,
        metadata={"topic_tags": topic_tags} if topic_tags is not None else {},
        last_updated_event_id="test_event",
    )
