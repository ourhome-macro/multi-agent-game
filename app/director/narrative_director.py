from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.director.fact_gateway import (
    FactGateway,
    FactGatewaySummary,
    FactGatewayViolation,
)
from app.domain.models import (
    ActionType,
    AgentContext,
    AgentIntent,
    CasePackage,
    DirectorDecision,
    DisclosureClaim,
    DisclosureMode,
    FactDisclosureStrategy,
    NarrativeState,
    PlayerAction,
    SafeFactFragmentProjection,
    SessionState,
    SubjectType,
)

SAFE_SPEECH = "I cannot discuss that right now."


class MentionDirectness(StrEnum):
    HINT_LIKE = "hint_like"
    DIRECT_CLAIM = "direct_claim"


class MentionMatchedBy(StrEnum):
    TITLE = "title"
    ALIAS = "alias"
    PATTERN = "pattern"
    FORBIDDEN_TERM = "forbidden_term"


@dataclass(frozen=True)
class DetectedWorldInfoMention:
    world_info_id: str
    matched_by: MentionMatchedBy
    directness: MentionDirectness
    matched_text: str | None = None
    pattern_id: str | None = None


@dataclass(frozen=True)
class _DisclosureConstraintView:
    allowed_modes: tuple[DisclosureMode, ...]
    forbidden_modes: tuple[DisclosureMode, ...]
    must_not_claim: tuple[str, ...] = ()


