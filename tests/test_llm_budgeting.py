from __future__ import annotations

import json
from pathlib import Path

from app.agents.gateway import AgentGateway
from app.agents.llm_contract import build_llm_agent_input
from app.agents.loop import _soft_compressed_provider_context
from app.agents.provider_payload import build_llm_provider_payload
from app.cases.loader import CaseLoader
from app.domain.models import (
    ActionType,
    AgentContext,
    AgentIntent,
    AgentIntentType,
    AgentMemorySnapshot,
    CasePackage,
    EventType,
    LLMAgentContractInput,
    LLMErrorType,
    PlayerAction,
    WorldEvent,
)
from app.runtime.budget import (
    CompressedHistory,
    ContextBudgetResult,
    TokenBudgetProfile,
    TokenEstimate,
)
from app.runtime.service import create_runtime
from app.runtime.tracing import RuntimeTracer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "cases" / "fake_case_001"


class RecordingEstimator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def estimate(
        self,
        text: str,
        *,
        profile: TokenBudgetProfile | None = None,
    ) -> TokenEstimate:
        del profile
        self.calls.append(text)
        return TokenEstimate(tokens=1, method="recording")


class ContractRecordingAgent:
    def __init__(self) -> None:
        self.contract_inputs: list[LLMAgentContractInput] = []

    def generate(
        self,
        context: AgentContext,
        *,
        contract_input: LLMAgentContractInput | None = None,
    ) -> AgentIntent:
        del context
        if contract_input is None:
            raise AssertionError("AgentLoop must pass the budgeted contract input")
        self.contract_inputs.append(contract_input)
        return AgentIntent(
            speech="I will stay within the permitted account.",
            intent=_first_allowed_intent(contract_input),
            proposed_actions=[],
        )


class ProviderPayloadOverLimitEstimator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def estimate(
        self,
        text: str,
        *,
        profile: TokenBudgetProfile | None = None,
    ) -> TokenEstimate:
        del profile
        self.calls.append(text)
        if "llm_provider_turn.v1" in text:
            return TokenEstimate(tokens=100, method="provider_payload_over_limit")
        return TokenEstimate(tokens=1, method="provider_payload_over_limit")


class SoftPayloadCompressionEstimator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def estimate(
        self,
        text: str,
        *,
        profile: TokenBudgetProfile | None = None,
    ) -> TokenEstimate:
        del profile
        self.calls.append(text)
        if "llm_provider_turn.v1" in text and "SOFT_PROFILE" in text:
            return TokenEstimate(tokens=45, method="soft_payload_compression")
        if "llm_provider_turn.v1" in text:
            return TokenEstimate(tokens=10, method="soft_payload_compression")
        return TokenEstimate(tokens=1, method="soft_payload_compression")


class FailingAgent:
    def __init__(self) -> None:
        self.generate_calls = 0

    def generate(
        self,
        context: AgentContext,
        *,
        contract_input: LLMAgentContractInput | None = None,
    ) -> AgentIntent:
        del context, contract_input
        self.generate_calls += 1
        raise AssertionError("Agent gateway must not run over-limit provider payloads")


class SoftCompressionRecordingAgent:
    def __init__(self) -> None:
        self.contract_inputs: list[LLMAgentContractInput] = []
        self.provider_payloads: list[dict[str, object]] = []

    def generate(
        self,
        context: AgentContext,
        *,
        contract_input: LLMAgentContractInput | None = None,
    ) -> AgentIntent:
        if contract_input is None:
            raise AssertionError("AgentLoop must pass the compact contract input")
        self.contract_inputs.append(contract_input)
        self.provider_payloads.append(build_llm_provider_payload(contract_input))
        assert context.compressed_history is not None
        return AgentIntent(
            speech="I can answer after compacting soft context.",
            intent=_first_allowed_intent(contract_input),
            proposed_actions=[],
        )


