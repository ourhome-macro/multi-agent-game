from __future__ import annotations

from dataclasses import dataclass

from app.agents.context import build_agent_context
from app.agents.disclosure_strategy import DISCLOSURE_MODE_ORDER
from app.agents.gateway import AgentGateway
from app.agents.llm_contract import build_llm_agent_input, validate_llm_agent_output
from app.agents.memory import MemoryRetriever
from app.agents.prompt_builder import PromptBuilder
from app.agents.retrieval_planner import MemoryRetrievalPlan, RetrievalPlanner
from app.agents.tools.runtime import ToolRuntime
from app.director.narrative_director import NarrativeDirector
from app.domain.models import (
    AgentContext,
    AgentIntent,
    AgentMemorySnapshot,
    CasePackage,
    DisclosureMode,
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
        plan = self._retrieval_planner.plan(case=case, session=session, action=action)
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
        )
        return self._attach_director_generation_constraints(
            case=case,
            session=session,
            context=context,
        )

    def run_turn(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> AgentTurnResult:
        phase_before = session.narrative.phase
        plan = self._retrieval_planner.plan(case=case, session=session, action=action)
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
        )
        context = self._attach_director_generation_constraints(
            case=case,
            session=session,
            context=context,
        )
        security_review = self._injection_guard.review(action)
        memory_ids = [snapshot.memory_id for snapshot in retrieved_memories]
        memory_projection = _memory_projection(plan, retrieved_memories, context)
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
            tool_calls=tool_calls,
            security_flags=security_review.security_flags,
        )
        intent = self._validate_agent_intent(context, self._agent_gateway.generate(context))
        return AgentTurnResult(
            context=context,
            intent=intent,
            trace=trace,
            security_flags=security_review.security_flags,
            memory_ids_used=memory_ids,
        )

    def _validate_agent_intent(
        self,
        context: AgentContext,
        intent: AgentIntent,
    ) -> AgentIntent:
        contract_input = build_llm_agent_input(context)
        payload = intent.model_dump(
            mode="json",
            exclude={"llm_error"},
        )
        validated = validate_llm_agent_output(payload, contract_input)
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
    return summary


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
