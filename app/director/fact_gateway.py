from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.domain.models import (
    AgentContext,
    AgentIntent,
    CasePackage,
    DisclosureMode,
    FactUnlockConditionConfig,
    ForbiddenInferenceConfig,
    NarrativeState,
    SafeFactFragmentConfig,
    SafeFactFragmentProjection,
    WorldInfoConfig,
)


class FactGatewayMatchedBy(StrEnum):
    CLAIM_REF = "claim_ref"
    SAFE_FRAGMENT_ALIAS = "safe_fragment_alias"
    SAFE_FRAGMENT_PATTERN = "safe_fragment_pattern"
    FORBIDDEN_INFERENCE_ALIAS = "forbidden_inference_alias"
    FORBIDDEN_INFERENCE_PATTERN = "forbidden_inference_pattern"
    FORBIDDEN_INFERENCE_GRAPH = "forbidden_inference_graph"


@dataclass(frozen=True)
class FactGatewayFragmentSummary:
    world_info_id: str
    fragment_id: str
    unlocked: bool
    allowed_modes: tuple[DisclosureMode, ...]
    safe_summary: str | None = None
    blocked_reason: str | None = None


@dataclass(frozen=True)
class FactGatewayInferenceSummary:
    world_info_id: str
    inference_id: str
    blocked: bool
    trigger_fragment_ids: tuple[str, ...]
    trigger_world_info_ids: tuple[str, ...]


@dataclass(frozen=True)
class FactGatewaySummary:
    revealable_fragments: tuple[FactGatewayFragmentSummary, ...]
    blocked_fragments: tuple[FactGatewayFragmentSummary, ...]
    forbidden_inferences: tuple[FactGatewayInferenceSummary, ...]


@dataclass(frozen=True)
class DetectedFactFragmentMention:
    world_info_id: str
    fragment_id: str
    matched_by: FactGatewayMatchedBy
    matched_text: str | None = None
    pattern_id: str | None = None


@dataclass(frozen=True)
class DetectedForbiddenInferenceMention:
    world_info_id: str
    inference_id: str
    matched_by: FactGatewayMatchedBy
    matched_text: str | None = None
    pattern_id: str | None = None
    trigger_fragment_ids: tuple[str, ...] = ()
    trigger_world_info_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class FactGatewayViolation:
    reason: str
    world_info_id: str
    claimed_mode: DisclosureMode | None = None
    fragment_id: str | None = None
    forbidden_inference_id: str | None = None
    matched_by: FactGatewayMatchedBy | None = None
    matched_text: str | None = None
    pattern_id: str | None = None