def test_agent_loop_budgets_serialized_provider_payload_used_by_gateway() -> None:
    case = CaseLoader().load(CASE_DIR)
    estimator = RecordingEstimator()
    agent = ContractRecordingAgent()
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=agent),
        runtime_tracer=RuntimeTracer.disabled(),
        token_estimator=estimator,
    )
    session = runtime.session_store.create(case)

    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.INSPECT,
            target_id="desk",
        ),
    )
    runtime.action_service.handle(
        session=session,
        action=PlayerAction(
            type=ActionType.TALK,
            target_id="butler",
            text="Where were you?",
        ),
    )

    assert agent.contract_inputs
    sent_provider_payload = build_llm_provider_payload(agent.contract_inputs[0])
    serialized_provider_payload = json.dumps(sent_provider_payload, ensure_ascii=False)
    assert estimator.calls[0] == serialized_provider_payload
    budget_payload = json.loads(estimator.calls[0])
    assert budget_payload == sent_provider_payload
    assert budget_payload["payload_kind"] == "llm_provider_turn.v1"
    assert budget_payload["output_limits"]["required_output_schema"] == "AgentIntent"
    assert budget_payload["turn"]["target_agent_id"] == "butler"
    assert "recent_events" not in budget_payload
    assert "context_layers" not in budget_payload
    _assert_key_absent(budget_payload, "agent_context")
    _assert_key_absent(budget_payload, "reply_options")
    _assert_key_absent(budget_payload, "payload")
    assert "NPC Agent turn context" not in estimator.calls[0]


def test_agent_loop_soft_compression_trims_low_value_provider_fields() -> None:
    case = _case_with_soft_profile_markers()
    estimator = SoftPayloadCompressionEstimator()
    agent = SoftCompressionRecordingAgent()
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=agent),
        runtime_tracer=RuntimeTracer.disabled(),
        token_estimator=estimator,
        context_limit_tokens=50,
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

    provider_budget_calls = [
        call for call in estimator.calls if "llm_provider_turn.v1" in call
    ]
    assert len(provider_budget_calls) == 2
    assert "SOFT_PROFILE" in provider_budget_calls[0]
    assert "SOFT_PROFILE" not in provider_budget_calls[1]
    assert response.llm_fallback_used is False
    assert agent.contract_inputs
    assert agent.contract_inputs[0].agent_context.compressed_history is not None
    final_payload = agent.provider_payloads[0]
    serialized_final_payload = json.dumps(final_payload, ensure_ascii=False)
    assert "SOFT_PROFILE" not in serialized_final_payload
    npc_payload = final_payload["npc"]
    assert isinstance(npc_payload, dict)
    assert npc_payload["id"] == "butler"
    assert npc_payload["public_description"] == ""
    assert npc_payload["speech_style"] == ""
    assert npc_payload["default_tone"] == ""
    assert npc_payload["catchphrases"] == []
    assert npc_payload["visible_traits"] == []
    assert npc_payload["defensive_style"] == "evasive"
    assert npc_payload["pressure_response"] == "conceal"
    assert npc_payload["trust_response"] == "cautious_help"
    assert npc_payload["fear_response"] == "panic_conceal"


def test_soft_compressed_context_trims_recent_events_and_memory_bodies() -> None:
    context = AgentContext(
        case_id="case",
        session_id="session",
        target_agent_id="npc",
        current_phase="investigation",
        player_action=PlayerAction(
            type=ActionType.TALK,
            target_id="npc",
            text="What did you see?",
        ),
        recent_events=[
            WorldEvent(
                id="event.secret",
                case_id="case",
                session_id="session",
                actor_id="system",
                type=EventType.PLAYER_TALKED,
                payload={"secret": "RECENT_EVENT_DETAIL_SHOULD_NOT_SURFACE"},
                created_at="2026-06-27T00:00:00Z",
            )
        ],
        memory_snapshots=[
            AgentMemorySnapshot(
                memory_id="memory.long",
                memory_type="episodic",
                memory_scope="npc_private",
                memory_layer="working",
                subject_id="player",
                owner_character_id="npc",
                visible_to_character_ids=["npc"],
                content=(
                    "The safe beginning stays visible. "
                    + ("middle " * 80)
                    + "TRAILING_MEMORY_DETAIL_SHOULD_NOT_SURFACE"
                ),
                source_event_ids=["event.secret"],
                source_memory_ids=["memory.source.secret"],
                salience=0.9,
                confidence=0.8,
                last_updated_event_id="event.memory.updated",
                created_at="2026-06-27T00:00:01Z",
                updated_at="2026-06-27T00:00:02Z",
            )
        ],
    )
    budget = ContextBudgetResult(
        context_tokens_estimated=100,
        context_budget_ratio=1.0,
        compression_used=True,
        compressed_history=CompressedHistory(
            summary="Compressed",
            important_event_ids=["event.secret"],
            important_memory_ids=["memory.long"],
            open_threads=[],
            risk_notes=[],
        ),
    )

    compressed = _soft_compressed_provider_context(context, budget)
    memory = compressed.memory_snapshots[0]

    assert compressed.compressed_history is not None
    assert compressed.recent_events == []
    assert compressed.memory_candidates == []
    assert len(memory.content) <= 96
    assert memory.content.endswith("...")
    assert memory.source_event_ids == []
    assert memory.source_memory_ids == []
    assert memory.created_at is None
    assert memory.updated_at is None
    assert "TRAILING_MEMORY_DETAIL_SHOULD_NOT_SURFACE" not in memory.content


