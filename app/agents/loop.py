from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import ValidationError

from app.agents.context import build_agent_context
from app.agents.disclosure_strategy import DISCLOSURE_MODE_ORDER
from app.agents.final_retrieval_plan import build_final_memory_retrieval_plan
from app.agents.gateway import AgentGateway
from app.agents.llm_contract import (
    LLMAgentPolicyViolationError,
    LLMAgentPrivateLeakError,
    LLMAgentSchemaError,
    build_llm_agent_input,
    validate_llm_agent_output,
)
from app.agents.memory import MemoryRetriever
from app.agents.npc_skills import NpcSkillSelection, NpcSkillSelector
from app.agents.prompt_builder import PromptBuilder
from app.agents.retrieval_planner import MemoryRetrievalPlan, RetrievalPlanner
from app.agents.tools.runtime import ToolRuntime
from app.agents.turn_plan import AgentTurnPlan, build_agent_turn_plan
from app.director.narrative_director import NarrativeDirector
from app.domain.models import (
    AgentContext,
    AgentIntent,
    AgentIntentType,
    AgentMemorySnapshot,
    CasePackage,
    DisclosureMode,
    LLMAgentContractInput,
    LLMAgentOutputContract,
    LLMErrorSummary,
    LLMErrorType,
    PlayerAction,
    PromptBundle,
    SafeFactFragmentProjection,
    SessionState,
)
from app.runtime.budget import ContextBudgetManager, ContextBudgetResult
from app.runtime.security import PromptInjectionGuard
from app.runtime.tracing import RuntimeTraceDraft, RuntimeTracer


@dataclass(frozen=True)
class AgentTurnResult:
    context: AgentContext
    intent: AgentIntent
    trace: RuntimeTraceDraft
    security_flags: list[str]
    memory_ids_used: list[str]
    npc_skill_selection: NpcSkillSelection


