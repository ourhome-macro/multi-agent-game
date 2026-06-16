from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.agents.memory_retrieval import MemorySearchResult
from app.domain.models import AgentMemorySnapshot

HIGH_IMPACT_MEMORY_TYPES = frozenset({"belief", "relationship", "strategy"})
MIN_HIGH_IMPACT_CONFIDENCE = 0.5
AUTHORITY_SOURCE_RANKS = {
    "system_rule": 90,
    "rule_derived": 80,
    "player_evidence": 70,
    "player_action": 65,
    "world_event": 60,
    "npc_direct": 50,
    "archival": 40,
    "llm_summary": 25,
    "npc_hearsay": 10,
}
DEFAULT_AUTHORITY_SOURCE_RANK = 45


@dataclass(frozen=True)
class MemoryAuthorityProfile:
    authoritative: bool
    authority_rank: int
    authority_source: str
    confidence: float
    source_event_count: int
    has_rule: bool
    updated_at: str
    memory_id: str

    @property
    def sort_key(self) -> tuple[bool, int, float, int, bool, str, str]:
        return (
            self.authoritative,
            self.authority_rank,
            self.confidence,
            self.source_event_count,
            self.has_rule,
            self.updated_at,
            self.memory_id,
        )


@dataclass(frozen=True)
class MemoryConflictResolutionTrace:
    conflict_key: tuple[str, ...]
    winner_memory_id: str
    dropped_memory_ids: tuple[str, ...]
    reason: str
    category: str = "high_impact_memory_conflict"

    def to_projection(self) -> dict[str, object]:
        return {
            "category": self.category,
            "reason": self.reason,
            "conflict_key": list(self.conflict_key),
            "winner_memory_id": self.winner_memory_id,
            "dropped_memory_ids": list(self.dropped_memory_ids),
        }


@dataclass(frozen=True)
class MemoryAuthorityTraceSummary:
    memory_conflict_resolution: tuple[MemoryConflictResolutionTrace, ...] = ()

    def to_projection(self) -> dict[str, object]:
        return {
            "memory_conflict_resolution": [
                resolution.to_projection()
                for resolution in self.memory_conflict_resolution
            ],
        }


@dataclass(frozen=True)
class MemoryAuthorityResolutionResult:
    results: list[MemorySearchResult]
    trace_summary: MemoryAuthorityTraceSummary


def resolve_authoritative_memory_results(
    results: list[MemorySearchResult],
) -> list[MemorySearchResult]:
    return resolve_authoritative_memory_results_with_trace(results).results


def resolve_authoritative_memory_results_with_trace(
    results: list[MemorySearchResult],
) -> MemoryAuthorityResolutionResult:
    """Gate weak high-impact memories and isolate conflicting belief surfaces.

    Scope, visibility, source provenance, phase and forbidden-content checks have
    already happened before this function runs. This layer only decides which
    already-eligible memories are safe to project into an NPC context together.
    """

    eligible = [
        result for result in results if _passes_high_impact_authority_gate(result.snapshot)
    ]
    winners_by_key: dict[tuple[str, ...], MemorySearchResult] = {}
    results_by_key: dict[tuple[str, ...], list[MemorySearchResult]] = defaultdict(list)

    for result in eligible:
        conflict_key = memory_conflict_key(result.snapshot)
        if conflict_key is None:
            continue
        results_by_key[conflict_key].append(result)
        current = winners_by_key.get(conflict_key)
        if current is None or _authority_winner(result, current) is result:
            winners_by_key[conflict_key] = result

    winners = set(id(result) for result in winners_by_key.values())
    filtered = [
        result
        for result in eligible
        if memory_conflict_key(result.snapshot) is None or id(result) in winners
    ]
    return MemoryAuthorityResolutionResult(
        results=filtered,
        trace_summary=MemoryAuthorityTraceSummary(
            memory_conflict_resolution=_conflict_resolution_traces(
                results_by_key,
                winners_by_key,
            ),
        ),
    )


