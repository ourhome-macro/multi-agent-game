from __future__ import annotations

import pytest

from app.agents.context import build_agent_context
from app.agents.gateway import AgentGateway
from app.agents.loop import AgentLoop
from app.agents.memory import MemoryRetriever
from app.agents.retrieval_planner import MemoryRetrievalPlan
from app.domain.models import (
    ActionType,
    AgentContext,
    AgentIntent,
    AgentIntentType,
    AgentMemorySnapshot,
    CaseMeta,
    CasePackage,
    CharacterConfig,
    ClueConfig,
    ForbiddenFactConfig,
    NarrativeState,
    PlayerAction,
    SceneConfig,
    SessionState,
)

CASE_ID = "memory_retrieval_quality"
PHASE = "opening"

JIANG = "jiang_yanhui"
SHEN = "shen_zhaoye"
EMPTY_CAPSULES = "empty_capsules"
DELAYED_LOCK_MARKS = "delayed_lock_marks"

OLD_TS = "2026-06-01T09:00:00Z"
NEW_TS = "2026-06-10T09:00:00Z"


class QuietAgent:
    def __init__(self) -> None:
        self.contexts: list[AgentContext] = []

    def generate(self, context: AgentContext) -> AgentIntent:
        self.contexts.append(context)
        return AgentIntent(
            speech="Within retrieval bounds.",
            intent=AgentIntentType.ANSWER,
            proposed_actions=[],
        )


class RecordingRetriever(MemoryRetriever):
    def __init__(self, memories: list[AgentMemorySnapshot]) -> None:
        self.memories = memories
        self.calls: list[dict[str, object]] = []

    def retrieve(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
        plan: MemoryRetrievalPlan | None = None,
    ) -> list[AgentMemorySnapshot]:
        self.calls.append(
            {
                "case_id": case.meta.id,
                "session_id": session.id,
                "target_id": action.target_id,
                "plan": plan,
            }
        )
        return list(self.memories)


def test_chinese_query_ranks_relevant_memory_above_unrelated_high_salience() -> None:
    relevant = _memory(
        memory_id="memory.quality.relevant.zh.empty_capsules",
        content="玩家追问了空胶囊的来源，江彦回明显回避药箱细节。",
        salience=0.25,
    )
    unrelated = _memory(
        memory_id="memory.quality.unrelated.high_salience",
        content="玩家多次追问遗嘱和座位表，管家对此非常紧张。",
        salience=0.95,
    )

    memories = _retrieve(
        [unrelated, relevant],
        PlayerAction(type=ActionType.TALK, target_id=JIANG, text="空胶囊"),
    )

    _assert_selected_before_or_without_unrelated(
        _memory_ids(memories),
        relevant.memory_id,
        unrelated.memory_id,
    )


@pytest.mark.parametrize(
    ("action", "relevant_kwargs"),
    [
        (
            PlayerAction(
                type=ActionType.ASK_ABOUT,
                target_id=JIANG,
                subject_type="clue",
                subject_id=EMPTY_CAPSULES,
                text="继续问胶囊",
            ),
            {
                "memory_id": "memory.quality.metadata.clue_match",
                "content": "江彦回对医药话题产生防御性反应。",
                "metadata": {"clue_id": EMPTY_CAPSULES},
                "salience": 0.20,
            },
        ),
        (
            PlayerAction(
                type=ActionType.PRESENT_CLUE,
                target_id=JIANG,
                clue_id=EMPTY_CAPSULES,
                text="出示证物",
            ),
            {
                "memory_id": "memory.quality.source_memory.clue_match",
                "content": "江彦回因为玩家出示某个证物而降低信任。",
                "source_memory_ids": [
                    f"memory.player.presented_clue.{JIANG}.{EMPTY_CAPSULES}",
                ],
                "salience": 0.20,
            },
        ),
        (
            PlayerAction(
                type=ActionType.ACCUSE,
                target_id=JIANG,
                claim_id="claim.medical_coverup",
                evidence_clue_ids=[EMPTY_CAPSULES],
                text="用证据质询",
            ),
            {
                "memory_id": f"memory.quality.memory_id.{EMPTY_CAPSULES}",
                "content": "玩家把一个关键物证串进了指控链。",
                "salience": 0.20,
            },
        ),
    ],
)
def test_structured_action_fields_prioritize_structured_memory_hits(
    action: PlayerAction,
    relevant_kwargs: dict[str, object],
) -> None:
    relevant = _memory(**relevant_kwargs)
    unrelated = _memory(
        memory_id="memory.quality.unrelated.very_high_salience",
        content="玩家对钟表、遗嘱和走廊动线进行了密集追问。",
        salience=0.95,
    )

    memories = _retrieve([unrelated, relevant], action)

    _assert_selected_before_or_without_unrelated(
        _memory_ids(memories),
        relevant.memory_id,
        unrelated.memory_id,
    )