class FactGateway:
    def __init__(
        self,
        *,
        case: CasePackage,
        narrative: NarrativeState,
        context: AgentContext | None = None,
    ) -> None:
        self._case = case
        self._narrative = narrative
        self._context = context
        self._world_info_by_id = {item.id: item for item in case.world_info}

    def summarize(self) -> FactGatewaySummary:
        revealable: list[FactGatewayFragmentSummary] = []
        blocked: list[FactGatewayFragmentSummary] = []
        forbidden: list[FactGatewayInferenceSummary] = []
        for world_info in self._case.world_info:
            for fragment in world_info.claim_graph.safe_fragments:
                unlocked = self._fragment_unlocked(fragment)
                summary = FactGatewayFragmentSummary(
                    world_info_id=world_info.id,
                    fragment_id=fragment.id,
                    unlocked=unlocked,
                    allowed_modes=tuple(fragment.allowed_modes),
                    safe_summary=fragment.summary if unlocked else None,
                    blocked_reason=None if unlocked else "unlock_conditions_not_met",
                )
                if unlocked:
                    revealable.append(summary)
                else:
                    blocked.append(summary)
            for inference in world_info.claim_graph.forbidden_inferences:
                forbidden.append(
                    FactGatewayInferenceSummary(
                        world_info_id=world_info.id,
                        inference_id=inference.id,
                        blocked=self._inference_blocked(inference),
                        trigger_fragment_ids=tuple(inference.trigger_fragment_ids),
                        trigger_world_info_ids=tuple(inference.trigger_world_info_ids),
                    )
                )
        return FactGatewaySummary(
            revealable_fragments=tuple(revealable),
            blocked_fragments=tuple(blocked),
            forbidden_inferences=tuple(forbidden),
        )

    def safe_fragment_projections(
        self,
        *,
        allowed_world_info_ids: set[str] | None = None,
    ) -> tuple[SafeFactFragmentProjection, ...]:
        projections: list[SafeFactFragmentProjection] = []
        for world_info in self._case.world_info:
            if allowed_world_info_ids is not None and world_info.id not in allowed_world_info_ids:
                continue
            for fragment in world_info.claim_graph.safe_fragments:
                if not self._fragment_unlocked(fragment):
                    continue
                projections.append(
                    SafeFactFragmentProjection(
                        world_info_id=world_info.id,
                        fragment_id=fragment.id,
                        ref=_canonical_safe_fragment_ref(world_info.id, fragment.id),
                        summary=fragment.summary,
                        allowed_modes=fragment.allowed_modes,
                        source_refs=_fragment_source_refs(fragment),
                    )
                )
        return tuple(projections)

    def validate_disclosure_claims(
        self,
        intent: AgentIntent,
    ) -> FactGatewayViolation | None:
        for claim in intent.disclosure_claims:
            world_info = self._world_info_by_id.get(claim.world_info_id)
            if world_info is None or not _has_claim_graph(world_info):
                continue

            fragment_refs = [
                fragment
                for fragment in world_info.claim_graph.safe_fragments
                if self._claim_references_fragment(world_info, fragment, claim)
            ]
            inference_refs = [
                inference
                for ref in claim.claim_refs
                for inference in self._matching_inference_refs(world_info, ref)
            ]

            for inference in inference_refs:
                if self._claim_mode_blocked_by_inference(claim.mode, inference):
                    return FactGatewayViolation(
                        reason=(
                            f"Disclosure claim for world_info '{claim.world_info_id}' "
                            f"references locked forbidden inference '{inference.id}'"
                        ),
                        world_info_id=claim.world_info_id,
                        claimed_mode=claim.mode,
                        forbidden_inference_id=inference.id,
                        matched_by=FactGatewayMatchedBy.CLAIM_REF,
                    )

            for fragment in fragment_refs:
                violation = self._validate_claim_fragment(
                    world_info_id=world_info.id,
                    fragment=fragment,
                    mode=claim.mode,
                )
                if violation is not None:
                    return violation

            if (
                world_info.claim_graph.safe_fragments
                and claim.mode in {DisclosureMode.PARTIAL, DisclosureMode.FULL}
                and not fragment_refs
            ):
                return FactGatewayViolation(
                    reason=(
                        f"Disclosure claim for world_info '{claim.world_info_id}' "
                        "does not reference an authorized safe fragment"
                    ),
                    world_info_id=claim.world_info_id,
                    claimed_mode=claim.mode,
                    matched_by=FactGatewayMatchedBy.CLAIM_REF,
                )
        return None

    def validate_speech(self, intent: AgentIntent) -> FactGatewayViolation | None:
        fragment_mentions = self.detect_safe_fragment_mentions(intent.speech)
        claims_by_world_info = {
            claim.world_info_id: claim for claim in intent.disclosure_claims
        }
        for mention in fragment_mentions:
            fragment = self._fragment_by_id(mention.world_info_id, mention.fragment_id)
            if fragment is None:
                continue
            claim = claims_by_world_info.get(mention.world_info_id)
            if claim is None:
                return FactGatewayViolation(
                    reason=(
                        f"Speech touched safe fragment '{mention.fragment_id}' "
                        f"for world_info '{mention.world_info_id}' without a disclosure claim"
                    ),
                    world_info_id=mention.world_info_id,
                    fragment_id=mention.fragment_id,
                    matched_by=mention.matched_by,
                    matched_text=mention.matched_text,
                    pattern_id=mention.pattern_id,
                )
            violation = self._validate_claim_fragment(
                world_info_id=mention.world_info_id,
                fragment=fragment,
                mode=claim.mode,
                matched_by=mention.matched_by,
                matched_text=mention.matched_text,
                pattern_id=mention.pattern_id,
            )
            if violation is not None:
                return violation
            world_info = self._world_info_by_id.get(mention.world_info_id)
            if world_info is None:
                continue
            if not self._claim_references_fragment(world_info, fragment, claim):
                return FactGatewayViolation(
                    reason=(
                        f"Speech touched safe fragment '{mention.fragment_id}' "
                        f"for world_info '{mention.world_info_id}' without matching "
                        "claim_refs or source_refs"
                    ),
                    world_info_id=mention.world_info_id,
                    claimed_mode=claim.mode,
                    fragment_id=mention.fragment_id,
                    matched_by=mention.matched_by,
                    matched_text=mention.matched_text,
                    pattern_id=mention.pattern_id,
                )

        for inference_mention in self.detect_forbidden_inference_mentions(
            intent.speech,
            fragment_mentions=fragment_mentions,
        ):
            inference = self._inference_by_id(
                inference_mention.world_info_id,
                inference_mention.inference_id,
            )
            if inference is None or not self._inference_blocked(inference):
                continue
            return FactGatewayViolation(
                reason=(
                    "Speech revealed locked forbidden inference "
                    f"'{inference_mention.inference_id}' for world_info "
                    f"'{inference_mention.world_info_id}'"
                ),
                world_info_id=inference_mention.world_info_id,
                forbidden_inference_id=inference_mention.inference_id,
                matched_by=inference_mention.matched_by,
                matched_text=inference_mention.matched_text,
                pattern_id=inference_mention.pattern_id,
            )
        return None

    def detect_safe_fragment_mentions(
        self,
        speech: str,
    ) -> list[DetectedFactFragmentMention]:
        mentions: list[DetectedFactFragmentMention] = []
        for world_info in self._case.world_info:
            for fragment in world_info.claim_graph.safe_fragments:
                mentions.extend(
                    _detect_fragment_alias_mentions(
                        speech=speech,
                        world_info_id=world_info.id,
                        fragment=fragment,
                    )
                )
                mentions.extend(
                    _detect_fragment_pattern_mentions(
                        speech=speech,
                        world_info_id=world_info.id,
                        fragment=fragment,
                    )
                )
        return _dedupe_fragment_mentions(mentions)

    def detect_forbidden_inference_mentions(
        self,
        speech: str,
        *,
        fragment_mentions: list[DetectedFactFragmentMention] | None = None,
    ) -> list[DetectedForbiddenInferenceMention]:
        mentions: list[DetectedForbiddenInferenceMention] = []
        touched_fragment_ids_by_world_info = _fragment_mentions_by_world_info(
            fragment_mentions or self.detect_safe_fragment_mentions(speech)
        )
        touched_world_info_ids = self._detect_touched_world_info_ids(speech)
        for world_info in self._case.world_info:
            for inference in world_info.claim_graph.forbidden_inferences:
                mentions.extend(
                    _detect_inference_alias_mentions(
                        speech=speech,
                        world_info_id=world_info.id,
                        inference=inference,
                    )
                )
                mentions.extend(
                    _detect_inference_pattern_mentions(
                        speech=speech,
                        world_info_id=world_info.id,
                        inference=inference,
                    )
                )
                if self._inference_triggers_present(
                    inference=inference,
                    world_info_id=world_info.id,
                    touched_fragment_ids_by_world_info=touched_fragment_ids_by_world_info,
                    touched_world_info_ids=touched_world_info_ids,
                ):
                    mentions.append(
                        DetectedForbiddenInferenceMention(
                            world_info_id=world_info.id,
                            inference_id=inference.id,
                            matched_by=FactGatewayMatchedBy.FORBIDDEN_INFERENCE_GRAPH,
                            trigger_fragment_ids=tuple(inference.trigger_fragment_ids),
                            trigger_world_info_ids=tuple(inference.trigger_world_info_ids),
                        )
                    )
        return _dedupe_inference_mentions(mentions)

    def _validate_claim_fragment(
        self,
        *,
        world_info_id: str,
        fragment: SafeFactFragmentConfig,
        mode: DisclosureMode,
        matched_by: FactGatewayMatchedBy | None = None,
        matched_text: str | None = None,
        pattern_id: str | None = None,
    ) -> FactGatewayViolation | None:
        if not self._fragment_unlocked(fragment):
            return FactGatewayViolation(
                reason=(
                    f"Safe fragment '{fragment.id}' for world_info '{world_info_id}' "
                    "is not unlocked"
                ),
                world_info_id=world_info_id,
                claimed_mode=mode,
                fragment_id=fragment.id,
                matched_by=matched_by or FactGatewayMatchedBy.CLAIM_REF,
                matched_text=matched_text,
                pattern_id=pattern_id,
            )
        if mode == DisclosureMode.FULL:
            return FactGatewayViolation(
                reason=(
                    f"Safe fragment '{fragment.id}' for world_info '{world_info_id}' "
                    "cannot be fully revealed"
                ),
                world_info_id=world_info_id,
                claimed_mode=mode,
                fragment_id=fragment.id,
                matched_by=matched_by or FactGatewayMatchedBy.CLAIM_REF,
                matched_text=matched_text,
                pattern_id=pattern_id,
            )
        if mode not in set(fragment.allowed_modes):
            return FactGatewayViolation(
                reason=(
                    f"Disclosure mode '{mode}' is not allowed for safe fragment "
                    f"'{fragment.id}' in world_info '{world_info_id}'"
                ),
                world_info_id=world_info_id,
                claimed_mode=mode,
                fragment_id=fragment.id,
                matched_by=matched_by or FactGatewayMatchedBy.CLAIM_REF,
                matched_text=matched_text,
                pattern_id=pattern_id,
            )
        return None

    def _claim_mode_blocked_by_inference(
        self,
        mode: DisclosureMode,
        inference: ForbiddenInferenceConfig,
    ) -> bool:
        return self._inference_blocked(inference) and mode in set(inference.blocked_modes)

    def _fragment_unlocked(self, fragment: SafeFactFragmentConfig) -> bool:
        return self._conditions_satisfied(fragment.unlock_conditions)

    def _inference_blocked(self, inference: ForbiddenInferenceConfig) -> bool:
        if inference.unlock_conditions is None:
            return True
        return not self._conditions_satisfied(inference.unlock_conditions)

    def _conditions_satisfied(self, conditions: FactUnlockConditionConfig) -> bool:
        if conditions.phases and self._narrative.phase not in set(conditions.phases):
            return False
        if not set(conditions.completed_beats) <= self._completed_beats():
            return False
        if not set(conditions.discovered_clues) <= self._discovered_clues():
            return False
        if not set(conditions.player_knowledge_ids) <= self._player_knowledge_ids():
            return False
        if not set(conditions.player_world_info_ids) <= self._player_world_info_ids():
            return False
        return True

    def _completed_beats(self) -> set[str]:
        values = set(self._narrative.completed_beats)
        if self._context is not None:
            values.update(self._context.completed_beats)
        return values

    def _discovered_clues(self) -> set[str]:
        values = set(self._narrative.discovered_clues)
        if self._context is not None:
            values.update(self._context.discovered_clues)
        return values

    def _player_knowledge_ids(self) -> set[str]:
        if self._context is None:
            return set()
        return {item.knowledge_id for item in self._context.player_knowledge}

    def _player_world_info_ids(self) -> set[str]:
        if self._context is None:
            return set()
        return {
            item.world_info_id
            for item in self._context.player_knowledge
            if item.world_info_id is not None
        }

    def _claim_references_fragment(
        self,
        world_info: WorldInfoConfig,
        fragment: SafeFactFragmentConfig,
        claim: object,
    ) -> bool:
        claim_refs = list(getattr(claim, "claim_refs", []))
        source_refs = list(getattr(claim, "source_refs", []))
        for ref in [*claim_refs, *source_refs]:
            if _claim_ref_matches(world_info.id, fragment.id, ref, "safe_fragment"):
                return True
            if ref == _canonical_safe_fragment_ref(world_info.id, fragment.id):
                return True
        return any(ref in set(_fragment_source_refs(fragment)) for ref in source_refs)

    def _matching_inference_refs(
        self,
        world_info: WorldInfoConfig,
        claim_ref: str,
    ) -> list[ForbiddenInferenceConfig]:
        return [
            inference
            for inference in world_info.claim_graph.forbidden_inferences
            if _claim_ref_matches(world_info.id, inference.id, claim_ref, "inference")
            or _claim_ref_matches(world_info.id, inference.id, claim_ref, "forbidden_inference")
        ]

    def _fragment_by_id(
        self,
        world_info_id: str,
        fragment_id: str,
    ) -> SafeFactFragmentConfig | None:
        world_info = self._world_info_by_id.get(world_info_id)
        if world_info is None:
            return None
        return next(
            (
                fragment
                for fragment in world_info.claim_graph.safe_fragments
                if fragment.id == fragment_id
            ),
            None,
        )

    def _inference_by_id(
        self,
        world_info_id: str,
        inference_id: str,
    ) -> ForbiddenInferenceConfig | None:
        world_info = self._world_info_by_id.get(world_info_id)
        if world_info is None:
            return None
        return next(
            (
                inference
                for inference in world_info.claim_graph.forbidden_inferences
                if inference.id == inference_id
            ),
            None,
        )

    def _detect_touched_world_info_ids(self, speech: str) -> set[str]:
        normalized_speech = _normalize_text(speech)
        touched: set[str] = set()
        for world_info in self._case.world_info:
            literal_values = [world_info.title, *world_info.aliases]
            if any(
                _normalize_text(value) and _normalize_text(value) in normalized_speech
                for value in literal_values
            ):
                touched.add(world_info.id)
                continue
            if any(
                re.search(pattern, speech, flags=re.IGNORECASE)
                for pattern in world_info.claim_patterns
            ):
                touched.add(world_info.id)
        return touched

    def _inference_triggers_present(
        self,
        *,
        inference: ForbiddenInferenceConfig,
        world_info_id: str,
        touched_fragment_ids_by_world_info: dict[str, set[str]],
        touched_world_info_ids: set[str],
    ) -> bool:
        required_fragments = set(inference.trigger_fragment_ids)
        required_world_info = set(inference.trigger_world_info_ids)
        if not required_fragments and not required_world_info:
            return False
        touched_fragments = touched_fragment_ids_by_world_info.get(world_info_id, set())
        return (
            required_fragments <= touched_fragments
            and required_world_info <= touched_world_info_ids
        )


