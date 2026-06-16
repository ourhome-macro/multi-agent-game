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
                "intent": AgentIntentType.REFUSE,
                "emotional_shift": {},
                "proposed_actions": [],
                "memory_refs": [],
                "disclosure_claims": [],
            }
        )
