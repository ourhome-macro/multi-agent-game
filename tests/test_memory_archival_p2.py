from __future__ import annotations

from pathlib import Path

from app.agents.context import build_agent_context
from app.agents.memory import MemoryRetriever
from app.agents.retrieval_planner import MemoryRetrievalPlan
from app.cases.loader import CaseLoader
from app.domain.models import (
    ActionType,
    AgentMemorySnapshot,
    EventType,
    ForbiddenFactConfig,
    NarrativeState,
    PlayerAction,
    SessionState,
    WorldEvent,
)
from app.runtime.events import EventRecorder
from app.runtime.memory_archival import MemoryArchivalSystem
from app.runtime.replay import replay_events
from app.runtime.service import create_runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "mist_clock_manor"

JIANG = "jiang_yanhui"
SHEN = "shen_zhaoye"
EMPTY_CAPSULES = "empty_capsules"

STALE_TS = "2026-05-01T09:00:00Z"
RECENT_TS = "2026-06-13T09:00:00Z"
AS_OF_TS = "2026-06-14T09:00:00Z"


def test_archival_system_archives_only_stale_unreinforced_working_memories() -> None:
    case = CaseLoader().load(CASE_DIR)
    session = _session(case.meta.id)
    archive_target = _snapshot(
        "memory.player.presented_clue.jiang_yanhui.empty_capsules",
        content="Player pressured Jiang about empty_capsules.",
        updated_at=STALE_TS,
        source_event_ids=["event.old.once"],
    )
    recent = _snapshot(
        "memory.player.recent.empty_capsules",
        content="Recent empty_capsules working memory.",
        updated_at=RECENT_TS,
        source_event_ids=["event.recent.once"],
    )
    reinforced = _snapshot(
        "memory.player.reinforced.empty_capsules",
        content="Repeated empty_capsules pressure.",
        updated_at=STALE_TS,
        source_event_ids=["event.old.1", "event.old.2"],
    )
    case_core = _snapshot(
        "memory.player.clue_discovered.empty_capsules",
        content="Player discovered empty_capsules.",
        memory_scope="case",
        memory_layer="core",
        owner_character_id=None,
        visible_to_character_ids=[JIANG, SHEN],
        updated_at=STALE_TS,
        source_event_ids=["event.core.once"],
    )
    director_audit = _snapshot(
        "memory.player.director_blocked.jiang_yanhui.fact",
        content="Director blocked unsafe speech.",
        memory_scope="director_audit",
        owner_character_id=None,
        visible_to_character_ids=[],
        updated_at=STALE_TS,
        source_event_ids=["event.audit.once"],
    )
    for snapshot in [archive_target, recent, reinforced, case_core, director_audit]:
        session.memory_snapshots[snapshot.memory_id] = snapshot
        _append_snapshot_event(session, snapshot)
    _append_clock_event(session, AS_OF_TS)

    events = MemoryArchivalSystem(EventRecorder()).apply(
        session=session,
        caused_by_event_id="event.clock",
    )
    second_pass = MemoryArchivalSystem(EventRecorder()).apply(
        session=session,
        caused_by_event_id="event.clock",
    )

    assert [event.payload["memory_id"] for event in events] == [
        archive_target.memory_id
    ]
    assert events[0].type == EventType.AGENT_MEMORY_SNAPSHOT_UPDATED
    assert events[0].payload["operation"] == "archived"
    assert events[0].payload["memory_layer"] == "archival"
    assert session.memory_snapshots[archive_target.memory_id].memory_layer == "archival"
    assert session.memory_snapshots[recent.memory_id].memory_layer == "working"
    assert session.memory_snapshots[reinforced.memory_id].memory_layer == "working"
    assert session.memory_snapshots[case_core.memory_id].memory_layer == "core"
    assert session.memory_snapshots[director_audit.memory_id].memory_layer == "working"
    assert second_pass == []

    replayed = replay_events(case, session.events)
    assert replayed.memory_snapshots[archive_target.memory_id].memory_layer == "archival"
    assert replayed.memory_snapshots[recent.memory_id].memory_layer == "working"


