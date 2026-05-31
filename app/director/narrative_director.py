from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.domain.models import (
    AgentContext,
    AgentIntent,
    CasePackage,
    DirectorDecision,
    DisclosureClaim,
    DisclosureMode,
    NarrativeState,
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


class NarrativeDirector:
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
            touched_decision = self._validate_touched_world_info(case, context, intent)
            if not touched_decision.allowed:
                return touched_decision
        return DirectorDecision(allowed=True)

    def _validate_disclosure_claims(
        self,
        context: AgentContext,
        intent: AgentIntent,
    ) -> DirectorDecision:
        constraints = _world_info_constraints_by_id(context)
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
        constraints = _world_info_constraints_by_id(context)
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


def _world_info_constraints_by_id(context: AgentContext) -> dict[str, object]:
    if context.inner_context is None:
        return {}
    return {
        strategy.world_info_id: strategy
        for strategy in context.inner_context.fact_disclosure_strategies
    }


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
