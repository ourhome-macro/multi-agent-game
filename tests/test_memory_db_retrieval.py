from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

from app.agents.gateway import AgentGateway
from app.agents.loop import AgentLoop
from app.agents.memory import InMemoryMemoryStore, MemoryRetriever, MemoryStoreQuery
from app.agents.retrieval_planner import MemoryRetrievalPlan
from app.domain.models import (
    ActionType,
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
from app.runtime.tracing import RuntimeTracer
from app.storage.postgres import PostgresMemoryStore

CASE_ID = "case.memory_db_retrieval"
SESSION_ID = "session.memory_db_retrieval"
PHASE = "opening"
JIANG = "jiang_yanhui"
SHEN = "shen_zhaoye"


class RecordingMemoryStore(InMemoryMemoryStore):
    def __init__(self) -> None:
        self.queries: list[MemoryStoreQuery] = []

    def fetch_candidates(
        self,
        *,
        session: SessionState,
        query: MemoryStoreQuery,
    ) -> list[AgentMemorySnapshot]:
        self.queries.append(query)
        return super().fetch_candidates(session=session, query=query)


class QueryPrefilteringMemoryStore(InMemoryMemoryStore):
    backend_name = "query_prefiltering_test"

    def __init__(self) -> None:
        self.queries: list[MemoryStoreQuery] = []

    def fetch_candidates(
        self,
        *,
        session: SessionState,
        query: MemoryStoreQuery,
    ) -> list[AgentMemorySnapshot]:
        self.queries.append(query)
        candidates = super().fetch_candidates(session=session, query=query)
        terms = tuple(query.query_anchors) + tuple(query.query_tokens)
        if not terms:
            return candidates
        normalized_terms = {
            " ".join(str(term).casefold().split())
            for term in terms
            if len(str(term).strip()) >= 2
        }
        return [
            snapshot
            for snapshot in candidates
            if any(term in _prefilter_haystack(snapshot) for term in normalized_terms)
        ]


class OverRecallingMemoryStore:
    backend_name = "over_recalling_test"

    def __init__(self, snapshots: list[AgentMemorySnapshot]) -> None:
        self.snapshots = snapshots
        self.queries: list[MemoryStoreQuery] = []

    def fetch_candidates(
        self,
        *,
        session: SessionState,
        query: MemoryStoreQuery,
    ) -> list[AgentMemorySnapshot]:
        _ = session
        self.queries.append(query)
        return list(self.snapshots)


def test_in_memory_store_preserves_legacy_retrieval_result() -> None:
    relevant = _memory(
        memory_id="memory.relevant.empty_capsules",
        content="empty capsules made jiang defensive",
        metadata={"clue_id": "empty_capsules", "phase_id": PHASE},
        salience=0.25,
    )
    unrelated = _memory(
        memory_id="memory.unrelated.high_salience",
        content="player discussed the seating chart",
        metadata={"phase_id": PHASE},
        salience=0.99,
    )
    hidden = _memory(
        memory_id="memory.hidden.other_npc",
        content="shen private memory about empty capsules",
        owner_character_id=SHEN,
        visible_to_character_ids=[SHEN],
        salience=1.0,
    )
    session = _session([unrelated, hidden, relevant])
    action = PlayerAction(
        type=ActionType.ASK_ABOUT,
        target_id=JIANG,
        subject_type="clue",
        subject_id="empty_capsules",
        text="empty capsules",
    )

    legacy_result = MemoryRetriever(max_results=10).retrieve(
        case=_case(),
        session=session,
        action=action,
        plan=_plan(),
    )
    store_result = MemoryRetriever(
        max_results=10,
        memory_store=InMemoryMemoryStore(),
    ).retrieve(
        case=_case(),
        session=session,
        action=action,
        plan=_plan(),
    )

    assert _memory_ids(store_result) == _memory_ids(legacy_result)
    assert _memory_ids(store_result)[0] == relevant.memory_id
    assert hidden.memory_id not in _memory_ids(store_result)


def test_retriever_passes_first_stage_boundaries_to_store() -> None:
    store = RecordingMemoryStore()
    session = _session(
        [
            _memory(
                memory_id="memory.visible",
                content="empty capsules",
                metadata={"phase_id": PHASE},
                salience=0.5,
            )
        ]
    )

    result = MemoryRetriever(memory_store=store).retrieve(
        case=_case(),
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="empty capsules"),
        plan=_plan(),
    )

    assert _memory_ids(result) == ["memory.visible"]
    assert store.queries[0] == MemoryStoreQuery(
        session_id=SESSION_ID,
        target_id=JIANG,
        phase=PHASE,
        enforce_target_visibility=True,
        scopes=("case", "npc_private", "scene_shared", "session"),
        layers=("core", "working"),
        memory_types=("belief", "episodic", "relationship", "strategy"),
        query_anchors=(),
        query_tokens=("capsule", "capsules", "empty"),
    )


