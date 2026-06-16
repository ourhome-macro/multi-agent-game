from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from app.agents.gateway import AgentGateway
from app.agents.loop import AgentLoop, AgentTurnResult
from app.agents.retrieval_planner import RetrievalPlanner
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
from app.runtime.action_router import ActionRouter, ActionRouteStatus, RouteResult
from app.runtime.budget import ContextBudgetManager
from app.runtime.derivations import DerivedEventSystem
from app.runtime.errors import ActionValidationError
from app.runtime.events import EventRecorder
from app.runtime.memory_archival import MemoryArchivalSystem
from app.runtime.memory_snapshots import MemorySnapshotSystem
from app.runtime.tracing import RuntimeTracer
from app.storage.memory import InMemoryCaseStore, InMemorySessionStore, build_state_summary


class ActionIntakeStatus(StrEnum):
    ACCEPTED = "accepted"
    NEEDS_CLARIFICATION = "needs_clarification"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ActionIntakeResult:
    status: ActionIntakeStatus
    route: RouteResult
    action: PlayerAction | None = None
    response: ActionResponse | None = None
    reason: str | None = None
    missing_slots: list[str] = field(default_factory=list)

    @property
    def needs_clarification(self) -> bool:
        return self.status == ActionIntakeStatus.NEEDS_CLARIFICATION

    @property
    def rejected(self) -> bool:
        return self.status == ActionIntakeStatus.REJECTED


class RuntimeSessionBackend(Protocol):
    def create_session(self, case: CasePackage) -> SessionState:
        ...

    def get_session(self, session_id: str) -> SessionState:
        ...

    def handle_action(
        self,
        *,
        session_id: str,
        action: PlayerAction,
        idempotency_key: str | None = None,
    ) -> ActionResponse:
        ...

    def handle_raw_text(
        self,
        *,
        session_id: str,
        raw_text: str,
        idempotency_key: str | None = None,
    ) -> ActionIntakeResult:
        ...

    def get_events(self, session_id: str) -> list[WorldEvent]:
        ...

    def close(self) -> None:
        ...


@dataclass(frozen=True)
class RuntimeContainer:
    case_store: InMemoryCaseStore
    session_store: InMemorySessionStore
    action_service: ActionService
    rule_engine: RuleEngine
    agent_loop: AgentLoop
    session_backend: RuntimeSessionBackend | None = None

    def create_session(self, case: CasePackage) -> SessionState:
        if self.session_backend is not None:
            return self.session_backend.create_session(case)
        return self.session_store.create(case)

    def get_session(self, session_id: str) -> SessionState:
        if self.session_backend is not None:
            return self.session_backend.get_session(session_id)
        return self.session_store.get(session_id)

    def handle_action(
        self,
        *,
        session_id: str,
        action: PlayerAction,
        idempotency_key: str | None = None,
    ) -> ActionResponse:
        if self.session_backend is not None:
            return self.session_backend.handle_action(
                session_id=session_id,
                action=action,
                idempotency_key=idempotency_key,
            )
        session = self.session_store.get(session_id)
        return self.action_service.handle(session=session, action=action)

    def handle_raw_text(
        self,
        *,
        session_id: str,
        raw_text: str,
        idempotency_key: str | None = None,
    ) -> ActionIntakeResult:
        if self.session_backend is not None:
            return self.session_backend.handle_raw_text(
                session_id=session_id,
                raw_text=raw_text,
                idempotency_key=idempotency_key,
            )
        session = self.session_store.get(session_id)
        return self.action_service.handle_raw_text(session=session, raw_text=raw_text)

    def get_events(self, session_id: str) -> list[WorldEvent]:
        if self.session_backend is not None:
            return self.session_backend.get_events(session_id)
        return self.session_store.get(session_id).events

    def close(self) -> None:
        if self.session_backend is not None:
            self.session_backend.close()