class NarrativeDirector:
    def fact_gateway_summary(
        self,
        case: CasePackage,
        narrative: NarrativeState,
        context: AgentContext | None = None,
    ) -> FactGatewaySummary:
        return FactGateway(case=case, narrative=narrative, context=context).summarize()

    def safe_fragment_constraints(
        self,
        case: CasePackage,
        narrative: NarrativeState,
        context: AgentContext,
    ) -> tuple[SafeFactFragmentProjection, ...]:
        constraints = _world_info_constraints_by_id(context)
        skill_safe_fragment_refs = _skill_safe_fragment_refs(context)
        if not constraints and not skill_safe_fragment_refs:
            return ()
        allowed_world_info_ids = set(constraints) | _world_info_ids_from_fragment_refs(
            skill_safe_fragment_refs
        )
        projections = FactGateway(
            case=case,
            narrative=narrative,
            context=context,
        ).safe_fragment_projections(
            allowed_world_info_ids=allowed_world_info_ids,
        )
        safe_fragments: dict[str, SafeFactFragmentProjection] = {}
        for projection in projections:
            strategy = constraints.get(projection.world_info_id)
            strategy_projection = (
                _project_fragment_for_strategy(projection, strategy)
                if strategy is not None
                else None
            )
            if strategy_projection is not None:
                safe_fragments[strategy_projection.ref] = strategy_projection
                continue
            if projection.ref in skill_safe_fragment_refs:
                safe_fragments[projection.ref] = projection
        return tuple(safe_fragments.values())

    def precheck_player_action(
        self,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> DirectorDecision:
        if action.type == ActionType.ASK_ABOUT and action.subject_type == SubjectType.CLUE:
            knowledge_id = _player_knowledge_id_for_clue(case, str(action.subject_id))
            if (
                str(action.subject_id) not in session.discovered_clues
                and knowledge_id not in session.player_knowledge
            ):
                return DirectorDecision(allowed=False, reason="subject_not_discovered")

        if action.type == ActionType.PRESENT_CLUE:
            if str(action.clue_id) not in session.discovered_clues:
                return DirectorDecision(allowed=False, reason="clue_not_discovered")
            knowledge_id = _player_knowledge_id_for_clue(case, str(action.clue_id))
            if knowledge_id not in session.player_knowledge:
                return DirectorDecision(allowed=False, reason="clue_not_available")

        if action.type == ActionType.ACCUSE:
            claim = next(
                (item for item in case.solution_claims.claims if item.id == action.claim_id),
                None,
            )
            if claim is None:
                return DirectorDecision(allowed=False, reason="claim_unknown")
            if session.narrative.phase not in claim.allowed_phases:
                return DirectorDecision(allowed=False, reason="claim_not_available")
            if not action.evidence_clue_ids:
                return DirectorDecision(allowed=False, reason="insufficient_evidence")
            undiscovered = sorted(set(action.evidence_clue_ids) - session.discovered_clues)
            if undiscovered:
                return DirectorDecision(allowed=False, reason="evidence_not_discovered")

        return DirectorDecision(allowed=True)

    def validate(
        self,
        case: CasePackage,
        narrative: NarrativeState,
        intent: AgentIntent,
        context: AgentContext | None = None,
    ) -> DirectorDecision:
        normalized_speech = _normalize_text(intent.speech)
        for fact in case.forbidden_facts:
            if fact.reveal_phase is not None and fact.reveal_phase == narrative.phase:
                continue
            for term in fact.blocked_terms:
                if _normalize_text(term) in normalized_speech:
                    return DirectorDecision(
                        allowed=False,
                        reason=f"Blocked forbidden fact '{fact.id}' in phase '{narrative.phase}'",
                        blocked_fact_id=fact.id,
                        safe_speech=SAFE_SPEECH,
                        world_info_id=fact.world_info_id,
                        detected_directness=MentionDirectness.DIRECT_CLAIM,
                        matched_by=MentionMatchedBy.FORBIDDEN_TERM,
                        matched_text=term,
                        safe_fallback_used=True,
                    )
        if context is not None:
            disclosure_decision = self._validate_disclosure_claims(context, intent)
            if not disclosure_decision.allowed:
                return disclosure_decision
        fact_gateway = FactGateway(case=case, narrative=narrative, context=context)
        claim_violation = fact_gateway.validate_disclosure_claims(intent)
        if claim_violation is not None:
            return _blocked_fact_gateway_violation(claim_violation)
        speech_violation = fact_gateway.validate_speech(intent)
        if speech_violation is not None:
            return _blocked_fact_gateway_violation(speech_violation)
        if context is not None:
            touched_decision = self._validate_touched_world_info(case, context, intent)
            if not touched_decision.allowed:
                return touched_decision
        return DirectorDecision(allowed=True)

    def _validate_disclosure_claims(
        self,
        context: AgentContext,
        intent: AgentIntent,
    ) -> DirectorDecision:
        constraints = _disclosure_constraint_views_by_id(context)
        for claim in intent.disclosure_claims:
            constraint = constraints.get(claim.world_info_id)
            if constraint is None:
                return _blocked_disclosure(
                    claim,
                    (
                        f"Disclosure claim for world_info '{claim.world_info_id}' "
                        "has no allowed constraint"
                    ),
                )
            allowed_modes = set(constraint.allowed_modes)
            forbidden_modes = set(constraint.forbidden_modes)
            fragment_modes = _referenced_safe_fragment_modes(context, claim)
            if fragment_modes:
                allowed_modes.update(fragment_modes)
                forbidden_modes.difference_update(fragment_modes)
            if claim.mode == DisclosureMode.FULL:
                return _blocked_disclosure(
                    claim,
                    (
                        f"Disclosure claim for world_info '{claim.world_info_id}' "
                        "attempted full reveal"
                    ),
                )
            if claim.mode not in allowed_modes:
                return _blocked_disclosure(
                    claim,
                    (
                        f"Disclosure mode '{claim.mode}' for world_info "
                        f"'{claim.world_info_id}' is not allowed"
                    ),
                )
            if claim.mode in forbidden_modes:
                return _blocked_disclosure(
                    claim,
                    (
                        f"Disclosure mode '{claim.mode}' for world_info "
                        f"'{claim.world_info_id}' is forbidden"
                    ),
                )
            if set(claim.claim_refs) & set(constraint.must_not_claim):
                return _blocked_disclosure(
                    claim,
                    (
                        f"Disclosure claim for world_info '{claim.world_info_id}' "
                        "violates must_not_claim"
                    ),
                )
        return DirectorDecision(allowed=True)

    def _validate_touched_world_info(
        self,
        case: CasePackage,
        context: AgentContext,
        intent: AgentIntent,
    ) -> DirectorDecision:
        constraints = _disclosure_constraint_views_by_id(context)
        claims_by_world_info = {
            claim.world_info_id: claim for claim in intent.disclosure_claims
        }
        for mention in detect_world_info_mentions(intent.speech, case):
            claim = claims_by_world_info.get(mention.world_info_id)
            if claim is None:
                return _blocked_mention(
                    mention=mention,
                    reason=(
                        f"Speech touched world_info '{mention.world_info_id}' "
                        "without a disclosure claim"
                    ),
                )
            if mention.world_info_id not in constraints:
                return _blocked_disclosure(
                    claim,
                    (
                        f"Speech touched world_info '{mention.world_info_id}' "
                        "without an allowed constraint"
                    ),
                    mention=mention,
                )
            if _claim_mode_exceeds_mention(claim.mode, mention):
                return _blocked_disclosure(
                    claim,
                    (
                        f"Speech directness '{mention.directness}' exceeds "
                        f"disclosure mode '{claim.mode}'"
                    ),
                    mention=mention,
                )
        return DirectorDecision(allowed=True)


def detect_world_info_mentions(
    speech: str,
    case: CasePackage,
) -> list[DetectedWorldInfoMention]:
    normalized_speech = _normalize_text(speech)
    mentions: list[DetectedWorldInfoMention] = []
    for world_info in case.world_info:
        mentions.extend(
            _detect_literal_mentions(
                normalized_speech=normalized_speech,
                world_info_id=world_info.id,
                matched_by=MentionMatchedBy.TITLE,
                values=[world_info.title],
            )
        )
        mentions.extend(
            _detect_literal_mentions(
                normalized_speech=normalized_speech,
                world_info_id=world_info.id,
                matched_by=MentionMatchedBy.ALIAS,
                values=world_info.aliases,
            )
        )
        mentions.extend(
            _detect_pattern_mentions(
                speech=speech,
                world_info_id=world_info.id,
                patterns=world_info.claim_patterns,
            )
        )
    mentions.extend(_detect_forbidden_term_mentions(speech, case))
    return _dedupe_mentions(mentions)


def _world_info_constraints_by_id(context: AgentContext) -> dict[str, FactDisclosureStrategy]:
    if context.inner_context is None:
        return {}
    return {
        strategy.world_info_id: strategy
        for strategy in context.inner_context.fact_disclosure_strategies
    }


def _disclosure_constraint_views_by_id(
    context: AgentContext,
) -> dict[str, _DisclosureConstraintView]:
    constraints: dict[str, _DisclosureConstraintView] = {}
    if context.inner_context is not None:
        constraints.update(
            {
                strategy.world_info_id: _strategy_constraint_view(strategy)
                for strategy in context.inner_context.fact_disclosure_strategies
            }
        )
    for world_info_id, fragments in _safe_fragments_by_world_info(
        context.director_safe_fragments
    ).items():
        if world_info_id in constraints:
            continue
        constraints[world_info_id] = _safe_fragment_constraint_view(fragments)
    return constraints


def _strategy_constraint_view(
    strategy: FactDisclosureStrategy,
) -> _DisclosureConstraintView:
    return _DisclosureConstraintView(
        allowed_modes=tuple(strategy.allowed_modes),
        forbidden_modes=tuple(strategy.forbidden_modes),
        must_not_claim=tuple(strategy.must_not_claim),
    )


def _safe_fragment_constraint_view(
    fragments: list[SafeFactFragmentProjection],
) -> _DisclosureConstraintView:
    allowed_modes = {
        mode
        for fragment in fragments
        for mode in fragment.allowed_modes
        if mode != DisclosureMode.FULL
    }
    ordered_allowed_modes = tuple(
        mode
        for mode in DisclosureMode
        if mode in allowed_modes and mode != DisclosureMode.FULL
    )
    return _DisclosureConstraintView(
        allowed_modes=ordered_allowed_modes,
        forbidden_modes=tuple(
            mode
            for mode in DisclosureMode
            if mode == DisclosureMode.FULL or mode not in allowed_modes
        ),
    )


def _safe_fragments_by_world_info(
    safe_fragments: list[SafeFactFragmentProjection],
) -> dict[str, list[SafeFactFragmentProjection]]:
    grouped: dict[str, list[SafeFactFragmentProjection]] = {}
    for fragment in safe_fragments:
        grouped.setdefault(fragment.world_info_id, []).append(fragment)
    return grouped


def _skill_safe_fragment_refs(context: AgentContext) -> set[str]:
    return {
        ref
        for skill in context.npc_skill_projections
        for ref in skill.safe_fragment_refs
    }


def _world_info_ids_from_fragment_refs(refs: set[str]) -> set[str]:
    return {
        ref.split(".safe_fragment:", 1)[0]
        for ref in refs
        if ".safe_fragment:" in ref
    }


def _referenced_safe_fragment_modes(
    context: AgentContext,
    claim: DisclosureClaim,
) -> set[DisclosureMode]:
    refs = set(claim.claim_refs) | set(claim.source_refs)
    modes: set[DisclosureMode] = set()
    for fragment in context.director_safe_fragments:
        if fragment.world_info_id != claim.world_info_id:
            continue
        if not _claim_refs_match_projection(fragment, refs):
            continue
        modes.update(mode for mode in fragment.allowed_modes if mode != DisclosureMode.FULL)
    return modes


def _claim_refs_match_projection(
    fragment: SafeFactFragmentProjection,
    refs: set[str],
) -> bool:
    return bool(
        refs
        & {
            fragment.ref,
            fragment.fragment_id,
            f"safe_fragment:{fragment.fragment_id}",
            f"{fragment.world_info_id}.{fragment.fragment_id}",
            f"{fragment.world_info_id}:{fragment.fragment_id}",
            *fragment.source_refs,
        }
    )


def _project_fragment_for_strategy(
    projection: SafeFactFragmentProjection,
    strategy: FactDisclosureStrategy,
) -> SafeFactFragmentProjection | None:
    allowed_modes = [
        mode
        for mode in projection.allowed_modes
        if mode in set(strategy.allowed_modes)
        and mode not in set(strategy.forbidden_modes)
        and mode != DisclosureMode.FULL
    ]
    if not allowed_modes:
        return None
    return projection.model_copy(update={"allowed_modes": allowed_modes})


def _blocked_disclosure(
    claim: DisclosureClaim,
    reason: str,
    mention: DetectedWorldInfoMention | None = None,
) -> DirectorDecision:
    return DirectorDecision(
        allowed=False,
        reason=reason,
        blocked_fact_id=claim.world_info_id,
        safe_speech=SAFE_SPEECH,
        world_info_id=claim.world_info_id,
        claimed_mode=claim.mode,
        detected_directness=mention.directness if mention is not None else None,
        matched_by=mention.matched_by if mention is not None else None,
        matched_text=mention.matched_text if mention is not None else None,
        pattern_id=mention.pattern_id if mention is not None else None,
        safe_fallback_used=True,
    )


def _blocked_mention(
    *,
    mention: DetectedWorldInfoMention,
    reason: str,
) -> DirectorDecision:
    return DirectorDecision(
        allowed=False,
        reason=reason,
        blocked_fact_id=mention.world_info_id,
        safe_speech=SAFE_SPEECH,
        world_info_id=mention.world_info_id,
        detected_directness=mention.directness,
        matched_by=mention.matched_by,
        matched_text=mention.matched_text,
        pattern_id=mention.pattern_id,
        safe_fallback_used=True,
    )


def _blocked_fact_gateway_violation(
    violation: FactGatewayViolation,
) -> DirectorDecision:
    return DirectorDecision(
        allowed=False,
        reason=violation.reason,
        blocked_fact_id=violation.forbidden_inference_id
        or violation.fragment_id
        or violation.world_info_id,
        safe_speech=SAFE_SPEECH,
        world_info_id=violation.world_info_id,
        claimed_mode=violation.claimed_mode,
        detected_directness=MentionDirectness.DIRECT_CLAIM,
        matched_by=violation.matched_by,
        matched_text=violation.matched_text,
        pattern_id=violation.pattern_id,
        safe_fallback_used=True,
    )


def _detect_literal_mentions(
    *,
    normalized_speech: str,
    world_info_id: str,
    matched_by: MentionMatchedBy,
    values: list[str],
) -> list[DetectedWorldInfoMention]:
    mentions: list[DetectedWorldInfoMention] = []
    for value in values:
        normalized_value = _normalize_text(value)
        if not normalized_value or normalized_value not in normalized_speech:
            continue
        mentions.append(
            DetectedWorldInfoMention(
                world_info_id=world_info_id,
                matched_by=matched_by,
                matched_text=value,
                directness=MentionDirectness.DIRECT_CLAIM,
            )
        )
    return mentions


def _detect_pattern_mentions(
    *,
    speech: str,
    world_info_id: str,
    patterns: list[str],
) -> list[DetectedWorldInfoMention]:
    mentions: list[DetectedWorldInfoMention] = []
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, speech, flags=re.IGNORECASE)
        if match is None:
            continue
        mentions.append(
            DetectedWorldInfoMention(
                world_info_id=world_info_id,
                matched_by=MentionMatchedBy.PATTERN,
                matched_text=match.group(0),
                pattern_id=f"{world_info_id}.claim_patterns[{index}]",
                directness=MentionDirectness.DIRECT_CLAIM,
            )
        )
    return mentions


