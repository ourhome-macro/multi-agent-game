from __future__ import annotations

from typing import Any

from app.domain.models import (
    AgentContext,
    AgentIntent,
    DisclosureMode,
    FactDisclosureStrategy,
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


def validate_llm_agent_output(
    payload: dict[str, Any],
    contract_input: LLMAgentContractInput | None = None,
) -> AgentIntent:
    intent = AgentIntent.model_validate(payload)
    for action in intent.proposed_actions:
        if action.type == ProposedActionType.NARRATIVE_PHASE_CHANGE:
            raise ValueError("LLM Agent output must not propose narrative phase changes")
    if contract_input is not None:
        _reject_raw_private_echo(intent, contract_input)
        _validate_disclosure_claims(intent, contract_input)
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
            _constraint_from_fact_disclosure_strategy(strategy)
            for strategy in inner_context.fact_disclosure_strategies
        )

    constraints.extend(
        LLMDisclosureConstraint(
            item_id=fact_id,
            item_kind="forbidden_fact",
            allowed_modes=[],
            forbidden_modes=[],
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
        forbidden_modes=[],
        direct_reveal_allowed=policy.direct_reveal_allowed,
        direct_quote_allowed=policy.direct_quote_allowed,
        related_clue_ids=item.related_clue_ids,
        related_world_info_ids=item.related_world_info_ids,
        blocked=not policy.revealable,
    )


def _constraint_from_fact_disclosure_strategy(
    strategy: FactDisclosureStrategy,
) -> LLMDisclosureConstraint:
    return LLMDisclosureConstraint(
        item_id=strategy.world_info_id,
        item_kind="world_info",
        allowed_modes=strategy.allowed_modes,
        forbidden_modes=strategy.forbidden_modes,
        direct_reveal_allowed=False,
        direct_quote_allowed=False,
        related_clue_ids=strategy.evidence_clue_ids,
        related_world_info_ids=[strategy.world_info_id],
        rhetoric_tactics=strategy.rhetoric_tactics,
        must_not_claim=strategy.must_not_claim,
        safe_fact_refs=strategy.safe_fact_refs,
        blocked=DisclosureMode.FULL in strategy.forbidden_modes,
    )


def _reject_raw_private_echo(
    intent: AgentIntent,
    contract_input: LLMAgentContractInput,
) -> None:
    inner_context = contract_input.agent_context.inner_context
    if inner_context is None:
        return

    serialized_output = intent.model_dump_json()
    for item in [
        *inner_context.inner_goals,
        *inner_context.inner_secrets,
        *inner_context.inner_knowledge,
    ]:
        if item.disclosure_policy.direct_quote_allowed:
            continue
        if item.summary and item.summary in serialized_output:
            raise ValueError("LLM Agent output must not quote raw private data")
    for portrait in inner_context.inner_portraits:
        for value in [
            portrait.personality_impression,
            portrait.perceived_motive,
            portrait.trust_boundary,
        ]:
            if value and value in serialized_output:
                raise ValueError("LLM Agent output must not quote raw private data")


def _validate_disclosure_claims(
    intent: AgentIntent,
    contract_input: LLMAgentContractInput,
) -> None:
    world_info_constraints = {
        constraint.item_id: constraint
        for constraint in contract_input.disclosure_constraints
        if constraint.item_kind == "world_info"
    }
    for claim in intent.disclosure_claims:
        constraint = world_info_constraints.get(claim.world_info_id)
        if constraint is None:
            raise ValueError("LLM Agent output disclosed unconstrained world_info")
        if claim.mode == DisclosureMode.FULL:
            raise ValueError("LLM Agent output must not request full reveal")
        if claim.mode not in set(constraint.allowed_modes):
            raise ValueError("LLM Agent output disclosure mode is not allowed")
        if claim.mode in set(constraint.forbidden_modes):
            raise ValueError("LLM Agent output disclosure mode is forbidden")
        if set(claim.claim_refs) & set(constraint.must_not_claim):
            raise ValueError("LLM Agent output violates must_not_claim")