def test_retriever_passes_semantic_alias_tokens_to_store_prefilter() -> None:
    store = RecordingMemoryStore()
    session = _session(
        [
            _memory(
                memory_id="memory.visible.semantic_prefilter",
                content="Jiang discusses the medicine clue.",
                metadata={"phase_id": PHASE},
                salience=0.5,
            )
        ]
    )

    result = MemoryRetriever(memory_store=store).retrieve(
        case=_case_with_empty_capsules_clue(),
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="继续追问药壳子"),
        plan=_plan(),
    )

    assert _memory_ids(result) == ["memory.visible.semantic_prefilter"]
    assert store.queries[0].query_anchors == ("empty_capsules",)
    assert {"capsules", "medicine"} <= set(store.queries[0].query_tokens)


def test_retriever_expands_source_links_from_unprefiltered_store_pool() -> None:
    store = QueryPrefilteringMemoryStore()
    anchor = _memory(
        memory_id="memory.source.001",
        content="player mentioned uniqueanchor to Jiang",
        salience=0.6,
    )
    strategy = _memory(
        memory_id="memory.linked.strategy",
        content="Jiang should deflect without adding facts.",
        memory_type="strategy",
        source_memory_ids=[anchor.memory_id],
        metadata={
            "authority_source": "player_evidence",
            "strategy_id": "deflect_topic",
        },
        salience=0.1,
    )
    session = _session([anchor, strategy])

    result = MemoryRetriever(
        max_results=10,
        memory_store=store,
    ).retrieve(
        case=_case(),
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="uniqueanchor"),
        plan=_plan(),
    )

    assert _memory_ids(result) == [anchor.memory_id, strategy.memory_id]
    assert len(store.queries) == 2
    assert store.queries[0].query_tokens == ("uniqueanchor",)
    assert store.queries[1].query_tokens == ()
    assert store.queries[1].query_anchors == ()


def test_retriever_hard_filters_remain_final_boundary_after_store_overrecall() -> None:
    visible = _memory(
        memory_id="memory.visible.allowed",
        content="empty capsules visible projected memory",
        metadata={"phase_id": PHASE},
        salience=0.7,
    )
    hidden = _memory(
        memory_id="memory.hidden.other_npc",
        content="empty capsules hidden from Jiang",
        owner_character_id=SHEN,
        visible_to_character_ids=[SHEN],
        metadata={"phase_id": PHASE},
        salience=1.0,
    )
    wrong_phase = _memory(
        memory_id="memory.wrong_phase",
        content="empty capsules later phase memory",
        metadata={"phase_id": "reveal"},
        salience=1.0,
    )
    no_source = _memory(
        memory_id="memory.no_source",
        content="empty capsules without provenance",
        metadata={"phase_id": PHASE},
        salience=1.0,
    ).model_copy(update={"source_event_ids": []})
    forbidden = _memory(
        memory_id="memory.forbidden",
        content="empty capsules locked truth",
        metadata={"phase_id": PHASE},
        salience=1.0,
    )
    plan_disallowed = _memory(
        memory_id="memory.plan_disallowed",
        content="empty capsules disallowed memory type",
        memory_type="relationship",
        metadata={"phase_id": PHASE},
        salience=1.0,
    )
    snapshots = [
        hidden,
        wrong_phase,
        no_source,
        forbidden,
        plan_disallowed,
        visible,
    ]
    store = OverRecallingMemoryStore(snapshots)
    case = _case().model_copy(
        update={
            "forbidden_facts": [
                ForbiddenFactConfig(
                    id="fact.locked_truth",
                    text="locked truth",
                    blocked_terms=["locked truth"],
                )
            ]
        }
    )

    result = MemoryRetriever(max_results=10, memory_store=store).retrieve(
        case=case,
        session=_session(snapshots),
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="empty capsules"),
        plan=replace(_plan(), included_memory_types=("episodic",)),
    )

    assert _memory_ids(result) == [visible.memory_id]
    assert store.queries[0].enforce_target_visibility is True
    assert store.queries[0].query_tokens == ("capsule", "capsules", "empty")