def _has_claim_graph(world_info: WorldInfoConfig) -> bool:
    return bool(
        world_info.claim_graph.safe_fragments
        or world_info.claim_graph.forbidden_inferences
    )


def _claim_ref_matches(
    world_info_id: str,
    item_id: str,
    claim_ref: str,
    prefix: str,
) -> bool:
    return claim_ref in {
        item_id,
        f"{prefix}:{item_id}",
        f"{world_info_id}.{item_id}",
        f"{world_info_id}:{item_id}",
        f"{world_info_id}.{prefix}:{item_id}",
    }


def _canonical_safe_fragment_ref(world_info_id: str, fragment_id: str) -> str:
    return f"{world_info_id}.safe_fragment:{fragment_id}"


def _fragment_source_refs(fragment: SafeFactFragmentConfig) -> list[str]:
    refs: list[str] = []
    conditions = fragment.unlock_conditions
    refs.extend(f"phase:{phase}" for phase in conditions.phases)
    refs.extend(f"beat:{beat}" for beat in conditions.completed_beats)
    refs.extend(conditions.completed_beats)
    refs.extend(f"clue:{clue_id}" for clue_id in conditions.discovered_clues)
    refs.extend(conditions.discovered_clues)
    refs.extend(conditions.player_knowledge_ids)
    refs.extend(
        f"world_info:{world_info_id}"
        for world_info_id in conditions.player_world_info_ids
    )
    return _dedupe_strings(refs)


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value in deduped:
            continue
        deduped.append(value)
    return deduped


