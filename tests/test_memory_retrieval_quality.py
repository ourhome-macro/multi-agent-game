from __future__ import annotations

import json
from typing import Any

import pytest

from app.agents.context import build_agent_context
from app.agents.gateway import AgentGateway
from app.agents.llm_contract import build_llm_agent_input
from app.agents.loop import AgentLoop
from app.agents.memory import MemoryRetriever, build_local_semantic_embedding_scorer
from app.agents.memory_retrieval import EmbeddingScorer
from app.agents.real_llm_agent import OpenAILLMAgent
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
    CompressedHistoryContext,
    EventType,
    ForbiddenFactConfig,
    MemoryCandidateState,
    NarrativeState,
    PlayerAction,
    SceneConfig,
    SessionState,
    WorldEvent,
    WorldInfoConfig,
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


def test_retrieval_trace_reports_zero_reason_without_memory_content() -> None:
    hidden = _memory(
        memory_id="memory.quality.hidden.other_npc",
        content="SECRET HIDDEN MEMORY CONTENT",
        owner_character_id=SHEN,
        visible_to_character_ids=[SHEN],
        metadata={"clue_id": EMPTY_CAPSULES},
        salience=0.8,
    )
    session = _session([hidden])
    retriever = MemoryRetriever(max_results=10)

    memories = retriever.retrieve(
        case=_case(),
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text=EMPTY_CAPSULES),
        plan=_plan(max_memory_items=10),
    )

    diagnostics = retriever.last_retrieval_trace_summary
    assert memories == []
    assert diagnostics is not None
    assert diagnostics.zero_reason == "all_candidates_filtered"
    assert diagnostics.filter_counts["visible_to_target"] == 1
    assert diagnostics.total_snapshot_count == 1
    assert diagnostics.selected_count == 0
    serialized = repr(diagnostics)
    assert "SECRET HIDDEN MEMORY CONTENT" not in serialized
    assert hidden.memory_id not in serialized


def test_chain_expansion_recalls_linked_typed_memories_after_episodic_anchor() -> None:
    episodic = _memory(
        memory_id="memory.chain.anchor.event",
        content="Player created anchor_event with Jiang.",
        memory_type="episodic",
        metadata={},
        salience=0.6,
    )
    strategy = _memory(
        memory_id="memory.chain.linked.strategy",
        content="Jiang should deflect.",
        memory_type="strategy",
        source_memory_ids=[episodic.memory_id],
        metadata={
            "authority_source": "player_evidence",
            "strategy_id": "deflect_topic",
        },
        salience=0.1,
    )

    memories = _retrieve(
        [episodic, strategy],
        PlayerAction(type=ActionType.TALK, target_id=JIANG, text="anchor_event"),
        max_memory_items=10,
    )

    assert [memory.memory_id for memory in memories] == [
        episodic.memory_id,
        strategy.memory_id,
    ]


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
        metadata={"clue_id": EMPTY_CAPSULES},
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
        metadata={"clue_id": EMPTY_CAPSULES},
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


def test_default_semantic_scorer_recalls_synonym_without_external_dependency() -> None:
    relevant = _memory(
        memory_id="memory.quality.semantic.empty_capsules",
        content="Jiang believes the player is closing in on the medicine clue.",
        metadata={"topic_tags": ["medicine_replaced"]},
        salience=0.2,
    )
    unrelated = _memory(
        memory_id="memory.quality.semantic.unrelated",
        content="The player studied the seating chart and corridor route.",
        salience=1.0,
    )
    action = PlayerAction(
        type=ActionType.TALK,
        target_id=JIANG,
        text="继续追问药壳子是不是药箱里的东西",
    )

    default_memories = _retrieve([unrelated, relevant], action)
    semantic_memories = _retrieve(
        [unrelated, relevant],
        action,
        embedding_scorer=build_local_semantic_embedding_scorer(),
    )

    assert _memory_ids(default_memories) == [relevant.memory_id]
    assert _memory_ids(semantic_memories) == [relevant.memory_id]


@pytest.mark.parametrize(
    "query_text",
    [
        "继续追问药盒里留下的空壳",
        "ask about the empty medicine shells in the pill bottle",
    ],
)
def test_default_semantic_recall_golden_queries_handle_zh_en_rewrites(
    query_text: str,
) -> None:
    relevant = _memory(
        memory_id="memory.quality.golden.semantic.medicine_swap",
        content="Jiang tracks the player's pressure around heart prescription tampering.",
        metadata={"world_info_id": "heart_medicine_replaced"},
        salience=0.2,
    )
    unrelated = _memory(
        memory_id="memory.quality.golden.semantic.unrelated",
        content="The player studied the seating chart and corridor route.",
        salience=1.0,
    )

    memories = _retrieve(
        [unrelated, relevant],
        PlayerAction(type=ActionType.TALK, target_id=JIANG, text=query_text),
        case=_case_with_world_info(),
    )

    assert _memory_ids(memories) == [relevant.memory_id]