def _detect_forbidden_term_mentions(
    speech: str,
    case: CasePackage,
) -> list[DetectedWorldInfoMention]:
    normalized_speech = _normalize_text(speech)
    mentions: list[DetectedWorldInfoMention] = []
    for fact in case.forbidden_facts:
        if fact.world_info_id is None:
            continue
        for term in fact.blocked_terms:
            if _normalize_text(term) not in normalized_speech:
                continue
            mentions.append(
                DetectedWorldInfoMention(
                    world_info_id=fact.world_info_id,
                    matched_by=MentionMatchedBy.FORBIDDEN_TERM,
                    matched_text=term,
                    directness=MentionDirectness.DIRECT_CLAIM,
                )
            )
    return mentions


def _dedupe_mentions(
    mentions: list[DetectedWorldInfoMention],
) -> list[DetectedWorldInfoMention]:
    seen: set[tuple[str, MentionMatchedBy, str | None, str | None]] = set()
    deduped: list[DetectedWorldInfoMention] = []
    for mention in mentions:
        key = (
            mention.world_info_id,
            mention.matched_by,
            mention.matched_text,
            mention.pattern_id,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(mention)
    return deduped


def _claim_mode_exceeds_mention(
    mode: DisclosureMode,
    mention: DetectedWorldInfoMention,
) -> bool:
    if mention.directness != MentionDirectness.DIRECT_CLAIM:
        return False
    return mode in {
        DisclosureMode.NONE,
        DisclosureMode.DENY,
        DisclosureMode.DEFLECT,
        DisclosureMode.HINT,
    }


def _normalize_text(value: str) -> str:
    return value.casefold()


def _player_knowledge_id_for_clue(case: CasePackage, clue_id: str) -> str:
    clue = next((item for item in case.clues if item.id == clue_id), None)
    if clue is None:
        return f"player_knowledge.{clue_id}"
    world_info_ids = {item.id for item in case.world_info}
    world_info_id = next(
        (item_id for item_id in clue.reveals_world_info if item_id in world_info_ids),
        None,
    )
    if world_info_id is None:
        return f"player_knowledge.{clue_id}"
    return f"player_knowledge.{world_info_id}"