def test_recency_prefers_newer_relevant_memory_over_staler_slightly_higher_salience() -> None:
    stale = _memory(
        memory_id=f"memory.quality.stale.{EMPTY_CAPSULES}",
        content="玩家很早以前问过空胶囊，江彦回当时只是敷衍。",
        salience=0.62,
        updated_at=OLD_TS,
    )
    recent = _memory(
        memory_id=f"memory.quality.recent.{EMPTY_CAPSULES}",
        content="玩家刚刚追问空胶囊，江彦回开始回避药瓶去向。",
        salience=0.58,
        updated_at=NEW_TS,
    )

    memories = _retrieve(
        [stale, recent],
        PlayerAction(
            type=ActionType.ASK_ABOUT,
            target_id=JIANG,
            subject_type="clue",
            subject_id=EMPTY_CAPSULES,
            text="空胶囊",
        ),
    )

    _assert_before(_memory_ids(memories), recent.memory_id, stale.memory_id)


def test_reinforcement_prefers_snapshot_with_more_source_events() -> None:
    reinforced = _memory(
        memory_id=f"memory.quality.aa_reinforced.{EMPTY_CAPSULES}",
        content="玩家多次把空胶囊和江彦回的医药压力联系起来。",
        salience=0.50,
        source_event_ids=["event.1", "event.2", "event.3"],
        updated_at=NEW_TS,
    )
    sparse = _memory(
        memory_id=f"memory.quality.zz_sparse.{EMPTY_CAPSULES}",
        content="玩家一次提到空胶囊。",
        salience=0.50,
        source_event_ids=["event.4"],
        updated_at=NEW_TS,
    )

    memories = _retrieve(
        [reinforced, sparse],
        PlayerAction(
            type=ActionType.ASK_ABOUT,
            target_id=JIANG,
            subject_type="clue",
            subject_id=EMPTY_CAPSULES,
            text="空胶囊",
        ),
    )

    _assert_before(_memory_ids(memories), reinforced.memory_id, sparse.memory_id)


def test_plan_max_memory_items_applies_after_quality_sorting() -> None:
    primary = _memory(
        memory_id="memory.quality.max.primary",
        content="空胶囊让江彦回暴露出对药箱的异常防御。",
        salience=0.30,
    )
    secondary = _memory(
        memory_id="memory.quality.max.secondary",
        content="空胶囊和缺失药片共同指向医药线索。",
        salience=0.25,
    )
    unrelated = _memory(
        memory_id="memory.quality.max.unrelated_high_salience",
        content="玩家确认了大厅座位表，管家对此记忆深刻。",
        salience=0.99,
    )
    plan = _plan(max_memory_items=2)

    memories = _retrieve(
        [unrelated, secondary, primary],
        PlayerAction(type=ActionType.TALK, target_id=JIANG, text="空胶囊"),
        plan=plan,
    )

    assert _memory_ids(memories) == [primary.memory_id, secondary.memory_id]


def test_build_agent_context_applies_quality_sorting_before_snapshot_truncation() -> None:
    primary = _memory(
        memory_id="memory.quality.context.zz_primary",
        content="空胶囊让江彦回暴露出对药箱的异常防御。",
        salience=0.30,
    )
    secondary = _memory(
        memory_id="memory.quality.context.zz_secondary",
        content="空胶囊和缺失药片共同指向医药线索。",
        salience=0.25,
    )
    unrelated = _memory(
        memory_id="memory.quality.context.aa_unrelated_high_salience",
        content="玩家确认了大厅座位表，管家对此记忆深刻。",
        salience=0.99,
    )
    action = PlayerAction(type=ActionType.TALK, target_id=JIANG, text="空胶囊")

    context = build_agent_context(
        _case(),
        _session([unrelated, secondary, primary]),
        action,
        retrieval_plan=_plan(max_memory_items=2),
    )

    assert _memory_ids(context.memory_snapshots) == [primary.memory_id, secondary.memory_id]


