from __future__ import annotations

from pathlib import Path

from app.agents.gateway import AgentGateway
from app.agents.real_llm_agent import OpenAILLMAgent
from app.cases.loader import CaseLoader
from app.domain.models import (
    ActionType,
    AgentContext,
    AgentIntent,
    AgentIntentType,
    LLMErrorSummary,
    LLMErrorType,
    PlayerAction,
)
from app.runtime.service import create_runtime
from app.runtime.tracing import RuntimeTracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


class FallbackAgent:
    @property
    def model_name(self) -> str:
        return "fallback-model"

    def generate(self, context: AgentContext) -> AgentIntent:
        return AgentIntent(
            speech=f"{context.target_agent_id} cannot answer through the LLM backend.",
            intent=AgentIntentType.REFUSE,
            proposed_actions=[],
            llm_error=LLMErrorSummary(
                backend="openai",
                error_type=LLMErrorType.TIMEOUT,
                error_message_sanitized="LLM provider request timed out",
                fallback_used=True,
            ),
        )


def test_action_response_exposes_real_llm_fallback_summary() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=FallbackAgent()),
        runtime_tracer=RuntimeTracer.disabled(),
    )
    session = runtime.session_store.create(case)

    response = runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id="butler",
            text="Where were you?",
        ),
    )

    assert response.llm_fallback_used is True
    assert response.llm_error is not None
    assert response.llm_error.error_type == LLMErrorType.TIMEOUT
    assert response.llm_error.error_message_sanitized == "LLM provider request timed out"


def test_runtime_trace_records_sanitized_llm_fallback_fields() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=FallbackAgent()),
        runtime_tracer=RuntimeTracer.disabled(),
    )
    session = runtime.session_store.create(case)

    turn = runtime.action_service.agent_loop.run_turn(
        case=case,
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id="butler",
            text="Where were you?",
        ),
    )
    record = turn.trace
    rendered = RuntimeTracer.disabled().finish_turn(
        record,
        intent=turn.intent,
        director_allowed=True,
        director_reason_category=None,
        rule_rejections=[],
        new_events=[],
        phase_after=session.narrative.phase,
        public_speech=turn.intent.speech,
        public_speech_source="npc",
    )

    assert rendered["llm_fallback_used"] is True
    assert rendered["llm_error_type"] == "timeout"
    assert rendered["llm_error_message_sanitized"] == "LLM provider request timed out"
    assert rendered["schema_validation_errors"] == []


def test_openai_agent_missing_api_key_is_observable_configuration_error() -> None:
    case = CaseLoader().load(CASE_DIR)
    runtime = create_runtime([case], runtime_tracer=RuntimeTracer.disabled())
    session = runtime.session_store.create(case)
    context = runtime.action_service.agent_loop.build_context(
        case=case,
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id="butler",
            text="Where were you?",
        ),
    )

    intent = OpenAILLMAgent(api_key="").generate(context)

    assert intent.proposed_actions == []
    assert intent.llm_error is not None
    assert intent.llm_error.error_type == LLMErrorType.CONFIGURATION_ERROR
    assert intent.llm_error.fallback_used is True
