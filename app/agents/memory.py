from __future__ import annotations

import re
from datetime import UTC, datetime

from app.agents.memory_retrieval import (
    EmbeddingScorer,
    LocalBM25KeywordScorer,
    MemoryHardFilter,
    MemoryReranker,
    MemoryRetrievalPipeline,
    MemorySearchQuery,
    MemorySearchResult,
)
from app.agents.retrieval_planner import MemoryRetrievalPlan
from app.domain.models import (
    AgentMemorySnapshot,
    CasePackage,
    PlayerAction,
    SessionState,
)

AGENT_MEMORY_SCOPES = {"case", "session", "npc_private", "scene_shared"}
DIRECTOR_MEMORY_SCOPES = AGENT_MEMORY_SCOPES | {"director_audit"}
LATIN_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]{3,}")
CJK_RUN_PATTERN = re.compile(r"[\u4e00-\u9fff]+")
RECENCY_BUCKETS = (
    (60 * 60, 0.8),
    (24 * 60 * 60, 0.65),
    (3 * 24 * 60 * 60, 0.4),
    (7 * 24 * 60 * 60, 0.2),
)
TEXT_SCORE_CAP = 1.5
STRUCTURED_SCORE_CAP = 5.0


class MemoryRetriever:
    def __init__(
        self,
        *,
        max_results: int = 8,
        embedding_scorer: EmbeddingScorer | None = None,
        reranker: MemoryReranker | None = None,
    ) -> None:
        self._max_results = max_results
        self._embedding_scorer = embedding_scorer
        self._reranker = reranker

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
        if max_results <= 0:
            return []

        query = _build_query(case, action)
        forbidden_terms = _forbidden_terms(case) if enforce_target_visibility else ()
        snapshots = list(session.memory_snapshots.values())
        working_filters = _working_hard_filters(
            enforce_target_visibility=enforce_target_visibility,
            target_id=action.target_id,
            phase=session.narrative.phase,
            plan=plan,
            forbidden_terms=forbidden_terms,
        )
        working_candidates = _filter_snapshots(snapshots, working_filters)
        scored = self._search_candidates(
            snapshots=snapshots,
            query=query,
            now=_retrieval_now(session, working_candidates),
            hard_filters=working_filters,
        )
        if scored or not enforce_target_visibility:
            return [result.snapshot for result in scored[:max_results]]

        archival_filters = _archival_hard_filters(
            target_id=action.target_id,
            phase=session.narrative.phase,
            plan=plan,
            forbidden_terms=forbidden_terms,
        )
        archival_candidates = _filter_snapshots(snapshots, archival_filters)
        archival_scored = self._search_candidates(
            snapshots=snapshots,
            query=query,
            now=_retrieval_now(session, archival_candidates),
            hard_filters=archival_filters,
        )
        return [result.snapshot for result in archival_scored[:max_results]]

    def _search_candidates(
        self,
        *,
        snapshots: list[AgentMemorySnapshot],
        query: MemorySearchQuery,
        now: datetime | None,
        hard_filters: tuple[MemoryHardFilter, ...],
    ) -> list[MemorySearchResult]:
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
            embedding_scorer=self._embedding_scorer,
            reranker=self._reranker,
        )
        return pipeline.search(
            query=query,
            snapshots=snapshots,
            hard_filters=hard_filters,
        )


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
            "forbidden_content_absent",
            lambda snapshot: not memory_content_matches_forbidden(
                snapshot,
                forbidden_terms,
            ),
        ),
    )


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
                allow_archival_layer=True,
            ),
        ),
        MemoryHardFilter(
            "forbidden_content_absent",
            lambda snapshot: not memory_content_matches_forbidden(
                snapshot,
                forbidden_terms,
            ),
        ),
    )


def _filter_snapshots(
    snapshots: list[AgentMemorySnapshot],
    hard_filters: tuple[MemoryHardFilter, ...],
) -> list[AgentMemorySnapshot]:
    return [
        snapshot
        for snapshot in snapshots
        if all(hard_filter.predicate(snapshot) for hard_filter in hard_filters)
    ]


def _tokens(text: str) -> set[str]:
    normalized = _normalize_text(text)
    tokens = {token.casefold() for token in LATIN_TOKEN_PATTERN.findall(normalized)}
    for run in CJK_RUN_PATTERN.findall(text):
        if len(run) >= 2:
            tokens.add(run)
        for size in (2, 3):
            if len(run) < size:
                continue
            for index in range(0, len(run) - size + 1):
                tokens.add(run[index : index + size])
    return {token for token in tokens if len(token) >= 2}


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
    )


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
        action.clue_id,
        action.claim_id,
        action.subject_id,
        *(action.evidence_clue_ids or []),
    ]
    action_text = action.text or ""
    action_text_normalized = _normalize_text(action_text)
    action_tokens = _tokens(action_text)
    for clue in case.clues:
        clue_title = _normalize_text(clue.title)
        clue_id = _normalize_text(clue.id)
        title_tokens = _tokens(clue.title)
        if (
            clue_id in action_text_normalized
            or (clue_title and clue_title in action_text_normalized)
            or bool(title_tokens & action_tokens)
        ):
            raw_anchors.append(clue.id)
            raw_anchors.extend(clue.reveals_world_info)
    return MemorySearchQuery(
        anchors=frozenset(
            anchor
            for anchor in (_normalize_text(str(item)) for item in raw_anchors)
            if anchor
        ),
        text_tokens=frozenset(action_tokens),
    )


def _structured_score(snapshot: AgentMemorySnapshot, query: MemorySearchQuery) -> float:
    if not query.anchors:
        return 0.0
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
    return min(score, STRUCTURED_SCORE_CAP)


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
    return anchor in {
        part
        for part in re.split(r"[^A-Za-z0-9_]+", identifier)
        if part
    }


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
