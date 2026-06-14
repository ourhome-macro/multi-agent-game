from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

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


@dataclass(frozen=True)
class RetrievalQuery:
    anchors: frozenset[str]
    text_tokens: frozenset[str]


@dataclass(frozen=True)
class RetrievalScore:
    total: float
    structured: float
    text: float
    recency: float
    reinforcement: float
    salience: float
    confidence: float
    updated_at: str
    memory_id: str
    has_relevance: bool

    @property
    def sort_key(self) -> tuple[float, float, float, float, float, str, str]:
        return (
            self.total,
            self.structured,
            self.salience,
            self.reinforcement,
            self.confidence,
            self.updated_at,
            self.memory_id,
        )


class MemoryRetriever:
    def __init__(self, *, max_results: int = 8) -> None:
        self._max_results = max_results

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
        forbidden_terms = _forbidden_terms(case) if enforce_target_visibility else ()
        candidates = [
            snapshot
            for snapshot in session.memory_snapshots.values()
            if snapshot.subject_id == "player"
            and _scope_allowed(
                snapshot,
                enforce_target_visibility=enforce_target_visibility,
            )
            and (
                not enforce_target_visibility
                or _visible_to_target(snapshot, action.target_id)
            )
            and _layer_allowed(snapshot)
            and memory_allowed_by_plan(snapshot, plan)
            and not memory_content_matches_forbidden(snapshot, forbidden_terms)
        ]
        query = _build_query(case, action)
        now = _retrieval_now(session, candidates)
        scored = [
            (self._score(snapshot, query, now), snapshot)
            for snapshot in candidates
        ]
        scored = [
            (score, snapshot)
            for score, snapshot in scored
            if score.has_relevance
        ]
        if not scored:
            scored = [
                (_fallback_score(snapshot), snapshot)
                for snapshot in candidates
                if snapshot.salience > 0
            ]
        scored.sort(
            key=lambda item: item[0].sort_key,
            reverse=True,
        )
        return [snapshot for _, snapshot in scored[:max_results]]

    def _score(
        self,
        snapshot: AgentMemorySnapshot,
        query: RetrievalQuery,
        now: datetime | None,
    ) -> RetrievalScore:
        structured = _structured_score(snapshot, query)
        text = _text_score(snapshot, query)
        has_relevance = structured > 0 or text > 0
        recency = _recency_score(snapshot, now) if has_relevance else 0.0
        reinforcement = _reinforcement_score(snapshot) if has_relevance else 0.0
        confidence = snapshot.confidence * 0.15 if has_relevance else 0.0
        total = (
            snapshot.salience
            + structured
            + text
            + recency
            + reinforcement
            + confidence
        )
        return RetrievalScore(
            total=total if has_relevance else 0.0,
            structured=structured,
            text=text,
            recency=recency,
            reinforcement=reinforcement,
            salience=snapshot.salience,
            confidence=snapshot.confidence,
            updated_at=snapshot.updated_at or snapshot.created_at or "",
            memory_id=snapshot.memory_id,
            has_relevance=has_relevance,
        )


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
) -> bool:
    if plan is None:
        return True
    memory_type = str(getattr(snapshot, "memory_type", "episodic"))
    memory_scope = str(getattr(snapshot, "memory_scope", "npc_private"))
    memory_layer = str(getattr(snapshot, "memory_layer", "working"))
    return (
        memory_type in set(plan.included_memory_types)
        and memory_scope in set(plan.included_scopes)
        and memory_layer in set(plan.included_layers)
        and memory_scope not in set(plan.forbidden_scopes)
        and memory_layer not in set(plan.forbidden_layers)
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


def _build_query(case: CasePackage, action: PlayerAction) -> RetrievalQuery:
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
    return RetrievalQuery(
        anchors=frozenset(
            anchor
            for anchor in (_normalize_text(str(item)) for item in raw_anchors)
            if anchor
        ),
        text_tokens=frozenset(action_tokens),
    )


def _structured_score(snapshot: AgentMemorySnapshot, query: RetrievalQuery) -> float:
    if not query.anchors:
        return 0.0
    score = 0.0
    metadata_values = _metadata_string_values(snapshot.metadata)
    source_memory_ids = [_normalize_text(item) for item in snapshot.source_memory_ids]
    memory_id = _normalize_text(snapshot.memory_id)
    for anchor in query.anchors:
        if anchor in metadata_values:
            score += 3.0
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


def _text_score(snapshot: AgentMemorySnapshot, query: RetrievalQuery) -> float:
    if not query.text_tokens:
        return 0.0
    haystack = _snapshot_haystack(snapshot)
    score = 0.0
    for token in query.text_tokens:
        if token in haystack:
            score += 0.45
    return min(score, TEXT_SCORE_CAP)


def _snapshot_haystack(snapshot: AgentMemorySnapshot) -> str:
    values = [
        snapshot.memory_id,
        snapshot.content,
        *snapshot.source_memory_ids,
        *(_stringify_metadata_value(value) for value in snapshot.metadata.values()),
    ]
    return _normalize_text(" ".join(value for value in values if value))


def _metadata_string_values(metadata: dict[str, object]) -> set[str]:
    values: set[str] = set()
    for value in metadata.values():
        normalized = _normalize_text(_stringify_metadata_value(value))
        if normalized:
            values.add(normalized)
    return values


def _stringify_metadata_value(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(
            _stringify_metadata_value(item) for item in value.values()
        )
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


def _fallback_score(snapshot: AgentMemorySnapshot) -> RetrievalScore:
    return RetrievalScore(
        total=snapshot.salience,
        structured=0.0,
        text=0.0,
        recency=0.0,
        reinforcement=0.0,
        salience=snapshot.salience,
        confidence=snapshot.confidence,
        updated_at=snapshot.updated_at or snapshot.created_at or "",
        memory_id=snapshot.memory_id,
        has_relevance=False,
    )


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())