def _detect_fragment_alias_mentions(
    *,
    speech: str,
    world_info_id: str,
    fragment: SafeFactFragmentConfig,
) -> list[DetectedFactFragmentMention]:
    normalized_speech = _normalize_text(speech)
    mentions: list[DetectedFactFragmentMention] = []
    for alias in fragment.aliases:
        normalized_alias = _normalize_text(alias)
        if not normalized_alias or normalized_alias not in normalized_speech:
            continue
        mentions.append(
            DetectedFactFragmentMention(
                world_info_id=world_info_id,
                fragment_id=fragment.id,
                matched_by=FactGatewayMatchedBy.SAFE_FRAGMENT_ALIAS,
                matched_text=alias,
            )
        )
    return mentions


def _detect_fragment_pattern_mentions(
    *,
    speech: str,
    world_info_id: str,
    fragment: SafeFactFragmentConfig,
) -> list[DetectedFactFragmentMention]:
    mentions: list[DetectedFactFragmentMention] = []
    for index, pattern in enumerate(fragment.claim_patterns):
        match = re.search(pattern, speech, flags=re.IGNORECASE)
        if match is None:
            continue
        mentions.append(
            DetectedFactFragmentMention(
                world_info_id=world_info_id,
                fragment_id=fragment.id,
                matched_by=FactGatewayMatchedBy.SAFE_FRAGMENT_PATTERN,
                matched_text=match.group(0),
                pattern_id=f"{world_info_id}.{fragment.id}.claim_patterns[{index}]",
            )
        )
    return mentions


