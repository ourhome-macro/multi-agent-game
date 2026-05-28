from __future__ import annotations

import os
from typing import Literal

from app.agents.llm_stub import LLMAgentStub
from app.agents.mock_agent import MockAgent
from app.agents.protocol import AgentProtocol
from app.agents.real_llm_agent import OpenAILLMAgent
from app.domain.models import AgentContext, AgentIntent

AgentBackend = Literal["mock", "llm_stub", "real"]


class AgentGateway:
    def __init__(
        self,
        *,
        backend: AgentBackend = "mock",
        mock_agent: AgentProtocol | None = None,
        llm_stub: AgentProtocol | None = None,
        real_agent: AgentProtocol | None = None,
    ) -> None:
        self._backend = backend
        self._agents: dict[AgentBackend, AgentProtocol] = {
            "mock": mock_agent or MockAgent(),
            "llm_stub": llm_stub or LLMAgentStub(),
            "real": real_agent or OpenAILLMAgent(),
        }

    @classmethod
    def from_env(cls) -> AgentGateway:
        backend = os.getenv("LLM_BACKEND", "mock").strip().lower()
        if backend == "llm_stub":
            return cls(backend="llm_stub")
        if backend == "real" and os.getenv("OPENAI_API_KEY"):
            return cls(backend="real")
        return cls()

    @property
    def backend_name(self) -> AgentBackend:
        return self._backend

    def generate(self, context: AgentContext) -> AgentIntent:
        return self._agents[self._backend].generate(context)
