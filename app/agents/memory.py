from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.agents.memory_authority import (
    MemoryAuthorityTraceSummary,
    resolve_authoritative_memory_results_with_trace,
)
from app.agents.memory_retrieval import (
    EmbeddingScorer,
    LocalBM25KeywordScorer,
    LocalSemanticEmbeddingScorer,
    MemoryHardFilter,
    MemoryReranker,
    MemoryRetrievalPipeline,
    MemorySearchQuery,
    MemorySearchResult,
    MemorySearchScore,
)
from app.agents.retrieval_planner import MemoryRetrievalPlan
from app.domain.models import (
    AgentMemorySnapshot,
    CasePackage,
    ClueConfig,
    PlayerAction,
    SessionState,
    WorldInfoConfig,
)

AGENT_MEMORY_SCOPES = {"case", "session", "npc_private", "scene_shared"}
DIRECTOR_MEMORY_SCOPES = AGENT_MEMORY_SCOPES | {"director_audit"}
LATIN_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]{2,}")
IDENTIFIER_CHUNK_PATTERN = re.compile(r"[^A-Za-z0-9_]+")
CAMEL_CASE_BOUNDARY_PATTERN = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])"
)
CJK_RUN_PATTERN = re.compile(r"[\u4e00-\u9fff]+")
LATIN_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "ask",
    "asked",
    "asking",
    "at",
    "be",
    "been",
    "being",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "her",
    "him",
    "his",
    "how",
    "in",
    "into",
    "is",
    "it",
    "its",
    "just",
    "not",
    "of",
    "on",
    "or",
    "she",
    "should",
    "tell",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "they",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
}
LOCAL_SEMANTIC_WEAK_TOKENS = frozenset(
    {
        "about",
        "archival",
        "belief",
        "case",
        "clue",
        "core",
        "continue",
        "continued",
        "evidence",
        "event",
        "event_observed",
        "eventobserved",
        "episodic",
        "false",
        "high",
        "high_salience",
        "highsalience",
        "item",
        "memory",
        "memory_id",
        "memory_rule",
        "memoryid",
        "memoryrule",
        "missing",
        "npc_private",
        "npcprivate",
        "observed",
        "player",
        "private",
        "question",
        "questions",
        "rule",
        "salience",
        "session",
        "something",
        "source",
        "source_event",
        "source_memory",
        "sourceevent",
        "sourcememory",
        "strategy",
        "test",
        "thing",
        "true",
        "working",
        "继续",
        "追问",
        "询问",
        "关于",
        "这个",
        "那个",
        "东西",
        "线索",
        "证据",
    }
)
RECENCY_BUCKETS = (
    (60 * 60, 0.8),
    (24 * 60 * 60, 0.65),
    (3 * 24 * 60 * 60, 0.4),
    (7 * 24 * 60 * 60, 0.2),
)
TEXT_SCORE_CAP = 1.5
STRUCTURED_SCORE_CAP = 5.0
LOCAL_SEMANTIC_SCORE_CAP = 1.25

DEFAULT_LOCAL_SEMANTIC_CONCEPT_ALIASES = {
    "empty_capsules": (
        "empty capsules",
        "empty capsule",
        "capsule shell",
        "capsule shells",
        "missing pills",
        "missing medicine",
        "medicine box",
        "medicine bottle",
        "medical clue",
        "medicine clue",
        "medicine shells",
        "medicine shell",
        "pill shells",
        "pill shell",
        "pill bottle",
        "prescription bottle",
        "prescription tampering",
        "heart medicine",
        "empty medicine shells",
        "空胶囊",
        "胶囊壳",
        "胶囊外壳",
        "药壳",
        "药壳子",
        "空药囊",
        "空药壳",
        "药盒",
        "药箱",
        "药瓶",
        "药片缺失",
        "心脏药",
        "医药线索",
    ),
    "delayed_lock_marks": (
        "delayed lock marks",
        "delay lock marks",
        "lock scratch marks",
        "timer lock",
        "study lock marks",
        "delayed latch",
        "延迟锁痕",
        "门锁划痕",
        "锁痕",
        "书房门锁",
    ),
}


@dataclass(frozen=True)
class MemoryStoreQuery:
    session_id: str
    target_id: str
    phase: str
    enforce_target_visibility: bool = True
    scopes: tuple[str, ...] = ()
    layers: tuple[str, ...] = ()
    memory_types: tuple[str, ...] = ()
    query_anchors: tuple[str, ...] = ()
    query_tokens: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryStoreTraceSummary:
    backend: str
    requested_filters: dict[str, object]
    candidate_count: int


@dataclass(frozen=True)
class MemoryRetrievalTraceSummary:
    total_snapshot_count: int = 0
    store_candidate_count: int = 0
    hard_filter_candidate_count: int = 0
    scored_count: int = 0
    authority_selected_count: int = 0
    selected_count: int = 0
    zero_reason: str | None = None
    filter_counts: dict[str, int] | None = None

    def to_projection(self) -> dict[str, object]:
        return {
            "total_snapshot_count": self.total_snapshot_count,
            "store_candidate_count": self.store_candidate_count,
            "hard_filter_candidate_count": self.hard_filter_candidate_count,
            "scored_count": self.scored_count,
            "authority_selected_count": self.authority_selected_count,
            "selected_count": self.selected_count,
            "zero_reason": self.zero_reason,
            "filter_counts": dict(self.filter_counts or {}),
        }


class MemoryStore(Protocol):
    backend_name: str

    def fetch_candidates(
        self,
        *,
        session: SessionState,
        query: MemoryStoreQuery,
    ) -> list[AgentMemorySnapshot]:
        ...