class ActionService:
    def __init__(
        self,
        *,
        case_store: InMemoryCaseStore,
        recorder: EventRecorder,
        agent_loop: AgentLoop,
        director: NarrativeDirector,
        rule_engine: RuleEngine,
        trigger_system: RuleTriggerSystem,
        derived_event_system: DerivedEventSystem,
        memory_snapshot_system: MemorySnapshotSystem,
        memory_archival_system: MemoryArchivalSystem,
    ) -> None:
        self._case_store = case_store
        self._recorder = recorder
        self._agent_loop = agent_loop
        self._director = director
        self._rule_engine = rule_engine
        self._trigger_system = trigger_system
        self._derived_event_system = derived_event_system
        self._memory_snapshot_system = memory_snapshot_system
        self._memory_archival_system = memory_archival_system

    @property
    def agent_loop(self) -> AgentLoop:
        return self._agent_loop

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
            new_events.extend(
                self._archive_stale_memories(
                    session=session,
                    caused_by_event_id=trigger_source_event_id,
                )
            )
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
            new_events.extend(
                self._archive_stale_memories(
                    session=session,
                    caused_by_event_id=trigger_source_event_id,
                )
            )
            turn = self._agent_loop.run_turn(case=case, session=session, action=action)
            new_events.extend(self._derive_events(case, session, new_events))
            new_events.extend(self._evaluate_triggers(case, session, trigger_source_event_id))
            self._agent_loop.finish_trace(
                turn,
                director_allowed=True,
                director_reason_category=None,
                rule_rejections=[],
                new_events=new_events,
                phase_after=session.narrative.phase,
                public_speech=None,
                public_speech_source=None,
            )
            return ActionResponse(
                session_id=session.id,
                accepted=True,
                new_events=new_events,
                state=build_state_summary(case, session),
                llm_fallback_used=_llm_fallback_used(turn.intent),
                llm_error=turn.intent.llm_error,
            )

        raise ValueError(f"Unsupported action type: {action.type}")

    def handle_raw_text(
        self,
        *,
        session: SessionState,
        raw_text: str,
    ) -> ActionIntakeResult:
        case = self._case_store.get(session.case_id)
        routed = ActionRouter(case).route(raw_text)

        if routed.status == ActionRouteStatus.NEEDS_CLARIFICATION:
            return ActionIntakeResult(
                status=ActionIntakeStatus.NEEDS_CLARIFICATION,
                route=routed,
                reason=routed.reason,
                missing_slots=list(routed.missing_slots),
            )

        if routed.action is None:
            return ActionIntakeResult(
                status=ActionIntakeStatus.REJECTED,
                route=routed,
                reason=routed.reason or "unresolved_player_action",
            )

        director_decision = self._director.precheck_player_action(case, session, routed.action)
        routed = routed.with_director_precheck(
            _precheck_summary(director_decision.allowed, director_decision.reason)
        )
        rejection_event = self._rule_engine.precheck_player_action(
            case=case,
            session=session,
            action=routed.action,
        )
        if rejection_event is not None:
            response = ActionResponse(
                session_id=session.id,
                accepted=False,
                new_events=[rejection_event],
                state=build_state_summary(case, session),
            )
            return ActionIntakeResult(
                status=ActionIntakeStatus.REJECTED,
                route=routed,
                action=routed.action,
                response=response,
                reason=str(rejection_event.payload.get("reason", "rule_precheck_rejected")),
            )

        if not director_decision.allowed:
            rejection_event = self._rule_engine.reject_player_action(
                session=session,
                action=routed.action,
                reason=f"director_precheck:{director_decision.reason or 'blocked'}",
            )
            response = ActionResponse(
                session_id=session.id,
                accepted=False,
                new_events=[rejection_event],
                state=build_state_summary(case, session),
            )
            return ActionIntakeResult(
                status=ActionIntakeStatus.REJECTED,
                route=routed,
                action=routed.action,
                response=response,
                reason=str(rejection_event.payload.get("reason", "director_precheck_blocked")),
            )

        response = self.handle(session=session, action=routed.action)
        return ActionIntakeResult(
            status=ActionIntakeStatus.ACCEPTED,
            route=routed,
            action=routed.action,
            response=response,
            reason=None if response.accepted else response.director_reason,
        )

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
        new_events.extend(
            self._archive_stale_memories(
                session=session,
                caused_by_event_id=player_event.id,
            )
        )
        turn = self._agent_loop.run_turn(case=case, session=session, action=action)
        context = turn.context
        intent = turn.intent
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
        self._finish_agent_trace(
            turn=turn,
            decision_allowed=decision.allowed,
            decision_reason=decision.reason,
            new_events=new_events,
            phase_after=session.narrative.phase,
            public_speech=speech,
            public_speech_source=(
                "npc" if decision.allowed else "director_safe_fallback"
            ),
        )

        return ActionResponse(
            session_id=session.id,
            accepted=decision.allowed,
            speech=speech,
            director_blocked=director_blocked,
            director_reason=director_reason,
            llm_fallback_used=_llm_fallback_used(intent),
            llm_error=intent.llm_error,
            new_events=new_events,
            state=build_state_summary(case, session),
        )

    def _finish_agent_trace(
        self,
        *,
        turn: AgentTurnResult,
        decision_allowed: bool,
        decision_reason: str | None,
        new_events: list[WorldEvent],
        phase_after: str,
        public_speech: str | None,
        public_speech_source: str | None,
    ) -> None:
        self._agent_loop.finish_trace(
            turn,
            director_allowed=decision_allowed,
            director_reason_category=_reason_category(decision_reason),
            rule_rejections=[
                str(event.payload.get("reason", "unknown"))
                for event in new_events
                if event.type == EventType.RULE_REJECTED
            ],
            new_events=new_events,
            phase_after=phase_after,
            public_speech=public_speech,
            public_speech_source=public_speech_source,
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

    def _archive_stale_memories(
        self,
        *,
        session: SessionState,
        caused_by_event_id: str | None,
    ) -> list[WorldEvent]:
        return self._memory_archival_system.apply(
            session=session,
            caused_by_event_id=caused_by_event_id,
        )


def create_runtime(
    case_packages: list[CasePackage],
    *,
    agent_gateway: AgentGateway | None = None,
    runtime_tracer: RuntimeTracer | None = None,
    retrieval_planner: RetrievalPlanner | None = None,
    context_limit_tokens: int = 8000,
) -> RuntimeContainer:
    recorder = EventRecorder()
    case_store = InMemoryCaseStore()
    for package in case_packages:
        case_store.add(package)
    session_store = InMemorySessionStore(recorder)
    rule_engine = RuleEngine(recorder)
    director = NarrativeDirector()
    agent_loop = AgentLoop(
        agent_gateway=agent_gateway or AgentGateway.from_env(),
        runtime_tracer=runtime_tracer or RuntimeTracer.disabled(),
        retrieval_planner=retrieval_planner,
        context_budget_manager=ContextBudgetManager(
            context_limit_tokens=context_limit_tokens,
        ),
        narrative_director=director,
    )
    action_service = ActionService(
        case_store=case_store,
        recorder=recorder,
        agent_loop=agent_loop,
        director=director,
        rule_engine=rule_engine,
        trigger_system=RuleTriggerSystem(recorder),
        derived_event_system=DerivedEventSystem(recorder),
        memory_snapshot_system=MemorySnapshotSystem(recorder),
        memory_archival_system=MemoryArchivalSystem(recorder),
    )
    return RuntimeContainer(
        case_store=case_store,
        session_store=session_store,
        action_service=action_service,
        rule_engine=rule_engine,
        agent_loop=agent_loop,
    )


def _redact_matched_text(matched_text: str | None) -> str | None:
    if matched_text is None:
        return None
    return "[redacted]"


def _reason_category(reason: str | None) -> str | None:
    if reason is None:
        return None
    normalized = reason.strip().lower().replace(" ", "_")
    if not normalized:
        return None
    return normalized[:80]


def _precheck_summary(allowed: bool, reason: str | None) -> str:
    if allowed:
        return "allowed"
    return f"blocked:{_reason_category(reason) or 'unknown'}"


def _llm_fallback_used(intent: object) -> bool:
    llm_error = getattr(intent, "llm_error", None)
    return bool(llm_error is not None and getattr(llm_error, "fallback_used", False))