def test_default_semantic_world_info_query_expands_to_linked_clue_anchor() -> None:
    relevant = _memory(
        memory_id="memory.quality.golden.cross_anchor",
        content="Jiang deflects when the capsule shells come up.",
        metadata={"clue_id": EMPTY_CAPSULES},
        salience=0.2,
    )
    unrelated = _memory(
        memory_id="memory.quality.golden.cross_anchor.unrelated",
        content="Jiang remembers the corridor route argument.",
        salience=1.0,
    )

    memories = _retrieve(
        [unrelated, relevant],
        PlayerAction(
            type=ActionType.TALK,
            target_id=JIANG,
            text="Was the heart medicine swapped before dinner?",
        ),
        case=_case_with_world_info(),
    )

    assert _memory_ids(memories) == [relevant.memory_id]


def test_default_semantic_recall_does_not_select_wrong_case_anchor() -> None:
    lock_memory = _memory(
        memory_id="memory.quality.golden.lock_marks",
        content="Jiang noticed delayed scratches around the study lock.",
        metadata={"clue_id": DELAYED_LOCK_MARKS},
        salience=0.2,
    )
    medicine_memory = _memory(
        memory_id="memory.quality.golden.medicine.high_salience",
        content="Jiang tracks the heart prescription tampering thread.",
        metadata={"clue_id": EMPTY_CAPSULES},
        salience=1.0,
    )

    memories = _retrieve(
        [medicine_memory, lock_memory],
        PlayerAction(
            type=ActionType.TALK,
            target_id=JIANG,
            text="ask about delayed lock scratches",
        ),
        case=_case_with_world_info(),
    )

    assert _memory_ids(memories) == [lock_memory.memory_id]


def test_local_semantic_scorer_still_respects_hard_filters_before_scoring() -> None:
    visible = _memory(
        memory_id="memory.quality.semantic.visible",
        content="Jiang believes the player is closing in on the medicine clue.",
        metadata={"topic_tags": ["medicine_replaced"]},
        salience=0.2,
    )
    hidden_scope = _memory(
        memory_id="memory.quality.semantic.director_audit",
        content="Director audit mentions the medicine clue.",
        memory_scope="director_audit",
        owner_character_id=None,
        visible_to_character_ids=[],
        salience=1.0,
    )
    hidden_visibility = _memory(
        memory_id="memory.quality.semantic.shen_private",
        content="Shen remembers pressure around the medicine clue.",
        owner_character_id=SHEN,
        visible_to_character_ids=[SHEN],
        salience=1.0,
    )
    hidden_phase = _memory(
        memory_id="memory.quality.semantic.future_phase",
        content="Jiang links the medicine clue to a later reconstruction.",
        metadata={"phase_id": "reconstruction", "topic_tags": ["medicine_replaced"]},
        salience=1.0,
    )
    hidden_archival = _memory(
        memory_id="memory.quality.semantic.archival",
        content="Archived medicine clue summary.",
        memory_layer="archival",
        salience=1.0,
    )
    action = PlayerAction(
        type=ActionType.TALK,
        target_id=JIANG,
        text="药壳子和药箱这条线",
    )

    memories = _retrieve(
        [
            hidden_scope,
            hidden_visibility,
            hidden_phase,
            hidden_archival,
            visible,
        ],
        action,
        embedding_scorer=build_local_semantic_embedding_scorer(),
    )

    assert _memory_ids(memories) == [visible.memory_id]


def test_local_semantic_scorer_cannot_admit_forbidden_memory_to_context() -> None:
    forbidden = _memory(
        memory_id="memory.quality.semantic.forbidden_fact",
        content="玩家把药瓶线索直接连到未解锁真相：真凶是管家。",
        metadata={"topic_tags": ["medicine_replaced"]},
        salience=1.0,
    )
    visible = _memory(
        memory_id="memory.quality.semantic.safe",
        content="Jiang believes the player is closing in on the medicine clue.",
        metadata={"topic_tags": ["medicine_replaced"]},
        salience=0.2,
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
        [forbidden, visible],
        PlayerAction(type=ActionType.TALK, target_id=JIANG, text="药壳子和药箱"),
        case=case,
        embedding_scorer=build_local_semantic_embedding_scorer(),
    )

    assert _memory_ids(memories) == [visible.memory_id]


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


