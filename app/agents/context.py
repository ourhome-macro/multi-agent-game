from __future__ import annotations

from app.domain.models import (
    AgentCharacterView,
    AgentContext,
    CasePackage,
    PlayerAction,
    SessionState,
)
from app.rules.engine import relationship_key

RECENT_EVENT_LIMIT = 10


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
            name=character.name,
            role=character.role,
            personality=character.personality,
            speech_style=character.speech_style,
        )
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
        recent_events=session.events[-RECENT_EVENT_LIMIT:],
        memory_candidates=sorted(
            session.memory_candidates.values(),
            key=lambda value: value.memory_id,
        ),
        blocked_fact_ids=blocked_fact_ids,
        revealable_fact_ids=revealable_fact_ids,
        player_action=action,
        target_profile=target_profile,
        default_speech=dialogue.default_speech if dialogue is not None else None,
        default_intent=dialogue.default_intent if dialogue is not None else None,
        reply_options=dialogue.replies if dialogue is not None else [],
        fallback_relationship_delta=(
            dialogue.relationship_delta_on_talk if dialogue is not None else {}
        ),
    )