def _detect_inference_alias_mentions(
    *,
    speech: str,
    world_info_id: str,
    inference: ForbiddenInferenceConfig,
) -> list[DetectedForbiddenInferenceMention]:
    normalized_speech = _normalize_text(speech)
    mentions: list[DetectedForbiddenInferenceMention] = []
    for alias in inference.aliases:
        normalized_alias = _normalize_text(alias)
        if not normalized_alias or normalized_alias not in normalized_speech:
            continue
        mentions.append(
            DetectedForbiddenInferenceMention(
                world_info_id=world_info_id,
                inference_id=inference.id,
                matched_by=FactGatewayMatchedBy.FORBIDDEN_INFERENCE_ALIAS,
                matched_text=alias,
            )
        )
    return mentions


def _detect_inference_pattern_mentions(
    *,
    speech: str,
    world_info_id: str,
    inference: ForbiddenInferenceConfig,
) -> list[DetectedForbiddenInferenceMention]:
    mentions: list[DetectedForbiddenInferenceMention] = []
    for index, pattern in enumerate(inference.claim_patterns):
        match = re.search(pattern, speech, flags=re.IGNORECASE)
        if match is None:
            continue
        mentions.append(
            DetectedForbiddenInferenceMention(
                world_info_id=world_info_id,
                inference_id=inference.id,
                matched_by=FactGatewayMatchedBy.FORBIDDEN_INFERENCE_PATTERN,
                matched_text=match.group(0),
                pattern_id=f"{world_info_id}.{inference.id}.claim_patterns[{index}]",
            )
        )
    return mentions