class AgentLoop:
    def __init__(
        self,
        *,
        agent_gateway: AgentGateway,
        prompt_builder: PromptBuilder | None = None,
        injection_guard: PromptInjectionGuard | None = None,
        runtime_tracer: RuntimeTracer | None = None,
        memory_retriever: MemoryRetriever | None = None,
        retrieval_planner: RetrievalPlanner | None = None,
        context_budget_manager: ContextBudgetManager | None = None,
        tool_runtime: ToolRuntime | None = None,
        narrative_director: NarrativeDirector | None = None,
    ) -> None:
        self._agent_gateway = agent_gateway
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._injection_guard = injection_guard or PromptInjectionGuard()
        self._runtime_tracer = runtime_tracer or RuntimeTracer.disabled()
        self._memory_retriever = memory_retriever or MemoryRetriever()
        self._retrieval_planner = retrieval_planner or RetrievalPlanner()
        self._context_budget_manager = (
            context_budget_manager or ContextBudgetManager()
        )
        self._tool_runtime = tool_runtime or ToolRuntime(
            memory_retriever=self._memory_retriever
        )
        self._narrative_director = narrative_director or NarrativeDirector()

    @property
    def backend_name(self) -> str:
        return self._agent_gateway.backend_name

    @property
    def prompt_builder(self) -> PromptBuilder:
        return self._prompt_builder

    def build_context(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> AgentContext:
        plan, npc_skill_selection = self._final_memory_plan(
            case=case,
            session=session,
            action=action,
        )
        retrieved_memories = self._memory_retriever.retrieve(
            case=case,
            session=session,
            action=action,
            plan=plan,
        )
        context = build_agent_context(
            case,
            session,
            action,
            retrieval_plan=plan,
            memory_snapshots=retrieved_memories,
            npc_skill_selection=npc_skill_selection,
        )
        return self._attach_director_generation_constraints(
            case=case,
            session=session,
            context=context,
        )

    def plan_turn(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
        context: AgentContext | None = None,
    ) -> AgentTurnPlan:
        context = context or self.build_context(
            case=case,
            session=session,
            action=action,
        )
        return build_agent_turn_plan(
            case=case,
            session=session,
            action=action,
            context=context,
            retrieval_planner=self._retrieval_planner,
            security_review=self._injection_guard.review(action),
        )

    def run_turn(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> AgentTurnResult:
        phase_before = session.narrative.phase
        plan, npc_skill_selection = self._final_memory_plan(
            case=case,
            session=session,
            action=action,
        )
        retrieved_memories = self._memory_retriever.retrieve(
            case=case,
            session=session,
            action=action,
            plan=plan,
        )
        context = build_agent_context(
            case,
            session,
            action,
            retrieval_plan=plan,
            memory_snapshots=retrieved_memories,
            npc_skill_selection=npc_skill_selection,
        )
        context = self._attach_director_generation_constraints(
            case=case,
            session=session,
            context=context,
        )
        security_review = self._injection_guard.review(action)
        turn_plan = build_agent_turn_plan(
            case=case,
            session=session,
            action=action,
            context=context,
            memory_retrieval_plan=plan,
            security_review=security_review,
        )
        memory_ids = [snapshot.memory_id for snapshot in retrieved_memories]
        memory_projection = _memory_projection(
            plan,
            retrieved_memories,
            context,
            store_trace_summary=_memory_store_trace_summary(self._memory_retriever),
            authority_trace_summary=_memory_authority_trace_summary(
                self._memory_retriever
            ),
            retrieval_trace_summary=_memory_retrieval_trace_summary(
                self._memory_retriever
            ),
        )
        npc_skill_projection = _npc_skill_projection(context)
        prompt_bundle = self._prompt_builder.build(context)
        budget = self._budget_prompt(prompt_bundle, context, memory_ids)
        if budget.compressed_history is not None:
            context = context.model_copy(
                update={
                    "compressed_history": budget.compressed_history.to_context(),
                }
            )
            prompt_bundle = self._prompt_builder.build(context)
            budget = self._budget_prompt(prompt_bundle, context, memory_ids)
        tool_calls = [
            self._tool_runtime.call(
                "search_memory",
                case=case,
                session=session,
                action=action,
                plan=plan,
                memory_snapshots=retrieved_memories,
            ).summary
        ]
        trace = self._runtime_tracer.start_turn(
            case_id=case.meta.id,
            session_id=session.id,
            action=action,
            target_agent_id=action.target_id,
            agent_backend=self._agent_gateway.backend_name,
            model=self._agent_gateway.model_name,
            phase_before=phase_before,
            context_tokens_estimated=budget.context_tokens_estimated,
            context_budget_ratio=budget.context_budget_ratio,
            compression_used=budget.compression_used,
            memory_ids_used=memory_ids,
            memory_projection=memory_projection,
            npc_skill_projection=npc_skill_projection,
            context_layer_budget=_context_layer_budget_projection(
                budget,
                context=context,
                memory_ids=memory_ids,
            ),
            tool_calls=tool_calls,
            security_flags=security_review.security_flags,
            turn_plan_id=turn_plan.plan_id,
            output_contract_summary=_output_contract_trace_summary(
                turn_plan.output_contract
            ),
        )
        contract_input = build_llm_agent_input(context, turn_plan=turn_plan)
        if budget.hard_context_over_limit:
            return AgentTurnResult(
                context=context,
                intent=_hard_context_over_limit_intent(
                    backend=self._agent_gateway.backend_name,
                    contract_input=contract_input,
                    fallback_reason=budget.fallback_reason,
                ),
                trace=trace,
                security_flags=security_review.security_flags,
                memory_ids_used=memory_ids,
                npc_skill_selection=npc_skill_selection,
            )
        intent = self._validate_agent_intent(
            context,
            self._agent_gateway.generate(
                context,
                contract_input=contract_input,
            ),
            contract_input=contract_input,
        )
        return AgentTurnResult(
            context=context,
            intent=intent,
            trace=trace,
            security_flags=security_review.security_flags,
            memory_ids_used=memory_ids,
            npc_skill_selection=npc_skill_selection,
        )

    def _final_memory_plan(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> tuple[MemoryRetrievalPlan, NpcSkillSelection]:
        base_plan = self._retrieval_planner.plan(case=case, session=session, action=action)
        npc_skill_selection = NpcSkillSelector().select(
            case=case,
            session=session,
            action=action,
        )
        return (
            build_final_memory_retrieval_plan(
                base_plan=base_plan,
                case=case,
                npc_skill_selection=npc_skill_selection,
            ),
            npc_skill_selection,
        )

    def _validate_agent_intent(
        self,
        context: AgentContext,
        intent: AgentIntent,
        *,
        turn_plan: AgentTurnPlan | None = None,
        contract_input: LLMAgentContractInput | None = None,
    ) -> AgentIntent:
        contract_input = (
            contract_input
            if contract_input is not None
            else build_llm_agent_input(context, turn_plan=turn_plan)
        )
        payload = intent.model_dump(
            mode="json",
            exclude={"llm_error"},
        )
        try:
            validated = validate_llm_agent_output(payload, contract_input)
        except LLMAgentPolicyViolationError as exc:
            return AgentIntent(
                speech=intent.speech,
                intent=contract_input.output_contract.fallback_intent,
                emotional_shift={},
                proposed_actions=[],
                memory_refs=[],
                disclosure_claims=[],
                llm_error=_contract_error_summary(
                    exc,
                    error_type=LLMErrorType.POLICY_VIOLATION,
                    backend=self._agent_gateway.backend_name,
                ),
            )
        except LLMAgentPrivateLeakError as exc:
            return AgentIntent(
                speech="I cannot answer that safely.",
                intent=AgentIntentType.REFUSE,
                emotional_shift={},
                proposed_actions=[],
                memory_refs=[],
                disclosure_claims=[],
                llm_error=_contract_error_summary(
                    exc,
                    error_type=LLMErrorType.PRIVATE_LEAK_DETECTED,
                    backend=self._agent_gateway.backend_name,
                ),
            )
        except LLMAgentSchemaError as exc:
            return AgentIntent(
                speech="I cannot answer that safely.",
                intent=AgentIntentType.REFUSE,
                emotional_shift={},
                proposed_actions=[],
                memory_refs=[],
                disclosure_claims=[],
                llm_error=_contract_error_summary(
                    exc,
                    error_type=LLMErrorType.SCHEMA_ERROR,
                    backend=self._agent_gateway.backend_name,
                ),
            )
        except ValidationError as exc:
            return AgentIntent(
                speech="I cannot answer that safely.",
                intent=AgentIntentType.REFUSE,
                emotional_shift={},
                proposed_actions=[],
                memory_refs=[],
                disclosure_claims=[],
                llm_error=_contract_error_summary(
                    exc,
                    error_type=LLMErrorType.SCHEMA_ERROR,
                    backend=self._agent_gateway.backend_name,
                ),
            )
        if intent.llm_error is None:
            return validated
        return validated.model_copy(update={"llm_error": intent.llm_error})

    def _attach_director_generation_constraints(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        context: AgentContext,
    ) -> AgentContext:
        safe_fragments = self._narrative_director.safe_fragment_constraints(
            case,
            session.narrative,
            context,
        )
        safe_fragments = tuple(_skill_limited_safe_fragments(context, safe_fragments))
        if not safe_fragments:
            return context
        return context.model_copy(
            update={"director_safe_fragments": list(safe_fragments)}
        )

    def _budget_prompt(
        self,
        prompt_bundle: PromptBundle,
        context: AgentContext,
        memory_ids: list[str],
    ) -> ContextBudgetResult:
        prompt_text = (
            prompt_bundle.agent_prompt
            + prompt_bundle.contract_instruction
            + prompt_bundle.safety_instruction
        )
        return self._context_budget_manager.apply(
            prompt_text=prompt_text,
            hard_context_text=_hard_context_budget_text(context),
            soft_context_text=_soft_context_budget_text(context),
            memory_ids=memory_ids,
            recent_event_ids=[event.id for event in context.recent_events],
        )

    def finish_trace(
        self,
        turn: AgentTurnResult,
        *,
        director_allowed: bool,
        director_reason_category: str | None,
        rule_rejections: list[str],
        new_events: list[object],
        phase_after: str,
        public_speech: str | None = None,
        public_speech_source: str | None = None,
        status: str = "ok",
        error_category: str | None = None,
    ) -> None:
        self._runtime_tracer.finish_turn(
            turn.trace,
            intent=turn.intent,
            director_allowed=director_allowed,
            director_reason_category=director_reason_category,
            rule_rejections=rule_rejections,
            new_events=new_events,  # type: ignore[arg-type]
            phase_after=phase_after,
            public_speech=public_speech,
            public_speech_source=public_speech_source,
            status=status,
            error_category=error_category,
        )


def _memory_projection(
    plan: MemoryRetrievalPlan,
    memories: list[AgentMemorySnapshot],
    context: AgentContext | None = None,
    store_trace_summary: object | None = None,
    authority_trace_summary: object | None = None,
    retrieval_trace_summary: object | None = None,
) -> dict[str, object]:
    summary = plan.trace_summary(selected_count=len(memories))
    summary["items"] = [
        {
            "memory_id": memory.memory_id,
            "memory_type": memory.memory_type,
            "memory_scope": memory.memory_scope,
            "memory_layer": memory.memory_layer,
            "owner_character_id": memory.owner_character_id,
            "visible_to_character_ids": list(memory.visible_to_character_ids),
        }
        for memory in memories
    ]
    if context is not None:
        summary["director_safe_fragment_refs"] = [
            fragment.ref for fragment in context.director_safe_fragments
        ]
    if store_trace_summary is not None:
        summary["store"] = {
            "backend": getattr(store_trace_summary, "backend", ""),
            "candidate_count": int(getattr(store_trace_summary, "candidate_count", 0)),
            "requested_filters": getattr(
                store_trace_summary,
                "requested_filters",
                {},
            ),
        }
    if retrieval_trace_summary is not None:
        try:
            summary["retrieval_diagnostics"] = retrieval_trace_summary.to_projection()
        except AttributeError:
            summary["retrieval_diagnostics"] = {}
    if authority_trace_summary is not None:
        summary.update(authority_trace_summary.to_projection())
    return summary


def _memory_store_trace_summary(memory_retriever: MemoryRetriever) -> object | None:
    try:
        return memory_retriever.last_store_trace_summary
    except AttributeError:
        return None


def _memory_authority_trace_summary(memory_retriever: MemoryRetriever) -> object | None:
    try:
        return memory_retriever.last_authority_trace_summary
    except AttributeError:
        return None


def _memory_retrieval_trace_summary(memory_retriever: MemoryRetriever) -> object | None:
    try:
        return memory_retriever.last_retrieval_trace_summary
    except AttributeError:
        return None


def _npc_skill_projection(context: AgentContext) -> dict[str, object]:
    return {
        "selected_skill_ids": [
            skill.skill_id for skill in context.npc_skill_projections
        ],
        "skill_safe_fragment_refs": sorted(
            {
                ref
                for skill in context.npc_skill_projections
                for ref in skill.safe_fragment_refs
            }
        ),
        "items": [
            skill.model_dump(mode="json")
            for skill in context.npc_skill_projections
        ],
    }


def _output_contract_trace_summary(
    contract: LLMAgentOutputContract | None,
) -> dict[str, object]:
    if contract is None:
        return {}
    return {
        "allowed_intents": [
            intent.value for intent in contract.allowed_intents
        ],
        "allowed_rhetoric_tactics": [
            tactic.value for tactic in contract.allowed_rhetoric_tactics
        ],
        "allowed_proposed_action_types": [
            action_type.value
            for action_type in contract.allowed_proposed_action_types
        ],
        "allowed_disclosure_modes": [
            mode.value for mode in contract.allowed_disclosure_modes
        ],
        "max_relationship_delta": {
            str(metric): float(value)
            for metric, value in contract.max_relationship_delta.items()
        },
        "fallback_intent": contract.fallback_intent.value,
    }


def _context_layer_budget_projection(
    budget: ContextBudgetResult,
    *,
    context: AgentContext,
    memory_ids: list[str],
) -> dict[str, object]:
    return {
        "compression_scope": budget.compression_scope,
        "compressed_layers": budget.compressed_layers or [],
        "hard_context_tokens_estimated": budget.hard_context_tokens_estimated,
        "soft_context_tokens_estimated": budget.soft_context_tokens_estimated,
        "hard_context_over_limit": budget.hard_context_over_limit,
        "fallback_reason": budget.fallback_reason,
        "hard_context_preserved": budget.compression_scope != "hard_context_over_limit",
        "soft_recent_event_count": len(context.recent_events),
        "selected_memory_count": len(memory_ids),
        "provider": budget.provider,
        "model": budget.model,
        "context_limit_tokens": budget.context_limit_tokens,
        "available_input_tokens": budget.available_input_tokens,
        "reserved_output_tokens": budget.reserved_output_tokens,
        "safety_margin_tokens": budget.safety_margin_tokens,
        "conservative_multiplier": budget.conservative_multiplier,
        "token_estimator_method": budget.token_estimator_method,
    }


def _hard_context_over_limit_intent(
    *,
    backend: str,
    contract_input: LLMAgentContractInput,
    fallback_reason: str | None,
) -> AgentIntent:
    reason = fallback_reason or "hard_context_over_limit"
    return AgentIntent(
        speech="I cannot answer that safely right now.",
        intent=contract_input.output_contract.fallback_intent,
        emotional_shift={},
        proposed_actions=[],
        memory_refs=[],
        disclosure_claims=[],
        llm_error=LLMErrorSummary(
            backend=backend,
            error_type=LLMErrorType.CONTEXT_OVER_LIMIT,
            error_message_sanitized=reason,
            fallback_used=True,
        ),
    )


def _hard_context_budget_text(context: AgentContext) -> str:
    payload = {
        "current_phase": context.current_phase,
        "completed_beats": context.completed_beats,
        "discovered_clues": context.discovered_clues,
        "player_knowledge_ids": [
            item.knowledge_id for item in context.player_knowledge
        ],
        "blocked_fact_ids": context.blocked_fact_ids,
        "revealable_fact_ids": context.revealable_fact_ids,
        "director_safe_fragment_refs": [
            fragment.ref for fragment in context.director_safe_fragments
        ],
        "selected_npc_skill_ids": [
            skill.skill_id for skill in context.npc_skill_projections
        ],
        "selected_memory_ids": [
            memory.memory_id for memory in context.memory_snapshots
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _soft_context_budget_text(context: AgentContext) -> str:
    compressed_history = context.compressed_history
    payload = {
        "recent_event_ids": [event.id for event in context.recent_events],
        "compressed_history": (
            compressed_history.model_dump(mode="json")
            if compressed_history is not None
            else None
        ),
        "memory_descriptions": [
            {
                "memory_id": memory.memory_id,
                "memory_type": memory.memory_type,
                "memory_scope": memory.memory_scope,
                "memory_layer": memory.memory_layer,
                "source_event_ids": memory.source_event_ids,
            }
            for memory in context.memory_snapshots
        ],
        "portrait_summary_present": bool(context.portrait_summary),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _skill_limited_safe_fragments(
    context: AgentContext,
    safe_fragments: tuple[SafeFactFragmentProjection, ...],
) -> tuple[SafeFactFragmentProjection, ...]:
    allowed_refs = {
        ref
        for skill in context.npc_skill_projections
        for ref in skill.safe_fragment_refs
    }
    if not allowed_refs:
        return safe_fragments
    mode_caps_by_ref = _skill_mode_caps_by_ref(context)
    return tuple(
        limited_fragment
        for fragment in safe_fragments
        if fragment.ref in allowed_refs
        for limited_fragment in [_limit_fragment_modes(fragment, mode_caps_by_ref)]
        if limited_fragment is not None
    )


def _skill_mode_caps_by_ref(context: AgentContext) -> dict[str, DisclosureMode]:
    caps: dict[str, DisclosureMode] = {}
    for skill in context.npc_skill_projections:
        for ref in skill.safe_fragment_refs:
            world_info_id = ref.split(".safe_fragment:", 1)[0]
            max_mode = skill.max_disclosure_mode_by_world_info.get(world_info_id)
            if max_mode is None:
                continue
            current = caps.get(ref)
            if current is None or _mode_index(max_mode) > _mode_index(current):
                caps[ref] = max_mode
    return caps


def _limit_fragment_modes(
    fragment: SafeFactFragmentProjection,
    mode_caps_by_ref: dict[str, DisclosureMode],
) -> SafeFactFragmentProjection | None:
    max_mode = mode_caps_by_ref.get(fragment.ref)
    if max_mode is None:
        return fragment
    allowed_modes = [
        mode for mode in fragment.allowed_modes if _mode_index(mode) <= _mode_index(max_mode)
    ]
    if not allowed_modes:
        return None
    return fragment.model_copy(update={"allowed_modes": allowed_modes})


def _mode_index(mode: DisclosureMode) -> int:
    return DISCLOSURE_MODE_ORDER.index(mode)


def _contract_error_summary(
    exc: Exception,
    *,
    error_type: LLMErrorType,
    backend: str,
) -> LLMErrorSummary:
    return LLMErrorSummary(
        backend=str(backend),
        error_type=error_type,
        error_message_sanitized=_trim_contract_error(str(exc)),
        fallback_used=True,
    )


def _trim_contract_error(message: str, *, limit: int = 180) -> str:
    normalized = " ".join(message.split())
    if not normalized:
        return "LLM output violated the turn contract"
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "...[truncated]"