def test_llm_contract_uses_selected_memory_snapshots_as_only_memory_content_source() -> None:
    selected = _memory(
        memory_id="memory.quality.llm.selected",
        content="SELECTED_SAFE_MEMORY_CONTENT",
        salience=0.2,
    )
    session = _session_with_unselected_memory_surface(selected)
    context = build_agent_context(
        _case(),
        session,
        PlayerAction(type=ActionType.TALK, target_id=JIANG, text="anything"),
        retrieval_plan=_plan(max_memory_items=5, allow_recent_events=True),
        memory_snapshots=[selected],
    ).model_copy(
        update={
            "compressed_history": _compressed_history_for_test(selected.memory_id),
        }
    )

    raw_context = context.model_dump_json()
    assert "UNSELECTED_MEMORY_CANDIDATE_SECRET" in raw_context
    assert "UNSELECTED_RECENT_MEMORY_EVENT_SECRET" in raw_context
    assert "SELECTED_RECENT_MEMORY_EVENT_PAYLOAD" in raw_context

    contract = build_llm_agent_input(context)
    serialized_contract = contract.model_dump_json()

    assert contract.agent_context.memory_candidates == []
    assert "SELECTED_SAFE_MEMORY_CONTENT" in serialized_contract
    assert selected.memory_id in serialized_contract
    assert "UNSELECTED_MEMORY_CANDIDATE_SECRET" not in serialized_contract
    assert "UNSELECTED_RECENT_MEMORY_EVENT_SECRET" not in serialized_contract
    assert "SELECTED_RECENT_MEMORY_EVENT_PAYLOAD" not in serialized_contract
    assert "memory.quality.llm.unselected" not in serialized_contract
    assert contract.agent_context.compressed_history is not None
    assert contract.agent_context.compressed_history.important_memory_ids == [
        selected.memory_id
    ]


def test_openai_llm_request_payload_uses_sanitized_memory_projection() -> None:
    selected = _memory(
        memory_id="memory.quality.openai.selected",
        content="SELECTED_OPENAI_MEMORY_CONTENT",
        salience=0.2,
    )
    session = _session_with_unselected_memory_surface(selected)
    context = build_agent_context(
        _case(),
        session,
        PlayerAction(type=ActionType.TALK, target_id=JIANG, text="anything"),
        retrieval_plan=_plan(max_memory_items=5, allow_recent_events=True),
        memory_snapshots=[selected],
    ).model_copy(
        update={
            "compressed_history": _compressed_history_for_test(selected.memory_id),
        }
    )
    client = _RecordingOpenAIClient(
        {
            "output_text": json.dumps(
                {
                    "speech": "Within retrieval bounds.",
                    "intent": "answer",
                    "emotional_shift": {},
                    "proposed_actions": [],
                    "memory_refs": [selected.memory_id],
                    "disclosure_claims": [],
                }
            )
        }
    )

    intent = OpenAILLMAgent(
        api_key="test-key",
        model="test-model",
        client=client,
    ).generate(context)

    assert intent.memory_refs == [selected.memory_id]
    assert client.request_payload is not None
    serialized_request = json.dumps(client.request_payload, ensure_ascii=False)
    assert "SELECTED_OPENAI_MEMORY_CONTENT" in serialized_request
    assert selected.memory_id in serialized_request
    assert "UNSELECTED_MEMORY_CANDIDATE_SECRET" not in serialized_request
    assert "UNSELECTED_RECENT_MEMORY_EVENT_SECRET" not in serialized_request
    assert "SELECTED_RECENT_MEMORY_EVENT_PAYLOAD" not in serialized_request
    assert "memory.quality.llm.unselected" not in serialized_request


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


