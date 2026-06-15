from __future__ import annotations

from typing import Any

from app.domain.models import (
    AgentContext,
    AgentIntent,
    CompressedHistoryContext,
    DisclosureMode,
    EventType,
    FactDisclosureStrategy,
    LLMAgentContractInput,
    LLMDisclosureConstraint,
    ProposedActionType,
    SelfKnowledgeItem,
    WorldEvent,
)


class LLMAgentPolicyViolationError(ValueError):
    pass


class LLMAgentPrivateLeakError(ValueError):
    pass


class LLMAgentSchemaError(ValueError):
    pass


def build_llm_agent_input(context: AgentContext) -> LLMAgentContractInput:
    safe_context = _project_context_for_llm(context)
    return LLMAgentContractInput(
        agent_context=safe_context,
        disclosure_constraints=_build_disclosure_constraints(safe_context),
    )


def validate_llm_agent_output(
    payload: dict[str, Any],
    contract_input: LLMAgentContractInput | None = None,
) -> AgentIntent:
    if contract_input is not None:
        allowed_keys = set(contract_input.output_contract.allowed_top_level_keys)
        extra_keys = sorted(set(payload) - allowed_keys)
        if extra_keys:
            raise LLMAgentSchemaError(
                "LLM Agent output contained unsupported top-level keys"
            )
    intent = AgentIntent.model_validate(payload)
    for action in intent.proposed_actions:
        if action.type == ProposedActionType.NARRATIVE_PHASE_CHANGE:
            raise LLMAgentPolicyViolationError(
                "LLM Agent output must not propose narrative phase changes"
            )
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


def _project_context_for_llm(context: AgentContext) -> AgentContext:
    selected_memory_ids = {memory.memory_id for memory in context.memory_snapshots}
    recent_events = _project_recent_events_for_llm(
        context.recent_events,
        selected_memory_ids=selected_memory_ids,
    )
    return context.model_copy(
        update={
            "memory_candidates": [],
            "recent_events": recent_events,
            "compressed_history": _project_compressed_history_for_llm(
                context.compressed_history,
                selected_memory_ids=selected_memory_ids,
                projected_recent_event_ids={event.id for event in recent_events},
            ),
        }
    )


def _project_recent_events_for_llm(
    events: list[WorldEvent],
    *,
    selected_memory_ids: set[str],
) -> list[WorldEvent]:
    projected: list[WorldEvent] = []
    for event in events:
        if event.type not in _MEMORY_EVENT_TYPES:
            projected.append(event)
            continue
        payload = event.payload
        memory_id = payload.get("memory_id") if isinstance(payload, dict) else None
        if not isinstance(memory_id, str) or memory_id not in selected_memory_ids:
            continue
        projected.append(
            event.model_copy(
                update={
                    "payload": {
                        "memory_id": memory_id,
                        "memory_type": payload.get("memory_type"),
                        "memory_scope": payload.get("memory_scope"),
                        "memory_layer": payload.get("memory_layer"),
                        "owner_character_id": payload.get("owner_character_id"),
                        "visible_to_character_ids": payload.get(
                            "visible_to_character_ids",
                            [],
                        ),
                        "selected_for_llm": True,
                        "content_redacted": True,
                    }
                }
            )
        )
    return projected


def _project_compressed_history_for_llm(
    compressed_history: CompressedHistoryContext | None,
    *,
    selected_memory_ids: set[str],
    projected_recent_event_ids: set[str],
) -> CompressedHistoryContext | None:
    if compressed_history is None:
        return None
    return CompressedHistoryContext(
        summary=(
            "Compressed history is available only as selected event and memory ids; "
            "memory content remains limited to memory_snapshots."
        ),
        important_event_ids=[
            event_id
            for event_id in compressed_history.important_event_ids
            if event_id in projected_recent_event_ids
        ],
        important_memory_ids=[
            memory_id
            for memory_id in compressed_history.important_memory_ids
            if memory_id in selected_memory_ids
        ],
        open_threads=[],
        risk_notes=[],
    )


_MEMORY_EVENT_TYPES = {
    EventType.MEMORY_CANDIDATE_CREATED,
    EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
}


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
            raise LLMAgentPrivateLeakError(
                "LLM Agent output must not quote raw private data"
            )
    for portrait in inner_context.inner_portraits:
        for value in [
            portrait.personality_impression,
            portrait.perceived_motive,
            portrait.trust_boundary,
        ]:
            if value and value in serialized_output:
                raise LLMAgentPrivateLeakError(
                    "LLM Agent output must not quote raw private data"
                )


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
            raise LLMAgentPolicyViolationError(
                "LLM Agent output disclosed unconstrained world_info"
            )
        if claim.mode == DisclosureMode.FULL:
            raise LLMAgentPolicyViolationError(
                "LLM Agent output must not request full reveal"
            )
        if claim.mode not in set(constraint.allowed_modes):
            raise LLMAgentPolicyViolationError(
                "LLM Agent output disclosure mode is not allowed"
            )
        if claim.mode in set(constraint.forbidden_modes):
            raise LLMAgentPolicyViolationError(
                "LLM Agent output disclosure mode is forbidden"
            )
        if set(claim.claim_refs) & set(constraint.must_not_claim):
            raise LLMAgentPolicyViolationError(
                "LLM Agent output violates must_not_claim"
            )
