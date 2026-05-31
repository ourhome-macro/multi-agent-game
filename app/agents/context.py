from __future__ import annotations

from app.domain.models import (
    AgentCharacterView,
    AgentContext,
    CasePackage,
    CharacterConfig,
    CharacterImpression,
    CharacterInnerContext,
    DisclosureMode,
    DisclosurePolicy,
    EventType,
    PlayerAction,
    SelfKnowledgeItem,
    SessionState,
)
from app.rules.engine import player_knowledge_id_for_clue, relationship_key
from app.runtime.pressure import calculate_interaction_pressure, subject_is_sensitive

RECENT_EVENT_LIMIT = 10
DISCLOSURE_MODE_ORDER = [
    DisclosureMode.NONE,
    DisclosureMode.DENY,
    DisclosureMode.DEFLECT,
    DisclosureMode.HINT,
    DisclosureMode.PARTIAL,
    DisclosureMode.FULL,
]


def build_agent_context(
    case: CasePackage,
    session: SessionState,
    action: PlayerAction,
) -> AgentContext:
    dialogue = next(
        (item for item in case.mock_dialogues if item.character_id == action.target_id),
        None,
    )
    character = next((item for item in case.characters if item.id == action.target_id), None)
    current_phase = session.narrative.phase
    relationship = session.relationships.get(relationship_key(action.target_id, "player"))
    threshold_prefix = f"{action.target_id}->player:"

    blocked_fact_ids = sorted(
        fact.id
        for fact in case.forbidden_facts
        if fact.reveal_phase != current_phase
    )
    revealable_fact_ids = sorted(
        fact.id
        for fact in case.forbidden_facts
        if fact.reveal_phase == current_phase
    )
    target_profile = (
        AgentCharacterView(
            id=character.id,
            display_name=character.display_name,
            public_role=character.public_role,
            public_description=character.public_description,
            speech_style=character.speech.style,
            default_tone=character.speech.default_tone,
            catchphrases=character.speech.catchphrases,
            visible_traits=character.personality.traits,
            defensive_style=character.speech.defensive_style,
            pressure_response=character.personality.pressure_response,
            trust_response=character.personality.trust_response,
            fear_response=character.personality.fear_response,
        )
        if character is not None
        else None
    )
    presented_clue_id = action.clue_id
    presented_knowledge_id = (
        player_knowledge_id_for_clue(case, action.clue_id)
        if action.clue_id is not None
        else None
    )
    asked_subject_type = action.subject_type
    asked_subject_id = action.subject_id
    inner_context = (
        build_character_inner_context(case, session, character, action)
        if character is not None
        else None
    )

    return AgentContext(
        case_id=case.meta.id,
        session_id=session.id,
        target_agent_id=action.target_id,
        current_phase=current_phase,
        completed_beats=sorted(session.narrative.completed_beats),
        discovered_clues=sorted(session.discovered_clues),
        player_knowledge=sorted(
            session.player_knowledge.values(),
            key=lambda value: value.knowledge_id,
        ),
        relationship_to_player=relationship,
        relationship_thresholds_crossed=sorted(
            item
            for item in session.relationship_thresholds_crossed
            if item.startswith(threshold_prefix)
        ),
        recent_events=[
            event
            for event in session.events
            if event.type != EventType.CHARACTER_IMPRESSION_UPDATED
        ][-RECENT_EVENT_LIMIT:],
        memory_candidates=sorted(
            session.memory_candidates.values(),
            key=lambda value: value.memory_id,
        ),
        memory_snapshots=sorted(
            (
                snapshot
                for snapshot in session.memory_snapshots.values()
                if snapshot.subject_id == "player"
            ),
            key=lambda value: value.memory_id,
        ),
        blocked_fact_ids=blocked_fact_ids,
        revealable_fact_ids=revealable_fact_ids,
        asked_subject_type=asked_subject_type,
        asked_subject_id=asked_subject_id,
        interaction_pressure=calculate_interaction_pressure(case, action),
        subject_is_sensitive=subject_is_sensitive(case, action),
        presented_clue_id=presented_clue_id,
        presented_knowledge_id=presented_knowledge_id,
        player_action=action,
        target_profile=target_profile,
        inner_context=inner_context,
        default_speech=dialogue.default_speech if dialogue is not None else None,
        default_intent=dialogue.default_intent if dialogue is not None else None,
        reply_options=dialogue.replies if dialogue is not None else [],
        fallback_relationship_delta=(
            dialogue.relationship_delta_on_talk if dialogue is not None else {}
        ),
    )