def test_cold_recall_uses_archival_only_when_working_has_no_relevant_hit() -> None:
    case = CaseLoader().load(CASE_DIR)
    action = _talk_action("empty_capsules")
    relevant_working = _snapshot(
        "memory.player.working.empty_capsules",
        content="Working memory mentions empty_capsules.",
        salience=0.2,
    )
    relevant_archival = _snapshot(
        "memory.player.archival.empty_capsules",
        content="Archival memory mentions empty_capsules.",
        memory_layer="archival",
        salience=1.0,
    )
    unrelated_working = _snapshot(
        "memory.player.working.unrelated.high_salience",
        content="Unrelated high salience memory about seating.",
        salience=1.0,
    )

    with_working_hit = _retrieve(
        case,
        [relevant_working, relevant_archival],
        action,
    )
    cold_recalled = _retrieve(
        case,
        [unrelated_working, relevant_archival],
        action,
    )

    assert _memory_ids(with_working_hit) == [relevant_working.memory_id]
    assert _memory_ids(cold_recalled) == [relevant_archival.memory_id]


def test_cold_recall_keeps_visibility_scope_and_forbidden_fact_boundaries() -> None:
    base_case = CaseLoader().load(CASE_DIR)
    forbidden_case = base_case.model_copy(
        update={
            "forbidden_facts": [
                ForbiddenFactConfig(
                    id="fact.archival.secret",
                    world_info_id="world.secret",
                    text="locked archival truth",
                    blocked_terms=["locked archival truth"],
                    reveal_phase="resolved",
                )
            ]
        }
    )
    jiang_private = _snapshot(
        "memory.player.archival.jiang.empty_capsules",
        content="Jiang archival empty_capsules memory.",
        memory_layer="archival",
        owner_character_id=JIANG,
        visible_to_character_ids=[JIANG],
    )
    shen_private = _snapshot(
        "memory.player.archival.shen.empty_capsules",
        content="Shen archival empty_capsules memory.",
        memory_layer="archival",
        owner_character_id=SHEN,
        visible_to_character_ids=[SHEN],
    )
    forbidden = _snapshot(
        "memory.player.archival.forbidden.empty_capsules",
        content="empty_capsules points to locked archival truth.",
        memory_layer="archival",
        owner_character_id=JIANG,
        visible_to_character_ids=[JIANG],
        salience=1.0,
    )
    unrelated_archival = _snapshot(
        "memory.player.archival.unrelated",
        content="Archival seating chart memory.",
        memory_layer="archival",
        owner_character_id=JIANG,
        visible_to_character_ids=[JIANG],
        salience=1.0,
    )

    jiang_memories = _retrieve(
        forbidden_case,
        [jiang_private, shen_private, forbidden, unrelated_archival],
        _talk_action("empty_capsules"),
    )
    shen_memories = _retrieve(
        forbidden_case,
        [jiang_private, shen_private],
        PlayerAction(type=ActionType.TALK, target_id=SHEN, text="empty_capsules"),
    )
    unrelated_query = _retrieve(
        forbidden_case,
        [unrelated_archival],
        _talk_action("empty_capsules"),
    )

    assert _memory_ids(jiang_memories) == [jiang_private.memory_id]
    assert _memory_ids(shen_memories) == [shen_private.memory_id]
    assert unrelated_query == []


def test_runtime_archives_before_agent_retrieval_and_allows_cold_recall() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case])
    session = runtime.session_store.create(case)
    stale = _snapshot(
        "memory.player.runtime.empty_capsules",
        content="Runtime stale working memory mentions empty_capsules.",
        updated_at=STALE_TS,
        source_event_ids=["event.runtime.once"],
    )
    session.memory_snapshots[stale.memory_id] = stale

    response = runtime.action_service.handle(
        session=session,
        action=_talk_action("empty_capsules"),
    )
    context = runtime.action_service.agent_loop.build_context(
        case=case,
        session=session,
        action=_talk_action("empty_capsules"),
    )

    archival_events = [
        event
        for event in response.new_events
        if event.type == EventType.AGENT_MEMORY_SNAPSHOT_UPDATED
        and event.payload.get("operation") == "archived"
    ]
    assert [event.payload["memory_id"] for event in archival_events] == [
        stale.memory_id
    ]
    assert session.memory_snapshots[stale.memory_id].memory_layer == "archival"
    assert _memory_ids(context.memory_snapshots) == [stale.memory_id]


