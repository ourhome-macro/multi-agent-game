from __future__ import annotations

from dataclasses import dataclass

from app.agents.context import build_agent_context
from app.agents.gateway import AgentGateway
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
from app.rules.triggers import RuleTriggerSystem
from app.runtime.derivations import DerivedEventSystem
from app.runtime.errors import ActionValidationError
from app.runtime.events import EventRecorder
from app.runtime.memory_snapshots import MemorySnapshotSystem
from app.storage.memory import InMemoryCaseStore, InMemorySessionStore, build_state_summary


@dataclass(frozen=True)
class RuntimeContainer:
    case_store: InMemoryCaseStore
    session_store: InMemorySessionStore
    action_service: ActionService
    rule_engine: RuleEngine


class ActionService:
    def __init__(
        self,
        *,
        case_store: InMemoryCaseStore,
        recorder: EventRecorder,
        agent_gateway: AgentGateway,
        director: NarrativeDirector,
        rule_engine: RuleEngine,
        trigger_system: RuleTriggerSystem,
        derived_event_system: DerivedEventSystem,
        memory_snapshot_system: MemorySnapshotSystem,
    ) -> None:
        self._case_store = case_store
        self._recorder = recorder
        self._agent_gateway = agent_gateway
        self._director = director
        self._rule_engine = rule_engine
        self._trigger_system = trigger_system
        self._derived_event_system = derived_event_system
        self._memory_snapshot_system = memory_snapshot_system

    def handle(self, *, session: SessionState, action: PlayerAction) -> ActionResponse:
        case = self._case_store.get(session.case_id)
        new_events: list[WorldEvent] = []

        if action.type == ActionType.INSPECT:
            self._require_hotspot(case, action.target_id)
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
            trigger_source_event_id = new_events[-1].id
            new_events.extend(self._derive_events(case, session, new_events))
            new_events.extend(self._evaluate_triggers(case, session, trigger_source_event_id))
            return ActionResponse(
                session_id=session.id,
                accepted=True,
                new_events=new_events,
                state=build_state_summary(case, session),
            )

        if action.type == ActionType.TALK:
            self._require_character(case, action.target_id)
            player_event = self._recorder.append(
                session,
                actor_id="player",
                event_type=EventType.PLAYER_TALKED,
                payload={"target_id": action.target_id, "text": action.text},
            )
            new_events.append(player_event)
            return self._complete_agent_backed_action(
                case=case,
                session=session,
                action=action,
                player_event=player_event,
                new_events=new_events,
            )

        if action.type == ActionType.ASK_ABOUT:
            new_events.extend(
                self._rule_engine.apply_ask_about(
                    case=case,
                    session=session,
                    action=action,
                )
            )
            if not new_events or new_events[-1].type == EventType.RULE_REJECTED:
                return ActionResponse(
                    session_id=session.id,
                    accepted=False,
                    new_events=new_events,
                    state=build_state_summary(case, session),
                )

            return self._complete_agent_backed_action(
                case=case,
                session=session,
                action=action,
                player_event=new_events[-1],
                new_events=new_events,
            )

        if action.type == ActionType.PRESENT_CLUE:
            new_events.extend(
                self._rule_engine.apply_present_clue(
                    case=case,
                    session=session,
                    action=action,
                )
            )
            if not new_events or new_events[-1].type == EventType.RULE_REJECTED:
                return ActionResponse(
                    session_id=session.id,
                    accepted=False,
                    new_events=new_events,
                    state=build_state_summary(case, session),
                )

            return self._complete_agent_backed_action(
                case=case,
                session=session,
                action=action,
                player_event=new_events[-1],
                new_events=new_events,
            )

        if action.type == ActionType.ACCUSE:
            new_events.extend(
                self._rule_engine.apply_accuse(
                    case=case,
                    session=session,
                    action=action,
                )
            )
            if not new_events or new_events[-1].type == EventType.RULE_REJECTED:
                return ActionResponse(
                    session_id=session.id,
                    accepted=False,
                    new_events=new_events,
                    state=build_state_summary(case, session),
                )

            trigger_source_event_id = new_events[-1].id
            new_events.extend(self._derive_events(case, session, new_events))
            new_events.extend(self._evaluate_triggers(case, session, trigger_source_event_id))
            return ActionResponse(
                session_id=session.id,
                accepted=True,
                new_events=new_events,
                state=build_state_summary(case, session),
            )

        raise ValueError(f"Unsupported action type: {action.type}")

    def _require_hotspot(self, case: CasePackage, target_id: str) -> None:
        for scene in case.scenes:
            for hotspot in scene.hotspots:
                if hotspot.id == target_id:
                    return
        raise ActionValidationError(f"Unknown inspect target_id: {target_id}")

    def _require_character(self, case: CasePackage, target_id: str) -> None:
        for character in case.characters:
            if character.id == target_id:
                return
        raise ActionValidationError(f"Unknown talk target_id: {target_id}")

    def _complete_agent_backed_action(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
        player_event: WorldEvent,
        new_events: list[WorldEvent],
    ) -> ActionResponse:
        context = build_agent_context(case, session, action)
        intent = self._agent_gateway.generate(context)
        decision = self._director.validate(case, session.narrative, intent, context)

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
                    "disclosure_claims": [
                        item.model_dump(mode="json") for item in intent.disclosure_claims
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
                    "world_info_id": decision.world_info_id,
                    "claimed_mode": decision.claimed_mode,
                    "detected_directness": decision.detected_directness,
                    "matched_by": decision.matched_by,
                    "matched_text": _redact_matched_text(decision.matched_text),
                    "pattern_id": decision.pattern_id,
                    "safe_fallback_used": decision.safe_fallback_used,
                    "disclosure_claims": [
                        item.model_dump(mode="json") for item in intent.disclosure_claims
                    ],
                },
                caused_by_event_id=player_event.id,
            )
            new_events.append(blocked_event)

        trigger_source_event_id = new_events[-1].id
        new_events.extend(self._derive_events(case, session, new_events))
        new_events.extend(self._evaluate_triggers(case, session, trigger_source_event_id))

        return ActionResponse(
            session_id=session.id,
            accepted=decision.allowed,
            speech=speech,
            director_blocked=director_blocked,
            director_reason=director_reason,
            new_events=new_events,
            state=build_state_summary(case, session),
        )

    def _evaluate_triggers(
        self,
        case: CasePackage,
        session: SessionState,
        caused_by_event_id: str,
    ) -> list[WorldEvent]:
        return self._trigger_system.evaluate(
            case=case,
            session=session,
            caused_by_event_id=caused_by_event_id,
        )

    def _derive_events(
        self,
        case: CasePackage,
        session: SessionState,
        source_events: list[WorldEvent],
    ) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        for source_event in source_events:
            derived_events = self._derived_event_system.derive(
                case=case,
                session=session,
                source_events=[source_event],
            )
            for event in derived_events:
                events.append(event)
                events.extend(self._memory_snapshot_system.apply(session=session, event=event))
        return events


def create_runtime(case_packages: list[CasePackage]) -> RuntimeContainer:
    recorder = EventRecorder()
    case_store = InMemoryCaseStore()
    for package in case_packages:
        case_store.add(package)
    session_store = InMemorySessionStore(recorder)
    rule_engine = RuleEngine(recorder)
    action_service = ActionService(
        case_store=case_store,
        recorder=recorder,
        agent_gateway=AgentGateway.from_env(),
        director=NarrativeDirector(),
        rule_engine=rule_engine,
        trigger_system=RuleTriggerSystem(recorder),
        derived_event_system=DerivedEventSystem(recorder),
        memory_snapshot_system=MemorySnapshotSystem(recorder),
    )
    return RuntimeContainer(
        case_store=case_store,
        session_store=session_store,
        action_service=action_service,
        rule_engine=rule_engine,
    )


def _redact_matched_text(matched_text: str | None) -> str | None:
    if matched_text is None:
        return None
    return "[redacted]"
