from __future__ import annotations

from app.domain.models import AgentContext, AgentIntent, AgentIntentType


class LLMAgentStub:
    def generate(self, context: AgentContext) -> AgentIntent:
        return AgentIntent(
            speech=f"{context.target_agent_id} is not connected to an external model yet.",
            intent=AgentIntentType.REFUSE,
            emotional_shift={},
            proposed_actions=[],
            memory_refs=[],
        )
