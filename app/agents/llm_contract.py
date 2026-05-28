from __future__ import annotations

from typing import Any

from app.domain.models import (
    AgentContext,
    AgentIntent,
    LLMAgentContractInput,
    LLMDisclosureConstraint,
    ProposedActionType,
    SelfKnowledgeItem,
)


def build_llm_agent_input(context: AgentContext) -> LLMAgentContractInput:
    return LLMAgentContractInput(
        agent_context=context,
        disclosure_constraints=_build_disclosure_constraints(context),
    )


def validate_llm_agent_output(payload: dict[str, Any]) -> AgentIntent:
    intent = AgentIntent.model_validate(payload)
    for action in intent.proposed_actions:
        if action.type == ProposedActionType.NARRATIVE_PHASE_CHANGE:
            raise ValueError("LLM Agent output must not propose narrative phase changes")
    return intent


def _build_disclosure_constraints(context: AgentContext) -> list[LLMDisclosureConstraint]:
    constraints: list[LLMDisclosureConstraint] = []
    inner_context = context.inner_context
    if inner_context is not None:
        for item in [
            *inner_context.inner_goals,
            *inner_context.inner_secrets,
            *inner_context.inner_knowledge,
        ]:
            constraints.append(_constraint_from_self_knowledge(item))

    constraints.extend(
        LLMDisclosureConstraint(
            item_id=fact_id,
            item_kind="forbidden_fact",
            allowed_modes=[],
            direct_reveal_allowed=False,
            direct_quote_allowed=False,
            blocked=True,
        )
        for fact_id in context.blocked_fact_ids
    )
    return constraints


def _constraint_from_self_knowledge(item: SelfKnowledgeItem) -> LLMDisclosureConstraint:
    policy = item.disclosure_policy
    return LLMDisclosureConstraint(
        item_id=item.id,
        item_kind=item.kind,
        allowed_modes=policy.allowed_modes,
        direct_reveal_allowed=policy.direct_reveal_allowed,
        direct_quote_allowed=policy.direct_quote_allowed,
        related_clue_ids=item.related_clue_ids,
        blocked=not policy.revealable,
    )