def test_build_agent_context_uses_supplied_memory_snapshots_without_fallback_retrieve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supplied = [
        _memory(
            memory_id="memory.quality.supplied.snapshot",
            content="Caller supplied this already retrieved memory.",
            salience=0.1,
        )
    ]

    def fail_if_constructed(*args: object, **kwargs: object) -> object:
        _ = args, kwargs
        raise AssertionError("build_agent_context should not construct a fallback retriever")

    monkeypatch.setattr("app.agents.context.MemoryRetriever", fail_if_constructed)

    context = build_agent_context(
        _case(),
        _session([]),
        PlayerAction(type=ActionType.TALK, target_id=JIANG, text="anything"),
        retrieval_plan=_plan(max_memory_items=1),
        memory_snapshots=supplied,
    )

    assert context.memory_snapshots == supplied


def test_build_agent_context_fallback_retrieval_still_works_without_supplied_snapshots() -> None:
    relevant = _memory(
        memory_id="memory.quality.fallback.empty_capsules",
        content="空胶囊让江彦回暴露出对药箱的异常防御。",
        salience=0.2,
    )
    unrelated = _memory(
        memory_id="memory.quality.fallback.unrelated_high_salience",
        content="玩家确认了大厅座位表，管家对此记忆深刻。",
        salience=0.99,
    )

    context = build_agent_context(
        _case(),
        _session([unrelated, relevant]),
        PlayerAction(type=ActionType.TALK, target_id=JIANG, text="空胶囊"),
        retrieval_plan=_plan(max_memory_items=1),
    )

    assert _memory_ids(context.memory_snapshots) == [relevant.memory_id]


def test_agent_loop_uses_injected_retriever_as_single_context_and_trace_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = [
        _memory(
            memory_id="memory.quality.loop.selected",
            content="Injected retriever selected this memory.",
            salience=0.2,
        )
    ]
    retriever = RecordingRetriever(selected)
    agent = QuietAgent()

    def fail_if_constructed(*args: object, **kwargs: object) -> object:
        _ = args, kwargs
        raise AssertionError("AgentLoop should pass retrieved snapshots into context")

    monkeypatch.setattr("app.agents.context.MemoryRetriever", fail_if_constructed)

    turn = AgentLoop(
        agent_gateway=AgentGateway(mock_agent=agent),
        memory_retriever=retriever,
    ).run_turn(
        case=_case(),
        session=_session([]),
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="anything"),
    )

    assert len(retriever.calls) == 1
    assert turn.context.memory_snapshots == selected
    assert agent.contexts[0].memory_snapshots == selected
    assert turn.memory_ids_used == [selected[0].memory_id]
    assert turn.trace.memory_ids_used == [selected[0].memory_id]
    assert turn.trace.memory_projection["selected_count"] == 1
    assert turn.trace.memory_projection["items"][0]["memory_id"] == selected[0].memory_id
    assert turn.trace.tool_calls[0]["result_count"] == 1


def test_director_audit_stays_out_of_regular_retrieve_but_director_can_see_it() -> None:
    audit = _memory(
        memory_id="memory.quality.director_audit.blocked_output",
        content="director blocked jiang_yanhui output for leaking locked facts.",
        memory_scope="director_audit",
        owner_character_id=None,
        visible_to_character_ids=[],
        salience=0.80,
    )
    session = _session([audit])
    case = _case()
    action = PlayerAction(
        type=ActionType.TALK,
        target_id=JIANG,
        text="director blocked jiang_yanhui",
    )

    npc_memories = MemoryRetriever(max_results=20).retrieve(
        case=case,
        session=session,
        action=action,
    )
    director_memories = MemoryRetriever(max_results=20).retrieve_for_director(
        case=case,
        session=session,
        action=action,
    )

    assert audit.memory_id not in _memory_ids(npc_memories)
    assert audit.memory_id in _memory_ids(director_memories)


def test_archival_memory_remains_unavailable_by_default() -> None:
    archival = _memory(
        memory_id=f"memory.quality.archival.{EMPTY_CAPSULES}",
        content="空胶囊的旧归档总结。",
        memory_layer="archival",
        salience=1.0,
    )

    memories = _retrieve(
        [archival],
        PlayerAction(type=ActionType.TALK, target_id=JIANG, text="空胶囊"),
    )

    assert archival.memory_id not in _memory_ids(memories)


def test_forbidden_fact_content_is_not_retrieved_even_when_chinese_query_matches() -> None:
    forbidden = _memory(
        memory_id="memory.quality.forbidden_fact",
        content="玩家听见了未解锁真相：真凶是管家。",
        salience=1.0,
    )
    case = _case(
        forbidden_facts=[
            ForbiddenFactConfig(
                id="fact.killer_identity",
                text="真凶是管家",
                blocked_terms=["真凶是管家", "管家下毒"],
            ),
        ],
    )

    memories = _retrieve(
        [forbidden],
        PlayerAction(type=ActionType.TALK, target_id=JIANG, text="真凶是管家"),
        case=case,
    )

    assert forbidden.memory_id not in _memory_ids(memories)


