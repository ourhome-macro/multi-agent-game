from __future__ import annotations

from app.agents.npc_skills import NpcSkillSelection
from app.agents.retrieval_planner import MemoryRetrievalPlan
from app.domain.models import CasePackage, NpcSkillConfig


def build_final_memory_retrieval_plan(
    *,
    base_plan: MemoryRetrievalPlan,
    case: CasePackage,
    npc_skill_selection: NpcSkillSelection,
) -> MemoryRetrievalPlan:
    selected_policy_skills = _selected_skills_with_memory_policy(
        case=case,
        selected_skill_ids=npc_skill_selection.available_skill_ids,
    )
    if not selected_policy_skills:
        return _with_final_plan_source(base_plan, npc_skill_policy_ids=())

    included_types = base_plan.included_memory_types
    included_scopes = base_plan.included_scopes
    included_layers = base_plan.included_layers
    included_topic_tags = base_plan.included_topic_tags
    max_memory_items = base_plan.max_memory_items

    for skill in selected_policy_skills:
        policy = skill.memory
        if policy.include_types:
            included_types = _ordered_intersection(
                included_types,
                tuple(str(item) for item in policy.include_types),
            )
        if policy.include_scopes:
            included_scopes = _without_forbidden(
                _ordered_intersection(
                    included_scopes,
                    tuple(str(item) for item in policy.include_scopes),
                ),
                base_plan.forbidden_scopes,
            )
        if policy.include_layers:
            included_layers = _without_forbidden(
                _ordered_intersection(
                    included_layers,
                    tuple(str(item) for item in policy.include_layers),
                ),
                base_plan.forbidden_layers,
            )
        if policy.topic_tags:
            policy_tags = tuple(str(item) for item in policy.topic_tags)
            included_topic_tags = (
                _ordered_intersection(included_topic_tags, policy_tags)
                if included_topic_tags
                else policy_tags
            )
        if policy.max_items is not None:
            max_memory_items = min(max_memory_items, int(policy.max_items))

    return MemoryRetrievalPlan(
        skill_id=base_plan.skill_id,
        included_memory_types=included_types,
        included_scopes=included_scopes,
        included_layers=included_layers,
        forbidden_scopes=base_plan.forbidden_scopes,
        forbidden_layers=base_plan.forbidden_layers,
        max_memory_items=max_memory_items,
        inject_portrait_summary=base_plan.inject_portrait_summary,
        allow_recent_events=base_plan.allow_recent_events,
        handoff_to_director=base_plan.handoff_to_director,
        disclosure_level=base_plan.disclosure_level,
        included_topic_tags=included_topic_tags,
        base_memory_skill_id=base_plan.base_memory_skill_id or base_plan.skill_id,
        npc_skill_policy_ids=tuple(skill.id for skill in selected_policy_skills),
    )


def _with_final_plan_source(
    base_plan: MemoryRetrievalPlan,
    *,
    npc_skill_policy_ids: tuple[str, ...],
) -> MemoryRetrievalPlan:
    if (
        (base_plan.base_memory_skill_id or base_plan.skill_id) == base_plan.base_memory_skill_id
        and base_plan.npc_skill_policy_ids == npc_skill_policy_ids
    ):
        return base_plan
    return MemoryRetrievalPlan(
        skill_id=base_plan.skill_id,
        included_memory_types=base_plan.included_memory_types,
        included_scopes=base_plan.included_scopes,
        included_layers=base_plan.included_layers,
        forbidden_scopes=base_plan.forbidden_scopes,
        forbidden_layers=base_plan.forbidden_layers,
        max_memory_items=base_plan.max_memory_items,
        inject_portrait_summary=base_plan.inject_portrait_summary,
        allow_recent_events=base_plan.allow_recent_events,
        handoff_to_director=base_plan.handoff_to_director,
        disclosure_level=base_plan.disclosure_level,
        included_topic_tags=base_plan.included_topic_tags,
        base_memory_skill_id=base_plan.base_memory_skill_id or base_plan.skill_id,
        npc_skill_policy_ids=npc_skill_policy_ids,
    )


def _selected_skills_with_memory_policy(
    *,
    case: CasePackage,
    selected_skill_ids: list[str],
) -> list[NpcSkillConfig]:
    selected_ids = set(selected_skill_ids)
    return [
        skill
        for skill in case.npc_skills
        if skill.id in selected_ids and _has_memory_policy(skill)
    ]


def _has_memory_policy(skill: NpcSkillConfig) -> bool:
    return bool(
        skill.memory.include_types
        or skill.memory.include_scopes
        or skill.memory.include_layers
        or skill.memory.topic_tags
        or skill.memory.max_items is not None
    )


def _ordered_intersection(
    current: tuple[str, ...],
    policy: tuple[str, ...],
) -> tuple[str, ...]:
    policy_set = set(policy)
    return tuple(item for item in current if item in policy_set)


def _without_forbidden(
    values: tuple[str, ...],
    forbidden: tuple[str, ...],
) -> tuple[str, ...]:
    forbidden_set = set(forbidden)
    return tuple(value for value in values if value not in forbidden_set)