def memory_conflict_key(snapshot: AgentMemorySnapshot) -> tuple[str, ...] | None:
    memory_type = snapshot.memory_type
    if memory_type not in HIGH_IMPACT_MEMORY_TYPES:
        return None

    metadata = snapshot.metadata
    owner = snapshot.owner_character_id or ""
    subject = snapshot.subject_id or ""
    if memory_type == "belief":
        belief_subject = _metadata_text(metadata.get("belief_subject"))
        if belief_subject is not None:
            return (memory_type, owner, subject, "belief_subject", belief_subject)
    if memory_type == "strategy":
        strategy_id = _metadata_text(metadata.get("strategy_id"))
        if strategy_id is not None:
            return (memory_type, owner, subject, "strategy_id", strategy_id)

    world_info_id = _metadata_text(metadata.get("world_info_id"))
    if world_info_id is not None:
        return (memory_type, owner, subject, "world_info_id", world_info_id)
    clue_id = _metadata_text(metadata.get("clue_id"))
    if clue_id is not None:
        return (memory_type, owner, subject, "clue_id", clue_id)
    return None


def memory_authority_profile(snapshot: AgentMemorySnapshot) -> MemoryAuthorityProfile:
    source_event_ids = {event_id for event_id in snapshot.source_event_ids if event_id}
    non_authoritative = snapshot.metadata.get("non_authoritative") is True
    authority_source = _authority_source(snapshot)
    return MemoryAuthorityProfile(
        authoritative=bool(source_event_ids) and not non_authoritative,
        authority_rank=AUTHORITY_SOURCE_RANKS.get(
            authority_source,
            DEFAULT_AUTHORITY_SOURCE_RANK,
        ),
        authority_source=authority_source,
        confidence=snapshot.confidence,
        source_event_count=len(source_event_ids),
        has_rule=bool(snapshot.rule_id),
        updated_at=snapshot.updated_at or snapshot.created_at or "",
        memory_id=snapshot.memory_id,
    )


def _passes_high_impact_authority_gate(snapshot: AgentMemorySnapshot) -> bool:
    if snapshot.memory_type not in HIGH_IMPACT_MEMORY_TYPES:
        return True
    profile = memory_authority_profile(snapshot)
    if not profile.authoritative:
        return False
    return profile.confidence >= MIN_HIGH_IMPACT_CONFIDENCE


def _authority_winner(
    left: MemorySearchResult,
    right: MemorySearchResult,
) -> MemorySearchResult:
    left_profile = memory_authority_profile(left.snapshot)
    right_profile = memory_authority_profile(right.snapshot)
    if left_profile.sort_key != right_profile.sort_key:
        return left if left_profile.sort_key > right_profile.sort_key else right
    return left if left.score.sort_key > right.score.sort_key else right


def _conflict_resolution_traces(
    results_by_key: dict[tuple[str, ...], list[MemorySearchResult]],
    winners_by_key: dict[tuple[str, ...], MemorySearchResult],
) -> tuple[MemoryConflictResolutionTrace, ...]:
    traces: list[MemoryConflictResolutionTrace] = []
    for conflict_key in sorted(results_by_key):
        results = results_by_key[conflict_key]
        if len(results) < 2:
            continue
        winner = winners_by_key[conflict_key]
        dropped = [
            result.snapshot.memory_id
            for result in results
            if result.snapshot.memory_id != winner.snapshot.memory_id
        ]
        if not dropped:
            continue
        traces.append(
            MemoryConflictResolutionTrace(
                conflict_key=conflict_key,
                winner_memory_id=winner.snapshot.memory_id,
                dropped_memory_ids=tuple(sorted(dropped)),
                reason=_conflict_resolution_reason(winner, results),
            )
        )
    return tuple(traces)


def _conflict_resolution_reason(
    winner: MemorySearchResult,
    results: list[MemorySearchResult],
) -> str:
    winner_profile = memory_authority_profile(winner.snapshot)
    for result in results:
        if result is winner:
            continue
        if memory_authority_profile(result.snapshot).sort_key != winner_profile.sort_key:
            return "lower_authority_profile"
    return "lower_retrieval_score"


def _metadata_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _authority_source(snapshot: AgentMemorySnapshot) -> str:
    value = _metadata_text(snapshot.metadata.get("authority_source"))
    if value is not None:
        return value
    if snapshot.rule_id:
        return "rule_derived"
    if snapshot.memory_layer == "archival":
        return "archival"
    return "world_event"
