from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.disclosure_strategy import DISCLOSURE_MODE_ORDER
from app.domain.models import (
    ActionType,
    AgentIntentType,
    CasePackage,
    DisclosureMode,
    NpcSkillConfig,
    NpcSkillPriority,
    NpcSkillProjection,
    PlayerAction,
    RelationshipState,
    SessionState,
)
from app.rules.engine import relationship_key
from app.runtime.pressure import calculate_interaction_pressure


@dataclass(frozen=True)
class NpcSkillSelection:
    projections: list[NpcSkillProjection]
    available_skill_ids: list[str]
    rejected_reasons: dict[str, str] = field(default_factory=dict)


class NpcSkillSelector:
    def select(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> NpcSkillSelection:
        relationship = session.relationships.get(relationship_key(action.target_id, "player"))
        player_world_info_ids = {
            knowledge.world_info_id
            for knowledge in session.player_knowledge.values()
            if knowledge.world_info_id is not None
        }
        player_knowledge_ids = set(session.player_knowledge)
        pressure = calculate_interaction_pressure(case, action)
        projections: list[NpcSkillProjection] = []
        rejected_reasons: dict[str, str] = {}
        for skill in sorted(case.npc_skills, key=_skill_sort_key):
            reason = _rejection_reason(
                skill,
                session=session,
                action=action,
                relationship=relationship,
                player_knowledge_ids=player_knowledge_ids,
                player_world_info_ids=player_world_info_ids,
                pressure=pressure,
            )
            if reason is not None:
                rejected_reasons[skill.id] = reason
                continue
            projections.append(_project_skill(skill))
        return NpcSkillSelection(
            projections=projections,
            available_skill_ids=[projection.skill_id for projection in projections],
            rejected_reasons=rejected_reasons,
        )


def _rejection_reason(
    skill: NpcSkillConfig,
    *,
    session: SessionState,
    action: PlayerAction,
    relationship: RelationshipState | None,
    player_knowledge_ids: set[str],
    player_world_info_ids: set[str],
    pressure: float,
) -> str | None:
    if action.target_id not in set(skill.owner_character_ids):
        return "owner_mismatch"
    if not _trigger_matches(skill, action):
        return "trigger_mismatch"
    conditions = skill.unlock_conditions
    if conditions.phases and session.narrative.phase not in set(conditions.phases):
        return "phase_locked"
    if not set(conditions.completed_beats).issubset(session.narrative.completed_beats):
        return "beat_locked"
    if not set(conditions.required_discovered_clues).issubset(session.discovered_clues):
        return "clue_locked"
    if not set(conditions.required_player_knowledge).issubset(player_knowledge_ids):
        return "player_knowledge_locked"
    if not set(conditions.required_world_info_ids).issubset(player_world_info_ids):
        return "world_info_locked"
    if conditions.required_pressure_min is not None and pressure < conditions.required_pressure_min:
        return "pressure_locked"
    if _relationship_locked(relationship, skill):
        return "relationship_locked"
    return None


def _trigger_matches(skill: NpcSkillConfig, action: PlayerAction) -> bool:
    triggers = skill.triggers
    if triggers.action_types and action.type not in set(triggers.action_types):
        return False
    if (
        action.type == ActionType.ASK_ABOUT
        and triggers.subject_types
        and action.subject_type not in set(triggers.subject_types)
    ):
        return False
    if triggers.subject_ids and action.subject_id not in set(triggers.subject_ids):
        return False
    if triggers.clue_ids:
        if action.clue_id not in set(triggers.clue_ids) and action.subject_id not in set(
            triggers.clue_ids
        ):
            return False
    return True


def _relationship_locked(
    relationship: RelationshipState | None,
    skill: NpcSkillConfig,
) -> bool:
    conditions = skill.unlock_conditions
    if relationship is None:
        return any(
            value is not None
            for value in [
                conditions.suspicion_min,
                conditions.trust_min,
                conditions.fear_min,
            ]
        )
    if conditions.suspicion_min is not None and relationship.suspicion < conditions.suspicion_min:
        return True
    if conditions.trust_min is not None and relationship.trust < conditions.trust_min:
        return True
    if conditions.fear_min is not None and relationship.fear < conditions.fear_min:
        return True
    return False


def _project_skill(skill: NpcSkillConfig) -> NpcSkillProjection:
    return NpcSkillProjection(
        skill_id=skill.id,
        type=skill.type,
        level=skill.level,
        signature=skill.signature,
        allowed_intents=_allowed_intents(skill),
        allowed_tactics=list(skill.disclosure.allowed_tactics),
        max_disclosure_mode_by_world_info={
            world_info_id: skill.disclosure.max_mode
            for world_info_id in skill.disclosure.world_info_ids
        },
        safe_fragment_refs=list(skill.disclosure.safe_fragment_refs),
        memory_plan_id=skill.id if _skill_has_memory_policy(skill) else None,
        allowed_proposed_actions=list(skill.proposed_action_policy.allowed),
    )


def _allowed_intents(skill: NpcSkillConfig) -> list[AgentIntentType]:
    max_mode = skill.disclosure.max_mode
    if max_mode in {DisclosureMode.NONE, DisclosureMode.DENY}:
        return [AgentIntentType.REFUSE, AgentIntentType.CONCEAL]
    if max_mode == DisclosureMode.DEFLECT:
        return [AgentIntentType.CONCEAL, AgentIntentType.PROBE, AgentIntentType.REFUSE]
    if max_mode in {DisclosureMode.HINT, DisclosureMode.PARTIAL}:
        return [AgentIntentType.ANSWER, AgentIntentType.CONCEAL, AgentIntentType.PROBE]
    return [AgentIntentType.CONCEAL]


def _skill_has_memory_policy(skill: NpcSkillConfig) -> bool:
    return bool(
        skill.memory.include_types
        or skill.memory.include_scopes
        or skill.memory.include_layers
        or skill.memory.topic_tags
        or skill.memory.max_items is not None
    )


def _skill_sort_key(skill: NpcSkillConfig) -> tuple[int, int, str]:
    priority_rank = {
        NpcSkillPriority.HIGH: 0,
        NpcSkillPriority.MEDIUM: 1,
        NpcSkillPriority.LOW: 2,
    }
    return (priority_rank[skill.priority], -skill.level, skill.id)


def disclosure_mode_at_most(mode: DisclosureMode, max_mode: DisclosureMode) -> bool:
    return DISCLOSURE_MODE_ORDER.index(mode) <= DISCLOSURE_MODE_ORDER.index(max_mode)

