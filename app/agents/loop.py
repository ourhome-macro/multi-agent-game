from __future__ import annotations

from dataclasses import dataclass

from app.agents.context import build_agent_context
from app.agents.gateway import AgentGateway
from app.agents.llm_contract import validate_llm_agent_output
from app.agents.memory import MemoryRetriever
from app.agents.prompt_builder import PromptBuilder
from app.agents.tools.runtime import ToolRuntime
from app.domain.models import (
    AgentContext,
    AgentIntent,
    AgentMemorySnapshot,
    CasePackage,
    PlayerAction,
    PromptBundle,
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
        context_budget_manager: ContextBudgetManager | None = None,
        tool_runtime: ToolRuntime | None = None,
    ) -> None:
        self._agent_gateway = agent_gateway
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._injection_guard = injection_guard or PromptInjectionGuard()
        self._runtime_tracer = runtime_tracer or RuntimeTracer.disabled()
        self._memory_retriever = memory_retriever or MemoryRetriever()
        self._context_budget_manager = (
            context_budget_manager or ContextBudgetManager()
        )
        self._tool_runtime = tool_runtime or ToolRuntime(
            memory_retriever=self._memory_retriever
        )

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
        return build_agent_context(case, session, action)

    def run_turn(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> AgentTurnResult:
        phase_before = session.narrative.phase
        context = self.build_context(case=case, session=session, action=action)
        security_review = self._injection_guard.review(action)
        retrieved_memories = self._memory_retriever.retrieve(
            case=case,
            session=session,
            action=action,
        )
        context = context.model_copy(
            update={
                "memory_snapshots": retrieved_memories,
            }
        )
        memory_ids = [snapshot.memory_id for snapshot in retrieved_memories]
        memory_projection = _memory_projection(retrieved_memories)
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
            tool_calls=tool_calls,
            security_flags=security_review.security_flags,
        )
        intent = self._agent_gateway.generate(context)
        intent = validate_llm_agent_output(intent.model_dump(mode="json"))
        return AgentTurnResult(
            context=context,
            intent=intent,
            trace=trace,
            security_flags=security_review.security_flags,
            memory_ids_used=memory_ids,
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


def _memory_projection(memories: list[AgentMemorySnapshot]) -> list[dict[str, object]]:
    return [
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