class InMemoryMemoryStore:
    backend_name = "in_memory"

    def fetch_candidates(
        self,
        *,
        session: SessionState,
        query: MemoryStoreQuery,
    ) -> list[AgentMemorySnapshot]:
        snapshots = list(session.memory_snapshots.values())
        return [
            snapshot
            for snapshot in snapshots
            if _store_query_matches(snapshot, query)
        ]


class MemoryRetriever:
    def __init__(
        self,
        *,
        max_results: int = 8,
        embedding_scorer: EmbeddingScorer | None = None,
        reranker: MemoryReranker | None = None,
        memory_store: MemoryStore | None = None,
    ) -> None:
        self._max_results = max_results
        self._embedding_scorer = embedding_scorer
        self._reranker = reranker
        self._memory_store = memory_store or InMemoryMemoryStore()
        self._last_store_trace_summary: MemoryStoreTraceSummary | None = None
        self._last_authority_trace_summary = MemoryAuthorityTraceSummary()
        self._last_retrieval_trace_summary = MemoryRetrievalTraceSummary()

    @property
    def last_store_trace_summary(self) -> MemoryStoreTraceSummary | None:
        return self._last_store_trace_summary

    @property
    def last_authority_trace_summary(self) -> MemoryAuthorityTraceSummary:
        return self._last_authority_trace_summary

    @property
    def last_retrieval_trace_summary(self) -> MemoryRetrievalTraceSummary:
        return self._last_retrieval_trace_summary

    def retrieve(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
        plan: MemoryRetrievalPlan | None = None,
    ) -> list[AgentMemorySnapshot]:
        return self._retrieve(
            case=case,
            session=session,
            action=action,
            enforce_target_visibility=True,
            plan=plan,
        )

    def retrieve_for_director(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> list[AgentMemorySnapshot]:
        return self._retrieve(
            case=case,
            session=session,
            action=action,
            enforce_target_visibility=False,
            plan=None,
        )

    def _retrieve(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
        enforce_target_visibility: bool,
        plan: MemoryRetrievalPlan | None,
    ) -> list[AgentMemorySnapshot]:
        max_results = plan.max_memory_items if plan is not None else self._max_results
        self._last_authority_trace_summary = MemoryAuthorityTraceSummary()
        self._last_retrieval_trace_summary = MemoryRetrievalTraceSummary()
        if max_results <= 0:
            self._last_retrieval_trace_summary = MemoryRetrievalTraceSummary(
                total_snapshot_count=len(session.memory_snapshots),
                selected_count=0,
                zero_reason="plan_max_items_zero",
                filter_counts={},
            )
            return []

        query = _build_query(case, action)
        forbidden_terms = _forbidden_terms(case) if enforce_target_visibility else ()
        working_filters = _working_hard_filters(
            enforce_target_visibility=enforce_target_visibility,
            target_id=action.target_id,
            phase=session.narrative.phase,
            plan=plan,
            forbidden_terms=forbidden_terms,
        )
        working_store_query = _store_query(
            session=session,
            target_id=action.target_id,
            enforce_target_visibility=enforce_target_visibility,
            scopes=_allowed_scopes_for_store(
                enforce_target_visibility=enforce_target_visibility,
                plan=plan,
            ),
            layers=_working_layers_for_store(plan),
            memory_types=_memory_types_for_store(plan),
            search_query=query,
        )
        snapshots = self._fetch_store_candidates(session, working_store_query)
        working_candidates = _filter_snapshots(snapshots, working_filters)
        raw_scored = self._search_candidates(
            snapshots=snapshots,
            query=query,
            case=case,
            now=_retrieval_now(session, working_candidates),
            hard_filters=working_filters,
        )
        expansion_snapshots = self._link_expansion_snapshots(
            session=session,
            query=working_store_query,
            snapshots=snapshots,
            has_seed_results=bool(raw_scored),
        )
        raw_scored = _expand_linked_results(
            results=raw_scored,
            snapshots=expansion_snapshots,
            query=query,
            now=_retrieval_now(session, working_candidates),
            hard_filters=working_filters,
            phase=session.narrative.phase,
        )
        authority_result = resolve_authoritative_memory_results_with_trace(raw_scored)
        scored = _rank_results_for_projection(
            authority_result.results,
            target_id=action.target_id,
            phase=session.narrative.phase,
        )
        self._last_authority_trace_summary = authority_result.trace_summary
        if scored or not enforce_target_visibility:
            selected = [result.snapshot for result in scored[:max_results]]
            self._last_retrieval_trace_summary = _retrieval_trace_summary(
                session=session,
                filters=working_filters,
                store_candidate_count=len(snapshots),
                hard_filter_candidate_count=len(working_candidates),
                scored_count=len(raw_scored),
                authority_selected_count=len(scored),
                selected_count=len(selected),
            )
            return selected

        archival_filters = _archival_hard_filters(
            target_id=action.target_id,
            phase=session.narrative.phase,
            plan=plan,
            forbidden_terms=forbidden_terms,
        )
        archival_store_query = _store_query(
            session=session,
            target_id=action.target_id,
            enforce_target_visibility=True,
            scopes=_allowed_scopes_for_store(
                enforce_target_visibility=True,
                plan=plan,
            ),
            layers=("archival",),
            memory_types=_memory_types_for_store(plan),
            search_query=query,
        )
        archival_snapshots = self._fetch_store_candidates(session, archival_store_query)
        archival_candidates = _filter_snapshots(archival_snapshots, archival_filters)
        archival_scored = self._search_candidates(
            snapshots=archival_snapshots,
            query=query,
            case=case,
            now=_retrieval_now(session, archival_candidates),
            hard_filters=archival_filters,
        )
        archival_authority_result = resolve_authoritative_memory_results_with_trace(
            archival_scored
        )
        archival_scored = _rank_results_for_projection(
            archival_authority_result.results,
            target_id=action.target_id,
            phase=session.narrative.phase,
        )
        self._last_authority_trace_summary = archival_authority_result.trace_summary
        selected = [result.snapshot for result in archival_scored[:max_results]]
        self._last_retrieval_trace_summary = _retrieval_trace_summary(
            session=session,
            filters=working_filters,
            store_candidate_count=len(snapshots),
            hard_filter_candidate_count=len(working_candidates),
            scored_count=len(raw_scored),
            authority_selected_count=0,
            selected_count=0,
        )
        if selected:
            self._last_retrieval_trace_summary = _retrieval_trace_summary(
                session=session,
                filters=archival_filters,
                store_candidate_count=len(archival_snapshots),
                hard_filter_candidate_count=len(archival_candidates),
                scored_count=len(archival_scored),
                authority_selected_count=len(archival_scored),
                selected_count=len(selected),
            )
        return selected

    def _fetch_store_candidates(
        self,
        session: SessionState,
        query: MemoryStoreQuery,
        *,
        record_trace: bool = True,
    ) -> list[AgentMemorySnapshot]:
        snapshots = self._memory_store.fetch_candidates(session=session, query=query)
        if not record_trace:
            return snapshots
        self._last_store_trace_summary = MemoryStoreTraceSummary(
            backend=self._memory_store.backend_name,
            requested_filters={
                "session_id": query.session_id,
                "target_id": query.target_id,
                "phase": query.phase,
                "scopes": list(query.scopes),
                "layers": list(query.layers),
                "memory_types": list(query.memory_types),
                "query_anchor_count": len(query.query_anchors),
                "query_token_count": len(query.query_tokens),
                "query_prefilter_enabled": bool(
                    query.query_anchors or query.query_tokens
                ),
            },
            candidate_count=len(snapshots),
        )
        return snapshots

    def _link_expansion_snapshots(
        self,
        *,
        session: SessionState,
        query: MemoryStoreQuery,
        snapshots: list[AgentMemorySnapshot],
        has_seed_results: bool,
    ) -> list[AgentMemorySnapshot]:
        if not has_seed_results:
            return snapshots
        if not (query.query_anchors or query.query_tokens):
            return snapshots
        expansion_query = _store_query_without_prefilter(query)
        expansion_snapshots = self._fetch_store_candidates(
            session,
            expansion_query,
            record_trace=False,
        )
        return _dedupe_snapshots([*snapshots, *expansion_snapshots])

    def _search_candidates(
        self,
        *,
        snapshots: list[AgentMemorySnapshot],
        query: MemorySearchQuery,
        case: CasePackage,
        now: datetime | None,
        hard_filters: tuple[MemoryHardFilter, ...],
    ) -> list[MemorySearchResult]:
        embedding_scorer = (
            self._embedding_scorer
            or build_local_semantic_embedding_scorer(_case_semantic_concept_aliases(case))
        )
        pipeline = MemoryRetrievalPipeline(
            structured_scorer=_structured_score,
            keyword_scorer_factory=lambda candidates: LocalBM25KeywordScorer(
                candidates,
                tokenizer=_tokens,
                haystack_builder=_snapshot_haystack,
                cap=TEXT_SCORE_CAP,
                b=0.0,
            ),
            recency_scorer=lambda snapshot: _recency_score(snapshot, now),
            reinforcement_scorer=_reinforcement_score,
            embedding_scorer=embedding_scorer,
            reranker=self._reranker,
        )
        return pipeline.search(
            query=query,
            snapshots=snapshots,
            hard_filters=hard_filters,
        )


def build_local_semantic_embedding_scorer(
    concept_aliases: dict[str, tuple[str, ...]] | None = None,
) -> LocalSemanticEmbeddingScorer:
    return LocalSemanticEmbeddingScorer(
        DEFAULT_LOCAL_SEMANTIC_CONCEPT_ALIASES
        if concept_aliases is None
        else concept_aliases,
        tokenizer=_tokens,
        haystack_builder=_snapshot_haystack,
        cap=LOCAL_SEMANTIC_SCORE_CAP,
        weak_tokens=LOCAL_SEMANTIC_WEAK_TOKENS,
    )


def _expand_linked_results(
    *,
    results: list[MemorySearchResult],
    snapshots: list[AgentMemorySnapshot],
    query: MemorySearchQuery,
    now: datetime | None,
    hard_filters: tuple[MemoryHardFilter, ...],
    phase: str,
) -> list[MemorySearchResult]:
    if not results:
        return results
    result_ids = {result.snapshot.memory_id for result in results}
    frontier_ids = set(result_ids)
    frontier_thread_ids = _case_thread_ids(result.snapshot for result in results)
    linked_results: list[MemorySearchResult] = []
    candidates = _filter_snapshots(snapshots, hard_filters)
    for snapshot in candidates:
        if snapshot.memory_id in result_ids:
            continue
        linked = bool(set(snapshot.source_memory_ids) & frontier_ids) or any(
            snapshot.memory_id in set(result.snapshot.source_memory_ids)
            for result in results
        )
        if (
            not linked
            and _case_thread_expansion_allowed(phase)
            and _snapshot_case_thread_id(snapshot) in frontier_thread_ids
        ):
            linked = True
        if not linked:
            continue
        linked_results.append(
            MemorySearchResult(
                snapshot=snapshot,
                score=_linked_memory_score(snapshot, query=query, now=now),
            )
        )
    if not linked_results:
        return results
    linked_results.sort(key=lambda result: result.score.sort_key, reverse=True)
    return [*results, *linked_results]


def _linked_memory_score(
    snapshot: AgentMemorySnapshot,
    *,
    query: MemorySearchQuery,
    now: datetime | None,
) -> MemorySearchScore:
    structured = 0.9 + _narrative_chain_boost(snapshot)
    recency = _recency_score(snapshot, now)
    reinforcement = _reinforcement_score(snapshot)
    confidence = snapshot.confidence * 0.15
    total = structured + recency + reinforcement + confidence
    return MemorySearchScore(
        total=total,
        structured=structured,
        keyword=0.0,
        embedding=0.0,
        rerank=0.0,
        recency=recency,
        reinforcement=reinforcement,
        salience=snapshot.salience,
        confidence=snapshot.confidence,
        updated_at=snapshot.updated_at or snapshot.created_at or "",
        memory_id=snapshot.memory_id,
        has_relevance=bool(query.anchors or query.text_tokens),
    )


def _case_thread_ids(snapshots: Iterable[AgentMemorySnapshot]) -> set[str]:
    return {
        case_thread_id
        for snapshot in snapshots
        for case_thread_id in [_snapshot_case_thread_id(snapshot)]
        if case_thread_id
    }


def _snapshot_case_thread_id(snapshot: AgentMemorySnapshot) -> str | None:
    value = snapshot.metadata.get("case_thread_id")
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _narrative_chain_boost(snapshot: AgentMemorySnapshot) -> float:
    boost = 0.0
    if snapshot.metadata.get("key_clue") is True:
        boost += 0.35
    if snapshot.metadata.get("case_thread_id"):
        boost += 0.25
    if snapshot.memory_type in {"belief", "strategy", "relationship"}:
        boost += 0.2
    return boost


def _case_thread_expansion_allowed(phase: str) -> bool:
    return phase in {"reconstruction", "resolved"}


def _rank_results_for_projection(
    results: list[MemorySearchResult],
    *,
    target_id: str,
    phase: str,
) -> list[MemorySearchResult]:
    if not _case_thread_expansion_allowed(phase):
        return results
    return sorted(
        results,
        key=lambda result: (
            _reconstruction_projection_priority(result.snapshot, target_id=target_id),
            result.score.sort_key,
        ),
        reverse=True,
    )


def _reconstruction_projection_priority(
    snapshot: AgentMemorySnapshot,
    *,
    target_id: str,
) -> int:
    if snapshot.metadata.get("key_clue") is True and snapshot.memory_type == "episodic":
        return 30
    if (
        snapshot.memory_type in {"belief", "strategy"}
        and snapshot.owner_character_id == target_id
        and snapshot.memory_scope == "npc_private"
        and snapshot.metadata.get("case_thread_id")
    ):
        return 20
    if (
        snapshot.memory_type in {"belief", "strategy"}
        and snapshot.memory_scope == "case"
        and snapshot.metadata.get("case_thread_id")
    ):
        return 10
    return 0


def _working_hard_filters(
    *,
    enforce_target_visibility: bool,
    target_id: str,
    phase: str,
    plan: MemoryRetrievalPlan | None,
    forbidden_terms: tuple[str, ...],
) -> tuple[MemoryHardFilter, ...]:
    return (
        MemoryHardFilter(
            "subject_is_player",
            lambda snapshot: snapshot.subject_id == "player",
        ),
        MemoryHardFilter(
            "scope_allowed",
            lambda snapshot: _scope_allowed(
                snapshot,
                enforce_target_visibility=enforce_target_visibility,
            ),
        ),
        MemoryHardFilter(
            "visible_to_target",
            lambda snapshot: (
                not enforce_target_visibility
                or _visible_to_target(snapshot, target_id)
            ),
        ),
        MemoryHardFilter("layer_allowed", _layer_allowed),
        MemoryHardFilter("has_source_event_ids", _source_allowed),
        MemoryHardFilter(
            "phase_allowed",
            lambda snapshot: _phase_allowed(snapshot, phase),
        ),
        MemoryHardFilter(
            "plan_allowed",
            lambda snapshot: memory_allowed_by_plan(snapshot, plan),
        ),
        MemoryHardFilter(
            "forbidden_text_absent",
            lambda snapshot: not memory_content_matches_forbidden(
                snapshot,
                forbidden_terms,
            ),
        ),
    )


def _store_query(
    *,
    session: SessionState,
    target_id: str,
    enforce_target_visibility: bool,
    scopes: tuple[str, ...],
    layers: tuple[str, ...],
    memory_types: tuple[str, ...],
    search_query: MemorySearchQuery | None = None,
) -> MemoryStoreQuery:
    return MemoryStoreQuery(
        session_id=session.id,
        target_id=target_id,
        phase=session.narrative.phase,
        enforce_target_visibility=enforce_target_visibility,
        scopes=scopes,
        layers=layers,
        memory_types=memory_types,
        query_anchors=tuple(sorted(search_query.anchors)) if search_query else (),
        query_tokens=tuple(sorted(search_query.semantic_tokens)) if search_query else (),
    )


def _allowed_scopes_for_store(
    *,
    enforce_target_visibility: bool,
    plan: MemoryRetrievalPlan | None,
) -> tuple[str, ...]:
    allowed = (
        AGENT_MEMORY_SCOPES
        if enforce_target_visibility
        else DIRECTOR_MEMORY_SCOPES
    )
    if plan is not None:
        allowed = allowed & set(plan.included_scopes)
        allowed = allowed - set(plan.forbidden_scopes)
    return tuple(sorted(allowed))


def _working_layers_for_store(plan: MemoryRetrievalPlan | None) -> tuple[str, ...]:
    layers = {"core", "working"}
    if plan is not None:
        layers = layers & set(plan.included_layers)
        layers = layers - set(plan.forbidden_layers)
    return tuple(sorted(layers))


def _memory_types_for_store(plan: MemoryRetrievalPlan | None) -> tuple[str, ...]:
    if plan is None:
        return ()
    return tuple(sorted(set(plan.included_memory_types)))


def _store_query_matches(
    snapshot: AgentMemorySnapshot,
    query: MemoryStoreQuery,
) -> bool:
    if query.scopes and snapshot.memory_scope not in set(query.scopes):
        return False
    if query.layers and snapshot.memory_layer not in set(query.layers):
        return False
    if query.memory_types and snapshot.memory_type not in set(query.memory_types):
        return False
    if query.enforce_target_visibility and not _visible_to_target(snapshot, query.target_id):
        return False
    return _phase_allowed(snapshot, query.phase)


def _store_query_without_prefilter(query: MemoryStoreQuery) -> MemoryStoreQuery:
    return MemoryStoreQuery(
        session_id=query.session_id,
        target_id=query.target_id,
        phase=query.phase,
        enforce_target_visibility=query.enforce_target_visibility,
        scopes=query.scopes,
        layers=query.layers,
        memory_types=query.memory_types,
        query_anchors=(),
        query_tokens=(),
    )


def _dedupe_snapshots(
    snapshots: Iterable[AgentMemorySnapshot],
) -> list[AgentMemorySnapshot]:
    deduped: list[AgentMemorySnapshot] = []
    seen: set[str] = set()
    for snapshot in snapshots:
        if snapshot.memory_id in seen:
            continue
        seen.add(snapshot.memory_id)
        deduped.append(snapshot)
    return deduped


def _archival_hard_filters(
    *,
    target_id: str,
    phase: str,
    plan: MemoryRetrievalPlan | None,
    forbidden_terms: tuple[str, ...],
) -> tuple[MemoryHardFilter, ...]:
    return (
        MemoryHardFilter(
            "subject_is_player",
            lambda snapshot: snapshot.subject_id == "player",
        ),
        MemoryHardFilter(
            "scope_allowed",
            lambda snapshot: _scope_allowed(
                snapshot,
                enforce_target_visibility=True,
            ),
        ),
        MemoryHardFilter(
            "visible_to_target",
            lambda snapshot: _visible_to_target(snapshot, target_id),
        ),
        MemoryHardFilter("archival_layer", _archival_layer_allowed),
        MemoryHardFilter("has_source_event_ids", _source_allowed),
        MemoryHardFilter(
            "phase_allowed",
            lambda snapshot: _phase_allowed(snapshot, phase),
        ),
        MemoryHardFilter(
            "plan_allowed",
            lambda snapshot: memory_allowed_by_plan(
                snapshot,
                plan,
                allow_archival_layer=_plan_allows_archival_cold_recall(plan),
            ),
        ),
        MemoryHardFilter(
            "forbidden_text_absent",
            lambda snapshot: not memory_content_matches_forbidden(
                snapshot,
                forbidden_terms,
            ),
        ),
    )


def _plan_allows_archival_cold_recall(plan: MemoryRetrievalPlan | None) -> bool:
    return plan is None or not plan.npc_skill_policy_ids


def _filter_snapshots(
    snapshots: list[AgentMemorySnapshot],
    hard_filters: tuple[MemoryHardFilter, ...],
) -> list[AgentMemorySnapshot]:
    return [
        snapshot
        for snapshot in snapshots
        if all(hard_filter.predicate(snapshot) for hard_filter in hard_filters)
    ]


def _retrieval_trace_summary(
    *,
    session: SessionState,
    filters: tuple[MemoryHardFilter, ...],
    store_candidate_count: int,
    hard_filter_candidate_count: int,
    scored_count: int,
    authority_selected_count: int,
    selected_count: int,
) -> MemoryRetrievalTraceSummary:
    total_snapshot_count = len(session.memory_snapshots)
    filter_counts = _hard_filter_rejection_counts(
        list(session.memory_snapshots.values()),
        filters,
    )
    return MemoryRetrievalTraceSummary(
        total_snapshot_count=total_snapshot_count,
        store_candidate_count=store_candidate_count,
        hard_filter_candidate_count=hard_filter_candidate_count,
        scored_count=scored_count,
        authority_selected_count=authority_selected_count,
        selected_count=selected_count,
        zero_reason=_zero_reason(
            total_snapshot_count=total_snapshot_count,
            hard_filter_candidate_count=hard_filter_candidate_count,
            scored_count=scored_count,
            authority_selected_count=authority_selected_count,
            selected_count=selected_count,
        ),
        filter_counts=filter_counts,
    )


def _hard_filter_rejection_counts(
    snapshots: list[AgentMemorySnapshot],
    filters: tuple[MemoryHardFilter, ...],
) -> dict[str, int]:
    counts = {hard_filter.name: 0 for hard_filter in filters}
    for snapshot in snapshots:
        for hard_filter in filters:
            if hard_filter.predicate(snapshot):
                continue
            counts[hard_filter.name] += 1
            break
    return counts


def _zero_reason(
    *,
    total_snapshot_count: int,
    hard_filter_candidate_count: int,
    scored_count: int,
    authority_selected_count: int,
    selected_count: int,
) -> str | None:
    if selected_count > 0:
        return None
    if total_snapshot_count == 0:
        return "no_memory_snapshots"
    if hard_filter_candidate_count == 0:
        return "all_candidates_filtered"
    if scored_count == 0:
        return "no_relevant_score"
    if authority_selected_count == 0:
        return "authority_filtered"
    return "selection_empty"


def _tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in LATIN_TOKEN_PATTERN.findall(text):
        tokens.update(_identifier_token_parts(token))
    for run in CJK_RUN_PATTERN.findall(text):
        if len(run) >= 2:
            tokens.add(run)
        for size in (2, 3):
            if len(run) < size:
                continue
            for index in range(0, len(run) - size + 1):
                tokens.add(run[index : index + size])
    return {token for token in tokens if _token_allowed(token)}


def memory_allowed_by_plan(
    snapshot: object,
    plan: MemoryRetrievalPlan | None,
    *,
    allow_archival_layer: bool = False,
) -> bool:
    if plan is None:
        return True
    memory_type = str(getattr(snapshot, "memory_type", "episodic"))
    memory_scope = str(getattr(snapshot, "memory_scope", "npc_private"))
    memory_layer = str(getattr(snapshot, "memory_layer", "working"))
    layer_included = memory_layer in set(plan.included_layers)
    layer_forbidden = memory_layer in set(plan.forbidden_layers)
    if allow_archival_layer and memory_layer == "archival":
        layer_included = True
        layer_forbidden = False
    return (
        memory_type in set(plan.included_memory_types)
        and memory_scope in set(plan.included_scopes)
        and layer_included
        and memory_scope not in set(plan.forbidden_scopes)
        and not layer_forbidden
        and _topic_tags_allowed(snapshot, plan.included_topic_tags)
    )


def _topic_tags_allowed(
    snapshot: object,
    included_topic_tags: tuple[str, ...],
) -> bool:
    if not included_topic_tags:
        return True
    metadata = getattr(snapshot, "metadata", {})
    if not isinstance(metadata, dict):
        return False
    raw_tags = metadata.get("topic_tags", [])
    if not isinstance(raw_tags, list):
        return False
    return bool({str(item) for item in raw_tags} & set(included_topic_tags))


def memory_content_matches_forbidden(
    snapshot: object,
    forbidden_terms: tuple[str, ...],
) -> bool:
    content = _normalize_text(str(getattr(snapshot, "content", "")))
    return any(
        normalized_term and normalized_term in content
        for normalized_term in (_normalize_text(term) for term in forbidden_terms)
    )


def _forbidden_terms(case: CasePackage) -> tuple[str, ...]:
    terms: list[str] = []
    for fact in case.forbidden_facts:
        terms.append(fact.text)
        terms.extend(fact.blocked_terms)
    return tuple(term for term in terms if term)


def _visible_to_target(snapshot: AgentMemorySnapshot, target_id: str) -> bool:
    if snapshot.memory_scope in {"case", "session"}:
        return (
            not snapshot.visible_to_character_ids
            or snapshot.owner_character_id == target_id
            or target_id in set(snapshot.visible_to_character_ids)
        )
    if snapshot.memory_scope == "npc_private":
        return (
            snapshot.owner_character_id == target_id
            or target_id in set(snapshot.visible_to_character_ids)
        )
    if snapshot.memory_scope == "scene_shared":
        return (
            target_id in set(snapshot.visible_to_character_ids)
            or snapshot.owner_character_id == target_id
        )
    return False


def _scope_allowed(
    snapshot: AgentMemorySnapshot,
    *,
    enforce_target_visibility: bool,
) -> bool:
    allowed_scopes = (
        AGENT_MEMORY_SCOPES
        if enforce_target_visibility
        else DIRECTOR_MEMORY_SCOPES
    )
    return snapshot.memory_scope in allowed_scopes


def _layer_allowed(snapshot: AgentMemorySnapshot) -> bool:
    if snapshot.memory_scope == "case":
        return snapshot.memory_layer == "core"
    if snapshot.memory_scope == "session":
        return snapshot.memory_layer == "working"
    return snapshot.memory_layer != "archival"


def _archival_layer_allowed(snapshot: AgentMemorySnapshot) -> bool:
    return snapshot.memory_layer == "archival"


def _source_allowed(snapshot: AgentMemorySnapshot) -> bool:
    return bool(snapshot.source_event_ids)


def _phase_allowed(snapshot: AgentMemorySnapshot, phase: str) -> bool:
    metadata = snapshot.metadata
    phase_id = metadata.get("phase_id")
    if phase_id is not None and str(phase_id) != phase:
        return False
    phase_ids = metadata.get("phase_ids")
    if isinstance(phase_ids, list) and phase not in {str(item) for item in phase_ids}:
        return False
    return True


def _build_query(case: CasePackage, action: PlayerAction) -> MemorySearchQuery:
    raw_anchors = [
        item
        for item in (
            action.clue_id,
            action.claim_id,
            action.subject_id,
            *(action.evidence_clue_ids or []),
        )
        if item is not None
    ]
    action_text = action.text or ""
    action_text_normalized = _normalize_text(action_text)
    action_tokens = _tokens(action_text)
    semantic_tokens = set(action_tokens)
    concept_aliases = _case_semantic_concept_aliases(case)
    normalized_raw_anchors = {
        normalized
        for normalized in (_normalize_text(str(anchor)) for anchor in raw_anchors)
        if normalized
    }
    matched_clue_ids: set[str] = set()
    matched_world_info_ids: set[str] = set()

    for clue in case.clues:
        clue_id = _normalize_text(clue.id)
        if (
            clue_id in normalized_raw_anchors
            or _case_alias_matches_query(
                action_text_normalized,
                action_tokens,
                _semantic_aliases_for_id(concept_aliases, clue.id),
            )
        ):
            matched_clue_ids.add(clue.id)
            matched_world_info_ids.update(clue.reveals_world_info)

    for world_info in case.world_info:
        world_info_id = _normalize_text(world_info.id)
        if (
            world_info_id in normalized_raw_anchors
            or _case_alias_matches_query(
                action_text_normalized,
                action_tokens,
                _semantic_aliases_for_id(concept_aliases, world_info.id),
            )
        ):
            matched_world_info_ids.add(world_info.id)

    if matched_world_info_ids:
        matched_world_info_id_set = {
            _normalize_text(world_info_id) for world_info_id in matched_world_info_ids
        }
        for clue in case.clues:
            if matched_world_info_id_set & {
                _normalize_text(world_info_id)
                for world_info_id in clue.reveals_world_info
            }:
                matched_clue_ids.add(clue.id)

    raw_anchors.extend(sorted(matched_clue_ids))
    raw_anchors.extend(sorted(matched_world_info_ids))
    for anchor in raw_anchors:
        semantic_tokens.update(
            _tokens(" ".join(_semantic_aliases_for_id(concept_aliases, anchor)))
        )

    return MemorySearchQuery(
        anchors=frozenset(
            anchor
            for anchor in (_normalize_text(str(item)) for item in raw_anchors)
            if anchor
        ),
        text_tokens=frozenset(action_tokens),
        semantic_tokens=frozenset(semantic_tokens),
        target_id=_normalize_text(action.target_id) or None,
    )


def _case_semantic_concept_aliases(
    case: CasePackage,
) -> dict[str, tuple[str, ...]]:
    aliases: dict[str, tuple[str, ...]] = {
        _normalize_text(concept): tuple(values)
        for concept, values in DEFAULT_LOCAL_SEMANTIC_CONCEPT_ALIASES.items()
        if _normalize_text(concept)
    }
    world_info_by_id = {
        _normalize_text(world_info.id): world_info
        for world_info in case.world_info
    }

    for world_info in case.world_info:
        _merge_semantic_aliases(
            aliases,
            world_info.id,
            _world_info_alias_strings(world_info),
        )

    for clue in case.clues:
        clue_aliases = list(_clue_alias_strings(clue))
        for world_info_id in clue.reveals_world_info:
            world_info = world_info_by_id.get(_normalize_text(world_info_id))
            if world_info is not None:
                clue_aliases.extend(_world_info_alias_strings(world_info))
        _merge_semantic_aliases(aliases, clue.id, clue_aliases)
        for world_info_id in clue.reveals_world_info:
            _merge_semantic_aliases(aliases, world_info_id, clue_aliases)

    return aliases


def _merge_semantic_aliases(
    aliases: dict[str, tuple[str, ...]],
    concept: str,
    values: Iterable[str],
) -> None:
    normalized_concept = _normalize_text(str(concept))
    if not normalized_concept:
        return
    aliases[normalized_concept] = _dedupe_strings(
        [
            *aliases.get(normalized_concept, ()),
            str(concept),
            *values,
        ]
    )


def _semantic_aliases_for_id(
    concept_aliases: dict[str, tuple[str, ...]],
    concept_id: object,
) -> tuple[str, ...]:
    return concept_aliases.get(_normalize_text(str(concept_id)), ())


def _clue_alias_strings(clue: ClueConfig) -> tuple[str, ...]:
    return _dedupe_strings(
        [
            clue.id,
            clue.title,
            clue.description,
            *clue.reveals_world_info,
        ]
    )


def _world_info_alias_strings(world_info: WorldInfoConfig) -> tuple[str, ...]:
    return _dedupe_strings(
        [
            world_info.id,
            world_info.title,
            world_info.description,
            *world_info.aliases,
            *world_info.claim_patterns,
        ]
    )


def _dedupe_strings(values: Iterable[object]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        normalized = _normalize_text(text)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(text)
    return tuple(deduped)


def _case_alias_matches_query(
    action_text_normalized: str,
    action_tokens: set[str],
    aliases: Iterable[str],
) -> bool:
    for alias in aliases:
        normalized_alias = _normalize_text(alias)
        if normalized_alias and normalized_alias in action_text_normalized:
            return True
        alias_tokens = _tokens(alias)
        overlap = action_tokens & alias_tokens
        if _semantic_overlap_is_match(overlap):
            return True
    return False


def _semantic_overlap_is_match(tokens: set[str]) -> bool:
    distinctive = {token for token in tokens if token not in LOCAL_SEMANTIC_WEAK_TOKENS}
    if len(distinctive) >= 2:
        return True
    if not distinctive:
        return False
    token = next(iter(distinctive))
    return bool(CJK_RUN_PATTERN.fullmatch(token)) or len(token) >= 7


def _structured_score(snapshot: AgentMemorySnapshot, query: MemorySearchQuery) -> float:
    score = 0.0
    metadata_values = _metadata_string_values(snapshot.metadata)
    source_event_ids = [_normalize_text(item) for item in snapshot.source_event_ids]
    source_memory_ids = [_normalize_text(item) for item in snapshot.source_memory_ids]
    memory_id = _normalize_text(snapshot.memory_id)
    for anchor in query.anchors:
        if anchor in metadata_values:
            score += 3.0
            continue
        if any(
            _identifier_contains(source_event_id, anchor)
            for source_event_id in source_event_ids
        ):
            score += 2.75
            continue
        if any(
            _identifier_contains(source_memory_id, anchor)
            for source_memory_id in source_memory_ids
        ):
            score += 2.5
            continue
        if _identifier_contains(memory_id, anchor):
            score += 1.5
    if not query.anchors:
        score += _target_relevance_score(snapshot, query.target_id)
    return min(score, STRUCTURED_SCORE_CAP)


def _target_relevance_score(
    snapshot: AgentMemorySnapshot,
    target_id: str | None,
) -> float:
    if not target_id:
        return 0.0
    if _normalize_text(snapshot.owner_character_id or "") == target_id:
        return 1.25
    if snapshot.memory_scope in {"npc_private", "scene_shared"} and target_id in {
        _normalize_text(item) for item in snapshot.visible_to_character_ids
    }:
        return 1.0
    return 0.0


def _snapshot_haystack(snapshot: AgentMemorySnapshot) -> str:
    values = [
        snapshot.memory_id,
        snapshot.content,
        *snapshot.source_event_ids,
        *snapshot.source_memory_ids,
        *(_stringify_metadata_value(value) for value in snapshot.metadata.values()),
    ]
    return _normalize_text(" ".join(value for value in values if value))


def _metadata_string_values(metadata: dict[str, object]) -> set[str]:
    values: set[str] = set()
    for value in metadata.values():
        for item in _metadata_value_strings(value):
            normalized = _normalize_text(item)
            if normalized:
                values.add(normalized)
    return values


def _metadata_value_strings(value: object) -> list[str]:
    if isinstance(value, dict):
        values: list[str] = []
        for item in value.values():
            values.extend(_metadata_value_strings(item))
        values.append(_stringify_metadata_value(value))
        return values
    if isinstance(value, list):
        values = []
        for item in value:
            values.extend(_metadata_value_strings(item))
        values.append(_stringify_metadata_value(value))
        return values
    if value is None:
        return []
    return [str(value)]


def _stringify_metadata_value(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(_stringify_metadata_value(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_stringify_metadata_value(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _identifier_contains(identifier: str, anchor: str) -> bool:
    if not identifier or not anchor:
        return False
    if identifier == anchor:
        return True
    identifier_parts = _identifier_token_parts(identifier)
    if anchor in identifier_parts:
        return True
    anchor_parts = _identifier_token_parts(anchor)
    return bool(anchor_parts) and anchor_parts <= identifier_parts


def _identifier_token_parts(identifier: str) -> set[str]:
    parts: set[str] = set()
    for chunk in IDENTIFIER_CHUNK_PATTERN.split(identifier):
        if not chunk:
            continue
        _add_token(parts, chunk)
        collapsed = chunk.replace("_", "")
        _add_token(parts, collapsed)
        for part in chunk.split("_"):
            _add_token(parts, part)
            for camel_part in CAMEL_CASE_BOUNDARY_PATTERN.sub(" ", part).split():
                _add_token(parts, camel_part)
    return {part for part in parts if _token_allowed(part)}


def _add_token(tokens: set[str], token: str) -> None:
    normalized = token.casefold().strip("_")
    if normalized:
        tokens.add(normalized)
        tokens.update(_latin_stem_variants(normalized))


def _latin_stem_variants(token: str) -> set[str]:
    if not token.isascii() or not token.isalnum():
        return set()
    variants: set[str] = set()
    handled_plural = False
    if len(token) > 5 and token.endswith("ies"):
        variants.add(f"{token[:-3]}y")
        handled_plural = True
    if len(token) > 5 and (
        token.endswith("ches")
        or token.endswith("shes")
        or token.endswith("xes")
        or token.endswith("zes")
    ):
        variants.add(token[:-2])
        handled_plural = True
    if len(token) > 5 and token.endswith("ed"):
        base = token[:-2]
        variants.add(base)
        if len(base) > 2 and base[-1] == base[-2]:
            variants.add(base[:-1])
    if len(token) > 4 and token.endswith("s") and not handled_plural:
        variants.add(token[:-1])
    return {variant for variant in variants if len(variant) >= 2}


def _token_allowed(token: str) -> bool:
    if len(token) < 2:
        return False
    return token not in LATIN_STOPWORDS


def _recency_score(
    snapshot: AgentMemorySnapshot,
    now: datetime | None,
) -> float:
    if now is None:
        return 0.0
    updated_at = _parse_datetime(snapshot.updated_at or snapshot.created_at)
    if updated_at is None:
        return 0.0
    age_seconds = max(0.0, (now - updated_at).total_seconds())
    for max_age, score in RECENCY_BUCKETS:
        if age_seconds <= max_age:
            return score
    return 0.0


def _reinforcement_score(snapshot: AgentMemorySnapshot) -> float:
    unique_event_count = len({event_id for event_id in snapshot.source_event_ids if event_id})
    if unique_event_count <= 1:
        return 0.0
    return min(0.75, (unique_event_count - 1) * 0.25)


def _retrieval_now(
    session: SessionState,
    snapshots: list[AgentMemorySnapshot],
) -> datetime | None:
    if session.events:
        event_time = _parse_datetime(session.events[-1].created_at)
        if event_time is not None:
            return event_time
    parsed_snapshot_times = [
        parsed
        for parsed in (
            _parse_datetime(snapshot.updated_at or snapshot.created_at)
            for snapshot in snapshots
        )
        if parsed is not None
    ]
    if not parsed_snapshot_times:
        return None
    return max(parsed_snapshot_times)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())