def test_build_agent_context_can_project_cold_recalled_archival_memory() -> None:
    case = CaseLoader().load(CASE_DIR)
    session = _session(case.meta.id)
    archival = _snapshot(
        "memory.player.context.empty_capsules",
        content="Context archival memory mentions empty_capsules.",
        memory_layer="archival",
    )
    session.memory_snapshots[archival.memory_id] = archival

    context = build_agent_context(case, session, _talk_action("empty_capsules"))

    assert _memory_ids(context.memory_snapshots) == [archival.memory_id]


def _retrieve(
    case: object,
    snapshots: list[AgentMemorySnapshot],
    action: PlayerAction,
) -> list[AgentMemorySnapshot]:
    session = _session(case.meta.id)
    session.memory_snapshots = {snapshot.memory_id: snapshot for snapshot in snapshots}
    return MemoryRetriever(max_results=10).retrieve(
        case=case,
        session=session,
        action=action,
        plan=_plan(),
    )


def _snapshot(
    memory_id: str,
    *,
    content: str,
    memory_scope: str = "npc_private",
    memory_layer: str = "working",
    owner_character_id: str | None = JIANG,
    visible_to_character_ids: list[str] | None = None,
    salience: float = 0.8,
    source_event_ids: list[str] | None = None,
    updated_at: str = RECENT_TS,
) -> AgentMemorySnapshot:
    return AgentMemorySnapshot(
        memory_id=memory_id,
        rule_id="memory_rule.test.p2.v1",
        memory_type="episodic",
        memory_scope=memory_scope,
        memory_layer=memory_layer,
        subject_id="player",
        owner_character_id=owner_character_id,
        visible_to_character_ids=visible_to_character_ids or [JIANG],
        content=content,
        source_event_ids=source_event_ids or [f"source.{memory_id}"],
        source_memory_ids=[],
        salience=salience,
        confidence=1.0,
        visibility="private",
        metadata={},
        last_updated_event_id=f"snapshot.{memory_id}",
        created_at=updated_at,
        updated_at=updated_at,
    )


def _session(case_id: str) -> SessionState:
    return SessionState(
        id="session.memory_archival_p2",
        case_id=case_id,
        narrative=NarrativeState(phase="opening"),
        relationships={},
    )


def _append_clock_event(session: SessionState, created_at: str) -> None:
    session.events.append(
        WorldEvent(
            id="event.clock",
            case_id=session.case_id,
            session_id=session.id,
            actor_id="test",
            type=EventType.PLAYER_TALKED,
            payload={"target_id": JIANG, "text": "clock"},
            created_at=created_at,
        )
    )


def _append_snapshot_event(session: SessionState, snapshot: AgentMemorySnapshot) -> None:
    session.events.append(
        WorldEvent(
            id=f"seed.{snapshot.memory_id}",
            case_id=session.case_id,
            session_id=session.id,
            actor_id="test",
            type=EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
            payload={
                "memory_id": snapshot.memory_id,
                "rule_id": snapshot.rule_id,
                "memory_type": snapshot.memory_type,
                "memory_scope": snapshot.memory_scope,
                "memory_layer": snapshot.memory_layer,
                "subject_id": snapshot.subject_id,
                "owner_character_id": snapshot.owner_character_id,
                "visible_to_character_ids": snapshot.visible_to_character_ids,
                "content": snapshot.content,
                "source_event_ids": snapshot.source_event_ids,
                "source_memory_ids": snapshot.source_memory_ids,
                "salience": snapshot.salience,
                "confidence": snapshot.confidence,
                "visibility": snapshot.visibility,
                "metadata": snapshot.metadata,
                "operation": "seeded",
            },
            created_at=snapshot.updated_at or snapshot.created_at or STALE_TS,
        )
    )


def _talk_action(text: str) -> PlayerAction:
    return PlayerAction(type=ActionType.TALK, target_id=JIANG, text=text)


def _plan() -> MemoryRetrievalPlan:
    return MemoryRetrievalPlan(
        skill_id="test.archival_p2",
        included_memory_types=("episodic", "belief", "relationship", "strategy"),
        included_scopes=("case", "session", "npc_private", "scene_shared"),
        included_layers=("core", "working"),
        forbidden_scopes=("director_audit",),
        forbidden_layers=("archival",),
        max_memory_items=10,
        inject_portrait_summary=False,
        allow_recent_events=False,
    )


def _memory_ids(memories: list[object]) -> list[str]:
    return [str(memory.memory_id) for memory in memories]
