from __future__ import annotations

from app.domain.models import (
    CharacterDisclosureStyleConfig,
    CharacterFactAwarenessState,
    CharacterFactStance,
    CharacterImpression,
    DisclosureMode,
    FactDisclosureStrategy,
    PlayerAction,
    RhetoricTactic,
)

DISCLOSURE_MODE_ORDER = [
    DisclosureMode.NONE,
    DisclosureMode.DENY,
    DisclosureMode.DEFLECT,
    DisclosureMode.HINT,
    DisclosureMode.PARTIAL,
    DisclosureMode.FULL,
]


def build_fact_disclosure_strategies(
    *,
    fact_awareness: list[CharacterFactAwarenessState],
    player_impression: CharacterImpression | None,
    action: PlayerAction,
    disclosure_style: CharacterDisclosureStyleConfig | None = None,
    player_known_world_info_ids: set[str] | None = None,
) -> list[FactDisclosureStrategy]:
    known_world_info_ids = player_known_world_info_ids or set()
    return [
        _build_strategy(
            awareness=awareness,
            player_impression=player_impression,
            action=action,
            disclosure_style=disclosure_style,
            player_known_world_info_ids=known_world_info_ids,
        )
        for awareness in sorted(fact_awareness, key=lambda item: item.awareness_id)
    ]


def _build_strategy(
    *,
    awareness: CharacterFactAwarenessState,
    player_impression: CharacterImpression | None,
    action: PlayerAction,
    disclosure_style: CharacterDisclosureStyleConfig | None,
    player_known_world_info_ids: set[str],
) -> FactDisclosureStrategy:
    allowed_modes = set(_base_allowed_modes(awareness.stance))
    tactics = set(_base_tactics(awareness.stance))
    safe_fact_refs: set[str] = set()
    must_not_claim = {
        f"full_reveal:{awareness.world_info_id}",
        f"direct_confession:{awareness.world_info_id}",
    }

    player_knows_fact = awareness.world_info_id in player_known_world_info_ids
    evidence_pressure = (
        _action_matches_evidence(action, awareness.evidence_clue_ids)
        or player_knows_fact
    )
    if evidence_pressure or _impression_has_relevant_evidence(player_impression):
        if awareness.stance in {CharacterFactStance.KNOWS, CharacterFactStance.CONCEALS}:
            allowed_modes.add(DisclosureMode.PARTIAL)
            tactics.add(RhetoricTactic.ANSWER_ADJACENT_TRUTH)
            safe_fact_refs.update(awareness.evidence_clue_ids)
            if player_knows_fact:
                safe_fact_refs.add(f"player_knowledge:{awareness.world_info_id}")
        if awareness.stance == CharacterFactStance.SUSPECTS:
            allowed_modes.add(DisclosureMode.HINT)
            tactics.add(RhetoricTactic.QUALIFY_CERTAINTY)

    if _alliance_ready(player_impression) and awareness.stance != CharacterFactStance.MISBELIEVES:
        allowed_modes.add(DisclosureMode.HINT)
        tactics.add(RhetoricTactic.ANSWER_ADJACENT_TRUTH)

    if _medium_pressure(player_impression):
        allowed_modes.add(DisclosureMode.DEFLECT)
        tactics.add(RhetoricTactic.COUNTER_QUESTION)

    if _dangerous_topic_triggered(player_impression) or _high_threat(player_impression):
        allowed_modes = allowed_modes & {DisclosureMode.DENY, DisclosureMode.DEFLECT}
        if not allowed_modes:
            allowed_modes = {DisclosureMode.DEFLECT}
        tactics.update(
            {
                RhetoricTactic.COUNTER_QUESTION,
                RhetoricTactic.SHIFT_FOCUS,
                RhetoricTactic.EMOTIONAL_SCREEN,
            }
        )
        safe_fact_refs.clear()

    allowed_modes = _apply_max_mode(
        allowed_modes,
        disclosure_style,
        awareness.world_info_id,
    )
    tactics = _apply_tactic_preferences(tactics, disclosure_style)
    allowed_modes.discard(DisclosureMode.FULL)
    forbidden_modes = set(DisclosureMode) - allowed_modes
    forbidden_modes.add(DisclosureMode.FULL)

    return FactDisclosureStrategy(
        world_info_id=awareness.world_info_id,
        stance=awareness.stance,
        allowed_modes=_ordered_modes(allowed_modes),
        forbidden_modes=_ordered_modes(forbidden_modes),
        rhetoric_tactics=sorted(tactics, key=lambda tactic: tactic.value),
        must_not_claim=sorted(must_not_claim),
        safe_fact_refs=sorted(safe_fact_refs),
        evidence_clue_ids=awareness.evidence_clue_ids,
        confidence=awareness.confidence,
        source_awareness_id=awareness.awareness_id,
    )