def test_store_trace_summary_excludes_memory_content() -> None:
    retriever = MemoryRetriever(memory_store=InMemoryMemoryStore())
    session = _session(
        [
            _memory(
                memory_id="memory.trace",
                content="SECRET MEMORY CONTENT MUST NOT ENTER TRACE",
                salience=0.5,
            )
        ]
    )

    retriever.retrieve(
        case=_case(),
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="SECRET"),
        plan=_plan(),
    )

    summary = retriever.last_store_trace_summary
    assert summary is not None
    serialized = repr(summary)
    assert summary.backend == "in_memory"
    assert summary.candidate_count == 1
    assert summary.requested_filters["query_anchor_count"] == 0
    assert summary.requested_filters["query_token_count"] == 1
    assert summary.requested_filters["query_prefilter_enabled"] is True
    assert "SECRET MEMORY CONTENT" not in serialized
    assert "memory.trace" not in serialized
    assert "SECRET" not in serialized


def test_agent_loop_trace_includes_store_summary_without_content() -> None:
    case = _case()
    session = _session(
        [
            _memory(
                memory_id="memory.loop.trace",
                content="LOOP SECRET MEMORY CONTENT",
                metadata={"phase_id": PHASE},
                salience=0.8,
            )
        ]
    )
    records: list[dict[str, object]] = []
    loop = AgentLoop(
        agent_gateway=AgentGateway(backend="llm_stub"),
        runtime_tracer=RuntimeTracer(sink=_RecordingTraceSink(records)),
        memory_retriever=MemoryRetriever(memory_store=InMemoryMemoryStore()),
    )

    turn = loop.run_turn(
        case=case,
        session=session,
        action=PlayerAction(type=ActionType.TALK, target_id=JIANG, text="loop trace"),
    )
    loop.finish_trace(
        turn,
        director_allowed=True,
        director_reason_category=None,
        rule_rejections=[],
        new_events=[],
        phase_after=PHASE,
        public_speech=turn.intent.speech,
        public_speech_source="npc",
    )

    assert len(records) == 1
    projection = records[0]["memory_projection"]
    serialized = json.dumps(projection, ensure_ascii=False)
    assert projection["store"]["backend"] == "in_memory"
    assert projection["store"]["candidate_count"] == 1
    assert projection["store"]["requested_filters"]["query_token_count"] == 2
    assert "LOOP SECRET MEMORY CONTENT" not in serialized
    assert "memory.loop.trace" in serialized


def test_postgres_memory_store_queries_projection_with_phase_and_visibility_filters() -> None:
    row = _postgres_memory_row(
        memory_id="memory.pg.visible",
        content="visible projected memory",
        metadata={"phase_id": PHASE},
    )
    connection = _FakeConnection(rows=[row])
    store = PostgresMemoryStore(connection)

    results = store.fetch_candidates(
        session=_session([]),
        query=MemoryStoreQuery(
            session_id=SESSION_ID,
            target_id=JIANG,
            phase=PHASE,
            enforce_target_visibility=True,
            scopes=("npc_private",),
            layers=("working",),
            memory_types=("episodic",),
            query_anchors=("empty_capsules",),
            query_tokens=("capsules", "medicine"),
        ),
    )

    assert _memory_ids(results) == ["memory.pg.visible"]
    assert connection.commit_count == 1
    assert connection.rollback_count == 0
    assert "FROM memory_snapshots" in connection.query
    assert "memory_scope = ANY(%s)" in connection.query
    assert "memory_layer = ANY(%s)" in connection.query
    assert "memory_type = ANY(%s)" in connection.query
    assert "metadata->>'phase_id' = %s" in connection.query
    assert "metadata->'phase_ids' ? %s" in connection.query
    assert "FROM unnest(%s::text[]) AS query_term(term)" in connection.query
    assert "memory_id ILIKE" in connection.query
    assert "content ILIKE" in connection.query
    assert "source_ref.value ILIKE" in connection.query
    assert "metadata::text ILIKE" in connection.query
    assert "to_tsvector( 'simple', concat_ws(" in connection.query
    assert ") @@ plainto_tsquery('simple', query_term.term)" in connection.query
    assert "content = %s" not in connection.query
    assert connection.params == (
        SESSION_ID,
        ["npc_private"],
        ["working"],
        ["episodic"],
        JIANG,
        JIANG,
        JIANG,
        JIANG,
        PHASE,
        PHASE,
        ["empty_capsules", "capsules", "medicine"],
    )


def test_postgres_memory_store_can_emit_optional_trigram_prefilter_shape() -> None:
    connection = _FakeConnection(rows=[])
    store = PostgresMemoryStore(
        connection,
        enable_trigram_prefilter=True,
        trigram_similarity_threshold=0.42,
    )

    results = store.fetch_candidates(
        session=_session([]),
        query=MemoryStoreQuery(
            session_id=SESSION_ID,
            target_id=JIANG,
            phase=PHASE,
            enforce_target_visibility=False,
            query_anchors=("empty_capsules",),
            query_tokens=("capsules",),
        ),
    )

    assert results == []
    assert "word_similarity(query_term.term, content) >= %s" in connection.query
    assert "word_similarity(query_term.term, memory_id) >= %s" in connection.query
    assert "word_similarity(query_term.term, metadata::text) >= %s" in connection.query
    assert "AS fuzzy_source_ref(value)" in connection.query
    assert connection.params == (
        SESSION_ID,
        PHASE,
        PHASE,
        ["empty_capsules", "capsules"],
        0.42,
        0.42,
        0.42,
        0.42,
    )