def test_archival_memory_is_cold_recalled_when_working_has_no_relevant_hit() -> None:
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

    assert _memory_ids(memories) == [archival.memory_id]


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
    embedding_scorer: EmbeddingScorer | None = None,
    max_memory_items: int = 20,
) -> list[AgentMemorySnapshot]:
    return MemoryRetriever(
        max_results=max_memory_items,
        embedding_scorer=embedding_scorer,
    ).retrieve(
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


def _case_with_world_info() -> CasePackage:
    return CasePackage(
        meta=CaseMeta(
            id=CASE_ID,
            title="Memory Retrieval Quality Case",
            initial_phase=PHASE,
        ),
        world_info=[
            WorldInfoConfig(
                id="heart_medicine_replaced",
                title="heart medicine replaced",
                description="The heart prescription was tampered with before dinner.",
                aliases=[
                    "heart medicine was swapped",
                    "prescription tampering",
                    "medicine replacement",
                    "心脏药被调包",
                    "心脏药调换",
                ],
                claim_patterns=[
                    "swapped heart medicine",
                    "replaced prescription",
                    "调包心脏药",
                ],
            )
        ],
        characters=[
            CharacterConfig(id=JIANG, display_name="Jiang", public_role="Doctor"),
            CharacterConfig(id=SHEN, display_name="Shen", public_role="Heir"),
        ],
        scenes=[SceneConfig(id="study", name="Study")],
        clues=[
            ClueConfig(
                id=EMPTY_CAPSULES,
                title="empty capsules",
                description="Empty capsule shells from the medicine box.",
                reveals_world_info=["heart_medicine_replaced"],
            ),
            ClueConfig(
                id=DELAYED_LOCK_MARKS,
                title="delayed lock marks",
                description="Scratch marks on the delayed study lock.",
            ),
        ],
    )


def _session(snapshots: list[AgentMemorySnapshot]) -> SessionState:
    return SessionState(
        id="session.memory_retrieval_quality",
        case_id=CASE_ID,
        narrative=NarrativeState(phase=PHASE),
        relationships={},
        memory_snapshots={snapshot.memory_id: snapshot for snapshot in snapshots},
    )


def _session_with_unselected_memory_surface(
    selected: AgentMemorySnapshot,
) -> SessionState:
    session = _session([selected])
    unselected_memory_id = "memory.quality.llm.unselected"
    session.memory_candidates[unselected_memory_id] = MemoryCandidateState(
        memory_id=unselected_memory_id,
        rule_id="memory_rule.test.llm_hardening.v1",
        memory_type="episodic",
        memory_scope="npc_private",
        memory_layer="working",
        subject_id="player",
        owner_character_id=JIANG,
        visible_to_character_ids=[JIANG],
        content="UNSELECTED_MEMORY_CANDIDATE_SECRET",
        source_event_id="event.unselected.candidate.source",
        source_event_ids=["event.unselected.candidate.source"],
        salience=0.99,
    )
    session.events.extend(
        [
            _memory_event(
                event_id="event.unselected.memory_candidate",
                event_type=EventType.MEMORY_CANDIDATE_CREATED,
                memory_id=unselected_memory_id,
                content="UNSELECTED_RECENT_MEMORY_EVENT_SECRET",
            ),
            _memory_event(
                event_id="event.selected.memory_snapshot",
                event_type=EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
                memory_id=selected.memory_id,
                content="SELECTED_RECENT_MEMORY_EVENT_PAYLOAD",
            ),
        ]
    )
    session.events.append(
        WorldEvent(
            id="event.regular.visible",
            case_id=CASE_ID,
            session_id=session.id,
            actor_id="player",
            type=EventType.PLAYER_TALKED,
            payload={"target_id": JIANG, "text": "regular event remains visible"},
            created_at="2026-06-10T09:00:00Z",
        )
    )
    return session


def _compressed_history_for_test(selected_memory_id: str) -> CompressedHistoryContext:
    return CompressedHistoryContext(
        summary="UNSELECTED_MEMORY_CANDIDATE_SECRET was compressed here.",
        important_event_ids=[
            "event.unselected.memory_candidate",
            "event.selected.memory_snapshot",
            "event.regular.visible",
        ],
        important_memory_ids=["memory.quality.llm.unselected", selected_memory_id],
        open_threads=["UNSELECTED_RECENT_MEMORY_EVENT_SECRET"],
        risk_notes=["SELECTED_RECENT_MEMORY_EVENT_PAYLOAD"],
    )


def _memory_event(
    *,
    event_id: str,
    event_type: EventType,
    memory_id: str,
    content: str,
) -> WorldEvent:
    return WorldEvent(
        id=event_id,
        case_id=CASE_ID,
        session_id="session.memory_retrieval_quality",
        actor_id="memory_derivation",
        type=event_type,
        payload={
            "memory_id": memory_id,
            "rule_id": "memory_rule.test.llm_hardening.v1",
            "memory_type": "episodic",
            "memory_scope": "npc_private",
            "memory_layer": "working",
            "subject_id": "player",
            "owner_character_id": JIANG,
            "visible_to_character_ids": [JIANG],
            "content": content,
            "source_event_id": f"source.{event_id}",
            "source_event_ids": [f"source.{event_id}"],
            "salience": 0.9,
            "confidence": 1.0,
        },
        created_at="2026-06-10T09:00:00Z",
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


def _plan(
    *,
    max_memory_items: int,
    allow_recent_events: bool = False,
) -> MemoryRetrievalPlan:
    return MemoryRetrievalPlan(
        skill_id="test.memory_retrieval_quality",
        included_memory_types=("episodic", "belief", "relationship", "strategy"),
        included_scopes=("case", "session", "npc_private", "scene_shared"),
        included_layers=("core", "working"),
        forbidden_scopes=("director_audit",),
        forbidden_layers=("archival",),
        max_memory_items=max_memory_items,
        inject_portrait_summary=False,
        allow_recent_events=allow_recent_events,
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


class _RecordingOpenAIResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _RecordingOpenAIClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._response = _RecordingOpenAIResponse(payload)
        self.request_payload: dict[str, Any] | None = None

    def post(self, _url: str, **kwargs: Any) -> _RecordingOpenAIResponse:
        request_payload = kwargs.get("json")
        if isinstance(request_payload, dict):
            self.request_payload = request_payload
        return self._response
