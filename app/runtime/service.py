from __future__ import annotations

from dataclasses import dataclass

from app.agents.mock_agent import MockAgent
from app.director.narrative_director import NarrativeDirector
from app.domain.models import (
    ActionResponse,
    ActionType,
    CasePackage,
    EventType,
    PlayerAction,
    SessionState,
    WorldEvent,
)
from app.rules.engine import RuleEngine
from app.runtime.events import EventRecorder
from app.storage.memory import InMemoryCaseStore, InMemorySessionStore, build_state_summary


@dataclass(frozen=True)
class RuntimeContainer:
    case_store: InMemoryCaseStore
    session_store: InMemorySessionStore
    action_service: ActionService


class ActionService:
    def __init__(
        self,
        *,
        case_store: InMemoryCaseStore,
        recorder: EventRecorder,
        mock_agent: MockAgent,
        director: NarrativeDirector,
        rule_engine: RuleEngine,
    ) -> None:
        self._case_store = case_store
        self._recorder = recorder
        self._mock_agent = mock_agent
        self._director = director
        self._rule_engine = rule_engine

    def handle(self, *, session: SessionState, action: PlayerAction) -> ActionResponse:
        case = self._case_store.get(session.case_id)
        new_events: list[WorldEvent] = []

        if action.type == ActionType.INSPECT:
            player_event = self._recorder.append(
                session,
                actor_id="player",
                event_type=EventType.PLAYER_INSPECTED,
                payload={"target_id": action.target_id},
            )
            new_events.append(player_event)
            new_events.extend(
                self._rule_engine.apply_inspect(
                    case=case,
                    session=session,
                    action=action,
                    caused_by_event_id=player_event.id,
                )
            )
            return ActionResponse(
                session_id=session.id,
                accepted=True,
                new_events=new_events,
                state=build_state_summary(case, session),
            )

        if action.type == ActionType.TALK:
            player_event = self._recorder.append(
                session,
                actor_id="player",
                event_type=EventType.PLAYER_TALKED,
                payload={"target_id": action.target_id, "text": action.text},
            )
            new_events.append(player_event)
            intent = self._mock_agent.generate(case, action)
            decision = self._director.validate(case, session.narrative, intent)

            speech = intent.speech
            director_blocked = not decision.allowed
            director_reason = decision.reason

            if decision.allowed:
                npc_event = self._recorder.append(
                    session,
                    actor_id=action.target_id,
                    event_type=EventType.NPC_REPLIED,
                    payload={
                        "speech": intent.speech,
                        "intent": intent.intent,
                        "proposed_actions": [
                            item.model_dump(mode="json") for item in intent.proposed_actions
                        ],
                    },
                    caused_by_event_id=player_event.id,
                )
                new_events.append(npc_event)
                new_events.extend(
                    self._rule_engine.apply_agent_intent(
                        case=case,
                        session=session,
                        intent=intent,
                        caused_by_event_id=npc_event.id,
                    )
                )
            else:
                speech = decision.safe_speech
                blocked_event = self._recorder.append(
                    session,
                    actor_id="director",
                    event_type=EventType.DIRECTOR_BLOCKED,
                    payload={
                        "target_id": action.target_id,
                        "blocked_fact_id": decision.blocked_fact_id,
                        "reason": decision.reason,
                    },
                    caused_by_event_id=player_event.id,
                )
                new_events.append(blocked_event)

            return ActionResponse(
                session_id=session.id,
                accepted=decision.allowed,
                speech=speech,
                director_blocked=director_blocked,
                director_reason=director_reason,
                new_events=new_events,
                state=build_state_summary(case, session),
            )

        raise ValueError(f"Unsupported action type: {action.type}")


def create_runtime(case_packages: list[CasePackage]) -> RuntimeContainer:
    recorder = EventRecorder()
    case_store = InMemoryCaseStore()
    for package in case_packages:
        case_store.add(package)
    session_store = InMemorySessionStore(recorder)
    action_service = ActionService(
        case_store=case_store,
        recorder=recorder,
        mock_agent=MockAgent(),
        director=NarrativeDirector(),
        rule_engine=RuleEngine(recorder),
    )
    return RuntimeContainer(
        case_store=case_store,
        session_store=session_store,
        action_service=action_service,
    )