def _case() -> CasePackage:
    return CasePackage(
        meta=CaseMeta(id=CASE_ID, title="Memory DB Retrieval", initial_phase=PHASE),
        characters=[
            CharacterConfig(id=JIANG, display_name="Jiang", public_role="doctor"),
            CharacterConfig(id=SHEN, display_name="Shen", public_role="heir"),
        ],
        scenes=[SceneConfig(id="study", name="Study")],
        clues=[],
    )


def _case_with_empty_capsules_clue() -> CasePackage:
    return _case().model_copy(
        update={
            "clues": [
                ClueConfig(
                    id="empty_capsules",
                    title="empty capsules",
                    description="Empty capsule shells from the medicine box.",
                )
            ]
        }
    )


def _session(snapshots: list[AgentMemorySnapshot]) -> SessionState:
    return SessionState(
        id=SESSION_ID,
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
    source_memory_ids: list[str] | None = None,
    metadata: dict[str, object] | None = None,
) -> AgentMemorySnapshot:
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
        source_event_ids=[f"event.{memory_id}"],
        source_memory_ids=source_memory_ids or [],
        salience=salience,
        confidence=1.0,
        visibility="private",
        metadata=metadata or {},
        last_updated_event_id=f"event.{memory_id}",
        created_at="2026-06-16T00:00:00Z",
        updated_at="2026-06-16T00:00:00Z",
    )


def _plan() -> MemoryRetrievalPlan:
    return MemoryRetrievalPlan(
        skill_id="test.memory_db_retrieval",
        included_memory_types=("episodic", "belief", "relationship", "strategy"),
        included_scopes=("case", "session", "npc_private", "scene_shared"),
        included_layers=("core", "working"),
        forbidden_scopes=("director_audit",),
        forbidden_layers=("archival",),
        max_memory_items=8,
        inject_portrait_summary=False,
        allow_recent_events=False,
    )


def _memory_ids(memories: list[AgentMemorySnapshot]) -> list[str]:
    return [memory.memory_id for memory in memories]


def _prefilter_haystack(snapshot: AgentMemorySnapshot) -> str:
    values = [
        snapshot.memory_id,
        snapshot.content,
        *snapshot.source_event_ids,
        *snapshot.source_memory_ids,
        json.dumps(snapshot.metadata, ensure_ascii=False, sort_keys=True),
    ]
    return " ".join(str(value).casefold() for value in values if value)


def _postgres_memory_row(
    *,
    memory_id: str,
    content: str,
    metadata: dict[str, object],
) -> dict[str, object]:
    return {
        "memory_id": memory_id,
        "rule_id": "memory_rule.test",
        "memory_type": "episodic",
        "memory_scope": "npc_private",
        "memory_layer": "working",
        "last_operation": "create",
        "subject_id": "player",
        "owner_character_id": JIANG,
        "visible_to_character_ids": [JIANG],
        "content": content,
        "source_event_ids": ["event.source"],
        "source_memory_ids": [],
        "salience": 0.7,
        "confidence": 1.0,
        "visibility": "private",
        "metadata": metadata,
        "last_updated_event_id": "event.source",
        "created_at": datetime(2026, 6, 16, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 16, tzinfo=UTC),
    }


class _FakeConnection:
    def __init__(self, *, rows: list[dict[str, object]]) -> None:
        self.cursor_obj = _FakeCursor(rows)
        self.commit_count = 0
        self.rollback_count = 0

    @property
    def query(self) -> str:
        return self.cursor_obj.query

    @property
    def params(self) -> tuple[object, ...]:
        return self.cursor_obj.params

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


class _FakeCursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.query = ""
        self.params: tuple[object, ...] = ()

    def execute(self, query: str, params: tuple[object, ...] | None = None) -> None:
        self.query = " ".join(query.split())
        self.params = params or ()

    def fetchall(self) -> list[dict[str, object]]:
        return list(self.rows)

    def fetchone(self) -> dict[str, object] | None:
        return self.rows[0] if self.rows else None


class _RecordingTraceSink:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self._records = records

    def write(self, record: dict[str, object]) -> None:
        self._records.append(record)
