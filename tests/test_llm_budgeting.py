from __future__ import annotations

import json
from pathlib import Path

from app.agents.gateway import AgentGateway
from app.agents.llm_contract import build_llm_agent_input
from app.agents.provider_payload import build_llm_provider_payload
from app.cases.loader import CaseLoader
from app.domain.models import (
    ActionType,
    AgentContext,
    AgentIntent,
    AgentIntentType,
    LLMAgentContractInput,
    PlayerAction,
)
from app.runtime.budget import TokenBudgetProfile, TokenEstimate
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
            type=ActionType.TALK,
            target_id="butler",
            text="Where were you?",
        ),
    )

    assert agent.contract_inputs
    budget_payload = json.loads(estimator.calls[0])
    sent_provider_payload = build_llm_provider_payload(agent.contract_inputs[0])
    assert budget_payload == sent_provider_payload
    assert budget_payload["payload_kind"] == "llm_provider_turn.v1"
    assert budget_payload["output_limits"]["required_output_schema"] == "AgentIntent"
    assert budget_payload["turn"]["target_agent_id"] == "butler"
    assert "agent_context" not in budget_payload
    assert "reply_options" not in estimator.calls[0]
    assert "NPC Agent turn context" not in estimator.calls[0]


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

    runtime.agent_loop._budget_prompt(
        None,
        context,
        [],
        contract_input=contract_input,
        serialized_provider_payload='{"compact": true}',
    )

    assert estimator.calls[0] == '{"compact": true}'


def _first_allowed_intent(contract_input: LLMAgentContractInput) -> AgentIntentType:
    allowed = contract_input.output_contract.allowed_intents
    return allowed[0] if allowed else AgentIntentType.REFUSE