def _retrieve(
    snapshots: list[AgentMemorySnapshot],
    action: PlayerAction,
    *,
    case: CasePackage | None = None,
    plan: MemoryRetrievalPlan | None = None,
) -> list[AgentMemorySnapshot]:
    return MemoryRetriever(max_results=20).retrieve(
        case=case or _case(),
        session=_session(snapshots),
        action=action,
        plan=plan,
    )


def _case(
    *,
    forbidden_facts: list[ForbiddenFactConfig] | None = None,
) -> CasePackage:
    return CasePackage(
        meta=CaseMeta(
            id=CASE_ID,
            title="Memory Retrieval Quality Case",
            initial_phase=PHASE,
        ),
        characters=[
            CharacterConfig(id=JIANG, display_name="江彦回", public_role="医生"),
            CharacterConfig(id=SHEN, display_name="沈照夜", public_role="继承人"),
        ],
        scenes=[SceneConfig(id="study", name="书房")],
        clues=[
            ClueConfig(
                id=EMPTY_CAPSULES,
                title="空胶囊",
                description="药箱里缺少药粉的空胶囊。",
            ),
            ClueConfig(
                id=DELAYED_LOCK_MARKS,
                title="延迟锁痕",
                description="书房门锁上可疑的延迟锁痕。",
            ),
        ],
        forbidden_facts=forbidden_facts or [],
    )


def _session(snapshots: list[AgentMemorySnapshot]) -> SessionState:
    return SessionState(
        id="session.memory_retrieval_quality",
        case_id=CASE_ID,
        narrative=NarrativeState(phase=PHASE),
        relationships={},
        memory_snapshots={snapshot.memory_id: snapshot for snapshot in snapshots},
    )


def _memory(
    *,
    memory_id: str,
    content: str,
    salience: float,
    memory_type: str = "episodic",
    memory_scope: str = "npc_private",
    memory_layer: str = "working",
    owner_character_id: str | None = JIANG,
    visible_to_character_ids: list[str] | None = None,
    source_event_ids: list[str] | None = None,
    source_memory_ids: list[str] | None = None,
    metadata: dict[str, object] | None = None,
    updated_at: str = NEW_TS,
) -> AgentMemorySnapshot:
    event_ids = source_event_ids or [f"event.{memory_id}"]
    return AgentMemorySnapshot(
        memory_id=memory_id,
        memory_type=memory_type,
        memory_scope=memory_scope,
        memory_layer=memory_layer,
        subject_id="player",
        owner_character_id=owner_character_id,
        visible_to_character_ids=(
            [JIANG] if visible_to_character_ids is None else visible_to_character_ids
        ),
        content=content,
        source_event_ids=event_ids,
        source_memory_ids=source_memory_ids or [],
        salience=salience,
        confidence=1.0,
        metadata=metadata or {},
        last_updated_event_id=event_ids[-1],
        created_at=event_ids[0],
        updated_at=updated_at,
    )


def _plan(*, max_memory_items: int) -> MemoryRetrievalPlan:
    return MemoryRetrievalPlan(
        skill_id="test.memory_retrieval_quality",
        included_memory_types=("episodic", "belief", "relationship", "strategy"),
        included_scopes=("case", "session", "npc_private", "scene_shared"),
        included_layers=("core", "working"),
        forbidden_scopes=("director_audit",),
        forbidden_layers=("archival",),
        max_memory_items=max_memory_items,
        inject_portrait_summary=False,
        allow_recent_events=False,
    )


def _memory_ids(memories: list[AgentMemorySnapshot]) -> list[str]:
    return [memory.memory_id for memory in memories]


def _assert_before(memory_ids: list[str], expected_first: str, expected_later: str) -> None:
    assert expected_first in memory_ids
    assert expected_later in memory_ids
    assert memory_ids.index(expected_first) < memory_ids.index(expected_later)


def _assert_selected_before_or_without_unrelated(
    memory_ids: list[str],
    expected_relevant: str,
    unrelated: str,
) -> None:
    assert expected_relevant in memory_ids
    if unrelated in memory_ids:
        assert memory_ids.index(expected_relevant) < memory_ids.index(unrelated)