def build_character_inner_context(
    case: CasePackage,
    session: SessionState,
    target_character: CharacterConfig,
    action: PlayerAction,
) -> CharacterInnerContext:
    _ = case, action
    portraits = sorted(
        session.character_impressions.get(target_character.id, {}).values(),
        key=lambda value: value.target_id,
    )
    player_impression = next(
        (portrait for portrait in portraits if portrait.target_id == "player"),
        None,
    )
    return CharacterInnerContext(
        character_id=target_character.id,
        inner_goals=[
            SelfKnowledgeItem(
                id=goal.id,
                kind="goal",
                summary=goal.summary,
                priority=goal.priority,
                related_world_info_ids=goal.related_world_info_ids,
                tags=goal.tags,
                disclosure_policy=_effective_disclosure_policy(
                    policy=goal.disclosure_policy,
                    impression=player_impression,
                    related_clue_ids=[],
                    related_world_info_ids=goal.related_world_info_ids,
                    action=action,
                ),
            )
            for goal in target_character.private.goals
        ],
        inner_secrets=[
            SelfKnowledgeItem(
                id=secret.id,
                kind="secret",
                summary=secret.summary,
                priority=secret.priority,
                related_clue_ids=secret.related_clue_ids,
                related_world_info_ids=secret.related_world_info_ids,
                tags=secret.tags,
                disclosure_policy=_effective_disclosure_policy(
                    policy=secret.disclosure_policy,
                    impression=player_impression,
                    related_clue_ids=secret.related_clue_ids,
                    related_world_info_ids=secret.related_world_info_ids,
                    action=action,
                ),
            )
            for secret in target_character.private.secrets
        ],
        inner_knowledge=[
            SelfKnowledgeItem(
                id=knowledge.id,
                kind="knowledge",
                summary=knowledge.summary,
                priority=knowledge.priority,
                related_clue_ids=knowledge.related_clue_ids,
                related_world_info_ids=knowledge.related_world_info_ids,
                tags=knowledge.tags,
                disclosure_policy=_effective_disclosure_policy(
                    policy=knowledge.disclosure_policy,
                    impression=player_impression,
                    related_clue_ids=knowledge.related_clue_ids,
                    related_world_info_ids=knowledge.related_world_info_ids,
                    action=action,
                ),
            )
            for knowledge in target_character.private.knowledge
        ],
        inner_portraits=portraits,
    )


def _effective_disclosure_policy(
    *,
    policy: DisclosurePolicy,
    impression: CharacterImpression | None,
    related_clue_ids: list[str],
    related_world_info_ids: list[str],
    action: PlayerAction,
) -> DisclosurePolicy:
    if impression is None:
        return policy

    modes = set(policy.allowed_modes)
    tags = set(impression.tags)
    dangerous_topic = "dangerous_topic_triggered" in tags
    high_threat = impression.threat_level >= 0.75

    if dangerous_topic:
        modes = modes & {DisclosureMode.DENY, DisclosureMode.DEFLECT}
        if not modes:
            modes = {DisclosureMode.DEFLECT}
    elif high_threat:
        modes = modes & {DisclosureMode.DENY, DisclosureMode.DEFLECT}
        if not modes:
            modes = {DisclosureMode.DENY, DisclosureMode.DEFLECT}
    else:
        if impression.alliance_potential >= 0.7:
            modes.add(DisclosureMode.HINT)
        if _impression_matches_related_evidence(
            impression,
            related_clue_ids,
            related_world_info_ids,
            action,
        ):
            modes.update({DisclosureMode.HINT, DisclosureMode.PARTIAL})

    modes.discard(DisclosureMode.FULL)
    ordered_modes = [mode for mode in DISCLOSURE_MODE_ORDER if mode in modes]
    can_hint_from_alliance = (
        impression.alliance_potential >= 0.7
        and DisclosureMode.HINT in ordered_modes
        and not dangerous_topic
        and not high_threat
    )
    can_partially_disclose = DisclosureMode.PARTIAL in ordered_modes

    return DisclosurePolicy(
        revealable=policy.revealable or can_hint_from_alliance or can_partially_disclose,
        allowed_modes=ordered_modes,
        direct_reveal_allowed=(
            policy.direct_reveal_allowed and DisclosureMode.FULL in ordered_modes
        ),
        direct_quote_allowed=(
            policy.direct_quote_allowed and DisclosureMode.FULL in ordered_modes
        ),
    )


def _impression_matches_related_evidence(
    impression: CharacterImpression,
    related_clue_ids: list[str],
    related_world_info_ids: list[str],
    action: PlayerAction,
) -> bool:
    if "has_relevant_evidence" not in impression.tags:
        return False
    if not related_clue_ids and not related_world_info_ids:
        return False
    if _action_matches_related_clue(action, related_clue_ids):
        return True
    refs = set(impression.suspected_knowledge_refs)
    clue_matches = any(
        clue_id in refs or f"player_knowledge.{clue_id}" in refs
        for clue_id in related_clue_ids
    )
    world_info_matches = any(
        world_info_id in refs or f"player_knowledge.{world_info_id}" in refs
        for world_info_id in related_world_info_ids
    )
    return clue_matches or world_info_matches


def _action_matches_related_clue(action: PlayerAction, related_clue_ids: list[str]) -> bool:
    if action.clue_id is not None and action.clue_id in related_clue_ids:
        return True
    return (
        action.subject_type == "clue"
        and action.subject_id is not None
        and action.subject_id in related_clue_ids
    )
