from __future__ import annotations

from dataclasses import dataclass

from app.agents.gateway import AgentGateway
from app.agents.loop import AgentLoop, AgentTurnResult
from app.domain.models import CasePackage, PlayerAction, SessionState
from app.runtime.tracing import RuntimeTracer


@dataclass(frozen=True)
class OrchestratorResult:
    secondary_turns: list[AgentTurnResult]


class AgentOrchestrator:
    def __init__(
        self,
        *,
        primary_loop: AgentLoop,
        secondary_gateway: AgentGateway,
        max_secondary_agents: int = 2,
    ) -> None:
        self._primary_loop = primary_loop
        self._secondary_gateway = secondary_gateway
        self._max_secondary_agents = max_secondary_agents

    def run_secondary_reactions(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> OrchestratorResult:
        _ = self._primary_loop
        secondary_turns: list[AgentTurnResult] = []
        for character in case.characters:
            if character.id == action.target_id:
                continue
            if len(secondary_turns) >= self._max_secondary_agents:
                break
            secondary_action = action.model_copy(update={"target_id": character.id})
            secondary_loop = AgentLoop(
                agent_gateway=self._secondary_gateway,
                runtime_tracer=RuntimeTracer.disabled(),
            )
            secondary_turns.append(
                secondary_loop.run_turn(
                    case=case,
                    session=session,
                    action=secondary_action,
                )
            )
        return OrchestratorResult(secondary_turns=secondary_turns)
