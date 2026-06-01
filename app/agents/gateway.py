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
        load_dotenv()
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


def load_dotenv(path: str = ".env") -> None:
    if os.getenv("LLM_LOAD_DOTENV", "1").strip().lower() in {"0", "false", "no", "off"}:
        return
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = _clean_env_value(value.strip())


def _clean_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