def _fragment_mentions_by_world_info(
    mentions: list[DetectedFactFragmentMention],
) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for mention in mentions:
        grouped.setdefault(mention.world_info_id, set()).add(mention.fragment_id)
    return grouped


def _dedupe_fragment_mentions(
    mentions: list[DetectedFactFragmentMention],
) -> list[DetectedFactFragmentMention]:
    seen: set[tuple[str, str, FactGatewayMatchedBy, str | None, str | None]] = set()
    deduped: list[DetectedFactFragmentMention] = []
    for mention in mentions:
        key = (
            mention.world_info_id,
            mention.fragment_id,
            mention.matched_by,
            mention.matched_text,
            mention.pattern_id,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(mention)
    return deduped


def _dedupe_inference_mentions(
    mentions: list[DetectedForbiddenInferenceMention],
) -> list[DetectedForbiddenInferenceMention]:
    seen: set[
        tuple[
            str,
            str,
            FactGatewayMatchedBy,
            str | None,
            str | None,
            tuple[str, ...],
            tuple[str, ...],
        ]
    ] = set()
    deduped: list[DetectedForbiddenInferenceMention] = []
    for mention in mentions:
        key = (
            mention.world_info_id,
            mention.inference_id,
            mention.matched_by,
            mention.matched_text,
            mention.pattern_id,
            mention.trigger_fragment_ids,
            mention.trigger_world_info_ids,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(mention)
    return deduped


def _normalize_text(value: str) -> str:
    return value.casefold()
