from __future__ import annotations

from typing import Protocol

from app.domain.models import AgentContext, AgentIntent, LLMAgentContractInput


class AgentProtocol(Protocol):
    def generate(
        self,
        context: AgentContext,
        *,
        contract_input: LLMAgentContractInput | None = None,
    ) -> AgentIntent:
        """Generate a structured intent from an immutable runtime context."""
        ...
