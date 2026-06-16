from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeVar
from uuid import NAMESPACE_URL, uuid5

from app.agents.npc_skills import NpcSkillSelector
from app.agents.retrieval_planner import MemoryRetrievalPlan, RetrievalPlanner
from app.domain.models import (
    AgentContext,
    AgentIntentType,
    CasePackage,
    DisclosureMode,
    LLMAgentOutputContract,
    NpcSkillProjection,
    PlayerAction,
    ProposedActionType,
    RhetoricTactic,
    SessionState,
)
from app.runtime.security import PromptInjectionReview

TStrEnum = TypeVar("TStrEnum", bound=StrEnum)


@dataclass(frozen=True)
class AgentTurnPlan:
    plan_id: str = ""
    memory_retrieval_plan: MemoryRetrievalPlan | None = None
    selected_skill_ids: list[str] | None = None
    output_contract: LLMAgentOutputContract | None = None
    security_flags: list[str] = field(default_factory=list)
    security_hard_restriction: bool = False
    allowed_intents: list[AgentIntentType] | None = None
    max_disclosure_mode: DisclosureMode | None = None
    recommended_response_mode: str | None = None

    @classmethod
    def from_security_review(cls, review: PromptInjectionReview) -> AgentTurnPlan:
        return cls(
            security_flags=review.security_flags,
            security_hard_restriction=review.requires_hard_restriction,
            allowed_intents=review.allowed_intents,
            max_disclosure_mode=review.max_disclosure_mode,
            recommended_response_mode=review.recommended_response_mode,
        )


def build_agent_turn_plan(
    *,
    case: CasePackage,
    session: SessionState,
    action: PlayerAction,
    context: AgentContext | None = None,
    retrieval_planner: RetrievalPlanner | None = None,
    memory_retrieval_plan: MemoryRetrievalPlan | None = None,
    security_review: PromptInjectionReview | None = None,
) -> AgentTurnPlan:
    memory_plan = (
        memory_retrieval_plan
        if memory_retrieval_plan is not None
        else (retrieval_planner or RetrievalPlanner()).plan(
            case=case,
            session=session,
            action=action,
        )
    )
    skill_projections = (
        context.npc_skill_projections
        if context is not None
        else NpcSkillSelector().select(
            case=case,
            session=session,
            action=action,
        ).projections
    )
    security_plan = (
        AgentTurnPlan.from_security_review(security_review)
        if security_review is not None
        else None
    )
    output_contract = build_skill_aware_output_contract(
        context=context,
        skill_projections=skill_projections,
        security_plan=security_plan,
    )
    plan_id = _plan_id(
        session_id=session.id,
        target_id=action.target_id,
        action_type=action.type.value,
        memory_skill_id=memory_plan.skill_id,
        selected_skill_ids=[skill.skill_id for skill in skill_projections],
        security_flags=security_plan.security_flags if security_plan is not None else [],
    )
    return AgentTurnPlan(
        plan_id=plan_id,
        memory_retrieval_plan=memory_plan,
        selected_skill_ids=[skill.skill_id for skill in skill_projections],
        output_contract=output_contract,
        security_flags=security_plan.security_flags if security_plan is not None else [],
        security_hard_restriction=(
            security_plan.security_hard_restriction if security_plan is not None else False
        ),
        allowed_intents=security_plan.allowed_intents if security_plan is not None else None,
        max_disclosure_mode=(
            security_plan.max_disclosure_mode if security_plan is not None else None
        ),
        recommended_response_mode=(
            security_plan.recommended_response_mode if security_plan is not None else None
        ),
    )


def build_skill_aware_output_contract(
    *,
    context: AgentContext | None,
    skill_projections: list[NpcSkillProjection] | None = None,
    security_plan: AgentTurnPlan | None = None,
) -> LLMAgentOutputContract:
    contract = LLMAgentOutputContract()
    skills = (
        list(skill_projections)
        if skill_projections is not None
        else list(context.npc_skill_projections) if context is not None else []
    )
    if skills:
        allowed_intents = _ordered_enum_values(
            AgentIntentType,
            {
                intent
                for skill in skills
                for intent in skill.allowed_intents
            },
        )
        allowed_tactics = _ordered_enum_values(
            RhetoricTactic,
            {
                tactic
                for skill in skills
                for tactic in skill.allowed_tactics
            },
        )
        allowed_action_types = _ordered_enum_values(
            ProposedActionType,
            {
                action_type
                for skill in skills
                for action_type in skill.allowed_proposed_actions
            },
        )
        max_relationship_delta = _merge_max_relationship_delta(
            skill.max_relationship_delta for skill in skills
        )
        contract = contract.model_copy(
            update={
                "allowed_intents": allowed_intents,
                "allowed_rhetoric_tactics": allowed_tactics,
                "allowed_proposed_action_types": allowed_action_types,
                "max_relationship_delta": max_relationship_delta,
            }
        )
    else:
        contract = contract.model_copy(
            update={"allowed_proposed_action_types": []}
        )

    if security_plan is not None and security_plan.security_hard_restriction:
        update: dict[str, object] = {}
        if security_plan.allowed_intents is not None:
            update["allowed_intents"] = [
                intent
                for intent in contract.allowed_intents
                if intent in set(security_plan.allowed_intents)
            ] or list(security_plan.allowed_intents)
        if security_plan.max_disclosure_mode is not None:
            update["allowed_disclosure_modes"] = [
                mode
                for mode in contract.allowed_disclosure_modes
                if _disclosure_mode_index(mode)
                <= _disclosure_mode_index(security_plan.max_disclosure_mode)
            ]
        if update:
            contract = contract.model_copy(update=update)
    return contract


def _ordered_enum_values(
    enum_type: type[TStrEnum],
    values: set[TStrEnum],
) -> list[TStrEnum]:
    return [item for item in enum_type if item in values]


def _merge_max_relationship_delta(
    delta_maps: Iterable[dict[str, float]],
) -> dict[str, float]:
    merged: dict[str, float] = {}
    for delta_map in delta_maps:
        for metric, value in delta_map.items():
            numeric = abs(float(value))
            current = merged.get(str(metric))
            if current is None or numeric > current:
                merged[str(metric)] = numeric
    return merged


def _disclosure_mode_index(mode: DisclosureMode) -> int:
    return list(DisclosureMode).index(mode)


def _plan_id(
    *,
    session_id: str,
    target_id: str,
    action_type: str,
    memory_skill_id: str,
    selected_skill_ids: list[str],
    security_flags: list[str],
) -> str:
    material = "|".join(
        [
            session_id,
            target_id,
            action_type,
            memory_skill_id,
            ",".join(selected_skill_ids),
            ",".join(security_flags),
        ]
    )
    return f"agent_turn_plan.{uuid5(NAMESPACE_URL, material)}"
