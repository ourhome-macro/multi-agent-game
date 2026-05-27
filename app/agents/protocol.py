from __future__ import annotations

from typing import Protocol

from app.domain.models import AgentContext, AgentIntent


class AgentProtocol(Protocol):
    def generate(self, context: AgentContext) -> AgentIntent:
        """Generate a structured intent from an immutable runtime context."""
        ...