def test_agent_loop_blocks_gateway_when_provider_payload_remains_over_limit() -> None:
    case = CaseLoader().load(CASE_DIR)
    estimator = ProviderPayloadOverLimitEstimator()
    agent = FailingAgent()
    runtime = create_runtime(
        [case],
        agent_gateway=AgentGateway(mock_agent=agent),
        runtime_tracer=RuntimeTracer.disabled(),
        token_estimator=estimator,
        context_limit_tokens=50,
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

    assert agent.generate_calls == 0
    assert response.llm_fallback_used is True
    assert response.llm_error is not None
    assert response.llm_error.error_type == LLMErrorType.CONTEXT_OVER_LIMIT
    assert (
        response.llm_error.error_message_sanitized
        == "provider_payload_over_limit"
    )
    assert sum("llm_provider_turn.v1" in call for call in estimator.calls) == 2


def test_budget_prompt_prefers_external_serialized_provider_payload() -> None:
    case = CaseLoader().load(CASE_DIR)
    estimator = RecordingEstimator()
    runtime = create_runtime(
        [case],
        runtime_tracer=RuntimeTracer.disabled(),
        token_estimator=estimator,
    )
    session = runtime.session_store.create(case)
    action = PlayerAction(
        type=ActionType.TALK,
        target_id="butler",
        text="Where were you?",
    )
    context = runtime.agent_loop.build_context(
        case=case,
        session=session,
        action=action,
    )
    turn_plan = runtime.agent_loop.plan_turn(
        case=case,
        session=session,
        action=action,
        context=context,
    )
    contract_input = build_llm_agent_input(context, turn_plan=turn_plan)

    budget = runtime.agent_loop._budget_prompt(
        None,
        context,
        [],
        contract_input=contract_input,
        serialized_provider_payload='{"compact": true}',
    )

    assert estimator.calls[0] == '{"compact": true}'
    assert budget.budgeted_input_bytes == len(b'{"compact": true}')


def _first_allowed_intent(contract_input: LLMAgentContractInput) -> AgentIntentType:
    allowed = contract_input.output_contract.allowed_intents
    return allowed[0] if allowed else AgentIntentType.REFUSE


def _case_with_soft_profile_markers() -> CasePackage:
    case = CaseLoader().load(CASE_DIR)
    characters = []
    for character in case.characters:
        if character.id != "butler":
            characters.append(character)
            continue
        characters.append(
            character.model_copy(
                update={
                    "public_description": "SOFT_PROFILE_PUBLIC_DESCRIPTION",
                    "speech": character.speech.model_copy(
                        update={
                            "style": "SOFT_PROFILE_SPEECH_STYLE",
                            "default_tone": "SOFT_PROFILE_DEFAULT_TONE",
                            "catchphrases": ["SOFT_PROFILE_CATCHPHRASE"],
                        }
                    ),
                    "personality": character.personality.model_copy(
                        update={"traits": ["SOFT_PROFILE_VISIBLE_TRAIT"]}
                    ),
                }
            )
        )
    return case.model_copy(update={"characters": characters})


def _assert_key_absent(value: object, forbidden_key: str) -> None:
    if isinstance(value, dict):
        assert forbidden_key not in value
        for item in value.values():
            _assert_key_absent(item, forbidden_key)
    elif isinstance(value, list):
        for item in value:
            _assert_key_absent(item, forbidden_key)
