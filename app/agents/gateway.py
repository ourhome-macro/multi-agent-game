from __future__ import annotations

from typing import Literal

from app.agents.llm_stub import LLMAgentStub
from app.agents.mock_agent import MockAgent
from app.agents.protocol import AgentProtocol
from app.domain.models import AgentContext, AgentIntent

AgentBackend = Literal["mock", "llm_stub"]


class AgentGateway:
    def __init__(
        self,
        *,
        backend: AgentBackend = "mock",
        mock_agent: AgentProtocol | None = None,
        llm_stub: AgentProtocol | None = None,
    ) -> None:
        self._backend = backend
        self._agents: dict[AgentBackend, AgentProtocol] = {
            "mock": mock_agent or MockAgent(),
            "llm_stub": llm_stub or LLMAgentStub(),
        }

    def generate(self, context: AgentContext) -> AgentIntent:
        return self._agents[self._backend].generate(context)
