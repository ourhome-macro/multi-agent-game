from __future__ import annotations

from app.agents.llm_contract import build_llm_agent_input, validate_llm_agent_output
from app.domain.models import (
    AgentContext,
    AgentIntent,
    AgentIntentType,
    LLMAgentContractInput,
)


class LLMAgentStub:
    def generate(
        self,
        context: AgentContext,
        *,
        contract_input: LLMAgentContractInput | None = None,
    ) -> AgentIntent:
        contract_input = contract_input or build_llm_agent_input(context)
        return validate_llm_agent_output(
            {
                "speech": (
                    f"{contract_input.agent_context.target_agent_id} is not connected "
                    "to an external model yet."
                ),
                "intent": _stub_intent(contract_input),
                "emotional_shift": {},
                "proposed_actions": [],
                "memory_refs": [],
                "disclosure_claims": [],
            },
            contract_input,
        )


def _stub_intent(contract_input: LLMAgentContractInput) -> AgentIntentType:
    allowed = contract_input.output_contract.allowed_intents
    fallback = contract_input.output_contract.fallback_intent
    if fallback in allowed:
        return fallback
    if AgentIntentType.CONCEAL in allowed:
        return AgentIntentType.CONCEAL
    return allowed[0] if allowed else fallback
