from __future__ import annotations

from dataclasses import dataclass

from app.agents.context import build_agent_context
from app.agents.gateway import AgentGateway
from app.agents.llm_contract import validate_llm_agent_output
from app.agents.prompt_builder import PromptBuilder
from app.domain.models import AgentContext, AgentIntent, CasePackage, PlayerAction, SessionState
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
    ) -> None:
        self._agent_gateway = agent_gateway
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._injection_guard = injection_guard or PromptInjectionGuard()
        self._runtime_tracer = runtime_tracer or RuntimeTracer.disabled()

    @property
    def backend_name(self) -> str:
        return self._agent_gateway.backend_name

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
        prompt_bundle = self._prompt_builder.build(context)
        context_tokens = _estimate_tokens(
            prompt_bundle.agent_prompt
            + prompt_bundle.contract_instruction
            + prompt_bundle.safety_instruction
        )
        memory_ids = [snapshot.memory_id for snapshot in context.memory_snapshots]
        trace = self._runtime_tracer.start_turn(
            case_id=case.meta.id,
            session_id=session.id,
            action=action,
            target_agent_id=action.target_id,
            agent_backend=self._agent_gateway.backend_name,
            phase_before=phase_before,
            context_tokens_estimated=context_tokens,
            context_budget_ratio=0.0,
            compression_used=False,
            memory_ids_used=memory_ids,
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

    def finish_trace(
        self,
        turn: AgentTurnResult,
        *,
        director_allowed: bool,
        director_reason_category: str | None,
        rule_rejections: list[str],
        new_events: list[object],
        phase_after: str,
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
            status=status,
            error_category=error_category,
        )


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