def _base_allowed_modes(stance: CharacterFactStance) -> set[DisclosureMode]:
    if stance == CharacterFactStance.CONCEALS:
        return {DisclosureMode.DENY, DisclosureMode.DEFLECT, DisclosureMode.HINT}
    if stance == CharacterFactStance.KNOWS:
        return {DisclosureMode.HINT, DisclosureMode.PARTIAL}
    if stance == CharacterFactStance.SUSPECTS:
        return {DisclosureMode.DEFLECT, DisclosureMode.HINT}
    return {DisclosureMode.DEFLECT}


def _base_tactics(stance: CharacterFactStance) -> set[RhetoricTactic]:
    if stance == CharacterFactStance.CONCEALS:
        return {
            RhetoricTactic.SHIFT_FOCUS,
            RhetoricTactic.COUNTER_QUESTION,
            RhetoricTactic.EMOTIONAL_SCREEN,
        }
    if stance == CharacterFactStance.KNOWS:
        return {
            RhetoricTactic.ANSWER_ADJACENT_TRUTH,
            RhetoricTactic.QUALIFY_CERTAINTY,
        }
    if stance == CharacterFactStance.SUSPECTS:
        return {
            RhetoricTactic.QUALIFY_CERTAINTY,
            RhetoricTactic.COUNTER_QUESTION,
        }
    return {
        RhetoricTactic.QUALIFY_CERTAINTY,
        RhetoricTactic.SHIFT_FOCUS,
    }


def _ordered_modes(modes: set[DisclosureMode]) -> list[DisclosureMode]:
    return [mode for mode in DISCLOSURE_MODE_ORDER if mode in modes]


def _apply_max_mode(
    modes: set[DisclosureMode],
    disclosure_style: CharacterDisclosureStyleConfig | None,
    world_info_id: str,
) -> set[DisclosureMode]:
    if disclosure_style is None:
        return modes
    max_mode = disclosure_style.max_mode_by_world_info.get(world_info_id)
    if max_mode is None:
        return modes
    max_index = DISCLOSURE_MODE_ORDER.index(max_mode)
    return {
        mode
        for mode in modes
        if DISCLOSURE_MODE_ORDER.index(mode) <= max_index
    }


def _apply_tactic_preferences(
    tactics: set[RhetoricTactic],
    disclosure_style: CharacterDisclosureStyleConfig | None,
) -> set[RhetoricTactic]:
    if disclosure_style is None:
        return tactics
    preferred_tactics = set(disclosure_style.preferred_tactics)
    forbidden_tactics = set(disclosure_style.forbidden_tactics)
    return (tactics | preferred_tactics) - forbidden_tactics


def _action_matches_evidence(action: PlayerAction, evidence_clue_ids: list[str]) -> bool:
    if not evidence_clue_ids:
        return False
    if action.clue_id is not None and action.clue_id in evidence_clue_ids:
        return True
    return (
        action.subject_type == "clue"
        and action.subject_id is not None
        and action.subject_id in evidence_clue_ids
    )


def _impression_has_relevant_evidence(
    player_impression: CharacterImpression | None,
) -> bool:
    return player_impression is not None and "has_relevant_evidence" in player_impression.tags


def _dangerous_topic_triggered(player_impression: CharacterImpression | None) -> bool:
    return (
        player_impression is not None
        and "dangerous_topic_triggered" in player_impression.tags
    )


def _high_threat(player_impression: CharacterImpression | None) -> bool:
    return player_impression is not None and player_impression.threat_level >= 0.75


def _medium_pressure(player_impression: CharacterImpression | None) -> bool:
    return (
        player_impression is not None
        and 0.35 <= player_impression.threat_level < 0.75
    )


def _alliance_ready(player_impression: CharacterImpression | None) -> bool:
    return player_impression is not None and player_impression.alliance_potential >= 0.7
