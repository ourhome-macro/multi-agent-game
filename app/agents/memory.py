from __future__ import annotations

import re

from app.agents.retrieval_planner import MemoryRetrievalPlan
from app.domain.models import (
    AgentMemorySnapshot,
    CasePackage,
    PlayerAction,
    SessionState,
)

AGENT_MEMORY_SCOPES = {"case", "session", "npc_private", "scene_shared"}
DIRECTOR_MEMORY_SCOPES = AGENT_MEMORY_SCOPES | {"director_audit"}


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
        scored = [
            (self._score(snapshot, action), snapshot)
            for snapshot in candidates
        ]
        scored = [(score, snapshot) for score, snapshot in scored if score > 0]
        if not scored:
            scored = [
                (snapshot.salience, snapshot)
                for snapshot in candidates
                if snapshot.salience > 0
            ]
        scored.sort(
            key=lambda item: (
                item[0],
                item[1].salience,
                item[1].updated_at or "",
                item[1].memory_id,
            ),
            reverse=True,
        )
        return [snapshot for _, snapshot in scored[:max_results]]

    def _score(self, snapshot: AgentMemorySnapshot, action: PlayerAction) -> float:
        haystack = f"{snapshot.memory_id} {snapshot.content}".lower()
        score = snapshot.salience
        direct_terms = [
            action.target_id,
            action.clue_id,
            action.claim_id,
            action.subject_id,
            *(action.evidence_clue_ids or []),
        ]
        for term in direct_terms:
            if term and term.lower() in haystack:
                score += 2.0
        for token in _tokens(action.text or ""):
            if token in haystack:
                score += 1.0
        return score if score > snapshot.salience else 0.0


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9_]{4,}", text)
    }


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
    content = str(getattr(snapshot, "content", ""))
    return any(term and term in content for term in forbidden_terms)


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
