from __future__ import annotations

from app.agents.disclosure_strategy import (
    DISCLOSURE_MODE_ORDER,
    build_fact_disclosure_strategies,
)
from app.agents.memory import (
    MemoryRetriever,
    memory_allowed_by_plan,
    memory_content_matches_forbidden,
)
from app.agents.retrieval_planner import MemoryRetrievalPlan, RetrievalPlanner
from app.domain.models import (
    AgentCharacterView,
    AgentContext,
    AgentMemorySnapshot,
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


def build_agent_context(
    case: CasePackage,
    session: SessionState,
    action: PlayerAction,
    retrieval_plan: MemoryRetrievalPlan | None = None,
    memory_snapshots: list[AgentMemorySnapshot] | None = None,
) -> AgentContext:
    plan = retrieval_plan or RetrievalPlanner().plan(
        case=case,
        session=session,
        action=action,
    )
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
    portrait_summary = (
        _portrait_summary(character, inner_context)
        if plan.inject_portrait_summary
        else None
    )
    forbidden_terms = _forbidden_terms(case)
    retrieved_memory_snapshots = (
        memory_snapshots
        if memory_snapshots is not None
        else MemoryRetriever(
            max_results=plan.max_memory_items,
        ).retrieve(
            case=case,
            session=session,
            action=action,
            plan=plan,
        )
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
        recent_events=(
            [
                event
                for event in session.events
                if _event_visible_to_target(
                    event,
                    action.target_id,
                    plan=plan,
                    forbidden_terms=forbidden_terms,
                )
            ][-RECENT_EVENT_LIMIT:]
            if plan.allow_recent_events
            else []
        ),
        memory_candidates=sorted(
            (
                candidate
                for candidate in session.memory_candidates.values()
                if candidate.subject_id == "player"
                and _memory_injectable_to_agent(
                    candidate,
                    action.target_id,
                    plan=plan,
                    forbidden_terms=forbidden_terms,
                )
            ),
            key=lambda value: value.memory_id,
        )[: plan.max_memory_items],
        memory_snapshots=retrieved_memory_snapshots,
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
        portrait_summary=portrait_summary,
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
    fact_awareness = sorted(
        (
            awareness
            for awareness in session.character_fact_awareness.values()
            if awareness.character_id == target_character.id
        ),
        key=lambda value: value.awareness_id,
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
        fact_awareness=fact_awareness,
        fact_disclosure_strategies=build_fact_disclosure_strategies(
            fact_awareness=fact_awareness,
            player_impression=player_impression,
            action=action,
            disclosure_style=target_character.private.disclosure_style,
            player_known_world_info_ids={
                knowledge.world_info_id for knowledge in session.player_knowledge.values()
            },
        ),
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


def _memory_injectable_to_agent(
    snapshot: object,
    target_id: str,
    *,
    plan: MemoryRetrievalPlan | None,
    forbidden_terms: tuple[str, ...],
) -> bool:
    if not _memory_scope_injectable(snapshot):
        return False
    if not _memory_visible_to_target(snapshot, target_id):
        return False
    if not _memory_layer_injectable(snapshot):
        return False
    if not memory_allowed_by_plan(snapshot, plan):
        return False
    return not memory_content_matches_forbidden(snapshot, forbidden_terms)


def _memory_scope_injectable(snapshot: object) -> bool:
    return getattr(snapshot, "memory_scope", "npc_private") in {
        "case",
        "session",
        "npc_private",
        "scene_shared",
    }


def _memory_visible_to_target(snapshot: object, target_id: str) -> bool:
    scope = getattr(snapshot, "memory_scope", "npc_private")
    owner = getattr(snapshot, "owner_character_id", None)
    visible_to = set(getattr(snapshot, "visible_to_character_ids", []))
    if scope in {"case", "session"}:
        return not visible_to or owner == target_id or target_id in visible_to
    if scope == "npc_private":
        return owner == target_id or target_id in visible_to
    if scope == "scene_shared":
        return target_id in visible_to or owner == target_id
    return False


def _memory_layer_injectable(snapshot: object) -> bool:
    scope = getattr(snapshot, "memory_scope", "npc_private")
    layer = getattr(snapshot, "memory_layer", "working")
    if scope == "case":
        return layer == "core"
    if scope == "session":
        return layer == "working"
    return layer != "archival"


def _event_visible_to_target(
    event: object,
    target_id: str,
    *,
    plan: MemoryRetrievalPlan | None,
    forbidden_terms: tuple[str, ...],
) -> bool:
    event_type = getattr(event, "type", None)
    payload = getattr(event, "payload", {})
    actor_id = getattr(event, "actor_id", None)
    if not isinstance(payload, dict):
        return True
    if event_type in {
        EventType.CHARACTER_IMPRESSION_UPDATED,
        EventType.CHARACTER_FACT_AWARENESS_UPDATED,
    }:
        return False
    if event_type in {
        EventType.MEMORY_CANDIDATE_CREATED,
        EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
    }:
        return _memory_event_visible_to_target(
            payload,
            target_id,
            plan=plan,
            forbidden_terms=forbidden_terms,
        )
    if event_type in {
        EventType.PLAYER_ASKED_ABOUT,
        EventType.PLAYER_PRESENTED_CLUE,
        EventType.PLAYER_ACCUSED,
        EventType.ACCUSATION_EVALUATED,
        EventType.DIRECTOR_BLOCKED,
    }:
        return payload.get("target_id") == target_id
    if event_type == EventType.NPC_REPLIED:
        return actor_id == target_id
    if event_type in {
        EventType.RELATIONSHIP_CHANGED,
        EventType.RELATIONSHIP_THRESHOLD_CROSSED,
    }:
        return payload.get("source_id") == target_id or payload.get("target_id") == target_id
    return True


def _memory_event_visible_to_target(
    payload: dict[str, object],
    target_id: str,
    *,
    plan: MemoryRetrievalPlan | None,
    forbidden_terms: tuple[str, ...],
) -> bool:
    if not _memory_event_scope_injectable(payload):
        return False
    if not _memory_event_target_visible(payload, target_id):
        return False
    if not _memory_event_layer_injectable(payload):
        return False
    if not _memory_event_allowed_by_plan(payload, plan):
        return False
    return not _memory_event_matches_forbidden(payload, forbidden_terms)


def _memory_event_scope_injectable(payload: dict[str, object]) -> bool:
    return str(payload.get("memory_scope", "npc_private")) in {
        "case",
        "session",
        "npc_private",
        "scene_shared",
    }


def _memory_event_target_visible(payload: dict[str, object], target_id: str) -> bool:
    scope = str(payload.get("memory_scope", "npc_private"))
    owner = payload.get("owner_character_id")
    visible_to = {
        str(item) for item in payload.get("visible_to_character_ids", []) if item is not None
    }
    if scope in {"case", "session"}:
        return not visible_to or owner == target_id or target_id in visible_to
    if scope == "npc_private":
        return owner == target_id or target_id in visible_to
    if scope == "scene_shared":
        return target_id in visible_to or owner == target_id
    return False


def _memory_event_layer_injectable(payload: dict[str, object]) -> bool:
    scope = str(payload.get("memory_scope", "npc_private"))
    layer = str(payload.get("memory_layer", "working"))
    if scope == "case":
        return layer == "core"
    if scope == "session":
        return layer == "working"
    return layer != "archival"


def _memory_event_allowed_by_plan(
    payload: dict[str, object],
    plan: MemoryRetrievalPlan | None,
) -> bool:
    if plan is None:
        return True
    memory_type = str(payload.get("memory_type", "episodic"))
    memory_scope = str(payload.get("memory_scope", "npc_private"))
    memory_layer = str(payload.get("memory_layer", "working"))
    return (
        memory_type in set(plan.included_memory_types)
        and memory_scope in set(plan.included_scopes)
        and memory_layer in set(plan.included_layers)
        and memory_scope not in set(plan.forbidden_scopes)
        and memory_layer not in set(plan.forbidden_layers)
    )


def _memory_event_matches_forbidden(
    payload: dict[str, object],
    forbidden_terms: tuple[str, ...],
) -> bool:
    content = str(payload.get("content", ""))
    return any(term and term in content for term in forbidden_terms)


def _forbidden_terms(case: CasePackage) -> tuple[str, ...]:
    terms: list[str] = []
    for fact in case.forbidden_facts:
        terms.append(fact.text)
        terms.extend(fact.blocked_terms)
    return tuple(term for term in terms if term)


def _portrait_summary(
    character: CharacterConfig | None,
    inner_context: CharacterInnerContext | None,
) -> str | None:
    if character is None or inner_context is None:
        return None
    portrait = next(
        (
            item
            for item in inner_context.inner_portraits
            if item.target_id == "player" and item.observer_id == character.id
        ),
        None,
    )
    if portrait is None:
        return None
    if (
        portrait.current_strategy == "avoid_medicine_topic"
        or portrait.suspicion >= 0.2
        or portrait.threat_level >= 0.5
    ):
        return f"{character.display_name}当前对玩家高度警惕"
    if portrait.trust >= 0.5 or portrait.alliance_potential >= 0.7:
        return f"{character.display_name}当前对玩家保持有限信任"
    return f"{character.display_name}当前仍在评估玩家"
