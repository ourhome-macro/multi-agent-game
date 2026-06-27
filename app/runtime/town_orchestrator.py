from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.director.narrative_director import NarrativeDirector
from app.domain.models import (
    CasePackage,
    EventType,
    NpcLocationState,
    SessionState,
    TownClockState,
    WorldEvent,
)
from app.rules.engine import RuleEngine
from app.runtime.derivations import DerivedEventSystem
from app.runtime.events import EventRecorder
from app.runtime.memory_snapshots import MemorySnapshotSystem
from app.runtime.npc_autonomy import (
    NPC_AUTONOMY_MOVE,
    NPC_AUTONOMY_OBSERVE,
    NPC_AUTONOMY_WAIT,
    NpcAutonomyIntent,
    current_npc_scene_id,
)
from app.runtime.perception import PerceptionSystem


@dataclass(frozen=True)
class TownTickResult:
    tick_event: WorldEvent
    candidate_intents: list[NpcAutonomyIntent]
    new_events: list[WorldEvent]


class TownOrchestrator:
    """Deterministic V1 town tick coordinator.

    V1 does not call an LLM. It advances the town clock, proposes a small
    deterministic autonomy intent set, runs Director and RuleEngine gates, then
    lets perception and derived memory systems produce replayable follow-up events.
    """

    def __init__(
        self,
        *,
        recorder: EventRecorder | None = None,
        director: NarrativeDirector | None = None,
        rule_engine: RuleEngine | None = None,
        perception_system: PerceptionSystem | None = None,
        derived_event_system: DerivedEventSystem | None = None,
        memory_snapshot_system: MemorySnapshotSystem | None = None,
        max_intents_per_tick: int = 1,
        max_observations_per_event: int = 1,
    ) -> None:
        if max_intents_per_tick < 1:
            raise ValueError("max_intents_per_tick must be positive")
        if max_observations_per_event < 0:
            raise ValueError("max_observations_per_event must not be negative")

        self._recorder = recorder or EventRecorder()
        self._director = director or NarrativeDirector()
        self._rule_engine = rule_engine or RuleEngine(self._recorder)
        self._perception_system = perception_system or PerceptionSystem()
        self._derived_event_system = derived_event_system or DerivedEventSystem(self._recorder)
        self._memory_snapshot_system = memory_snapshot_system or MemorySnapshotSystem(
            self._recorder
        )
        self._max_intents_per_tick = max_intents_per_tick
        self._max_observations_per_event = max_observations_per_event

    def tick_once(self, *, case: CasePackage, session: SessionState) -> TownTickResult:
        self._ensure_initial_locations(case=case, session=session)

        tick_event = self._advance_town_clock(session)
        new_events = [tick_event]
        candidate_intents = self._candidate_intents(case=case, session=session)

        applied = 0
        for intent in candidate_intents:
            if applied >= self._max_intents_per_tick:
                break
            if not self._director_allows(case=case, session=session, intent=intent):
                continue

            intent_events = self._rule_engine.apply_npc_autonomy_intent(
                case=case,
                session=session,
                intent=intent,
                caused_by_event_id=tick_event.id,
            )
            for event in intent_events:
                self._apply_runtime_projection(session=session, event=event)
                new_events.append(event)

                if _event_type_value(event) == EventType.RULE_REJECTED.value:
                    continue
                new_events.extend(
                    self._derive_and_snapshot(case=case, session=session, source_event=event)
                )
                if _event_type_value(event) == EventType.NPC_LOCATION_CHANGED.value:
                    observation_events = self._observe_location_event(
                        case=case,
                        session=session,
                        source_event=event,
                    )
                    for observation_event in observation_events:
                        new_events.append(observation_event)
                        new_events.extend(
                            self._derive_and_snapshot(
                                case=case,
                                session=session,
                                source_event=observation_event,
                            )
                        )
            applied += 1

        return TownTickResult(
            tick_event=tick_event,
            candidate_intents=candidate_intents,
            new_events=new_events,
        )

    def _advance_town_clock(self, session: SessionState) -> WorldEvent:
        previous_tick = session.town_clock.tick
        current_tick = previous_tick + 1
        event = self._recorder.append(
            session,
            actor_id="town",
            event_type=EventType.TOWN_TICK_ADVANCED,
            payload={
                "previous": {"tick": previous_tick},
                "current": {"tick": current_tick},
                "from_tick": previous_tick,
                "to_tick": current_tick,
                "llm_called": False,
                "policy": "deterministic_v1",
            },
        )
        session.town_clock = TownClockState(
            tick=current_tick,
            updated_at_event_id=event.id,
        )
        return event

    def _candidate_intents(
        self,
        *,
        case: CasePackage,
        session: SessionState,
    ) -> list[NpcAutonomyIntent]:
        character_ids = sorted(character.id for character in case.characters)
        for actor_id in character_ids:
            current_scene_id = current_npc_scene_id(case, session, actor_id)
            if current_scene_id is None:
                continue
            target_scene_id = self._preferred_move_scene(
                case=case,
                session=session,
                actor_id=actor_id,
                current_scene_id=current_scene_id,
            )
            if target_scene_id is not None and target_scene_id != current_scene_id:
                return [
                    NpcAutonomyIntent(
                        type=NPC_AUTONOMY_MOVE,
                        actor_id=actor_id,
                        from_scene_id=current_scene_id,
                        to_scene_id=target_scene_id,
                        rationale="deterministic town tick movement",
                    )
                ]

        for actor_id in character_ids:
            current_scene_id = current_npc_scene_id(case, session, actor_id)
            if current_scene_id is None:
                continue
            target_id = self._first_other_character_in_scene(
                case=case,
                session=session,
                scene_id=current_scene_id,
                actor_id=actor_id,
            )
            if target_id is not None:
                return [
                    NpcAutonomyIntent(
                        type=NPC_AUTONOMY_OBSERVE,
                        actor_id=actor_id,
                        scene_id=current_scene_id,
                        target_id=target_id,
                        rationale="deterministic town tick observation",
                    )
                ]

        if character_ids:
            actor_id = character_ids[0]
            current_scene_id = current_npc_scene_id(case, session, actor_id)
            return [
                NpcAutonomyIntent(
                    type=NPC_AUTONOMY_WAIT,
                    actor_id=actor_id,
                    scene_id=current_scene_id,
                    rationale="deterministic town tick wait",
                )
            ]
        return []

    def _preferred_move_scene(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        actor_id: str,
        current_scene_id: str,
    ) -> str | None:
        for scene in case.scenes:
            if scene.id == current_scene_id:
                continue
            if self._first_other_character_in_scene(
                case=case,
                session=session,
                scene_id=scene.id,
                actor_id=actor_id,
            ):
                return scene.id

        scene_ids = [scene.id for scene in case.scenes]
        if len(scene_ids) < 2 or current_scene_id not in scene_ids:
            return None
        current_index = scene_ids.index(current_scene_id)
        return scene_ids[(current_index + 1) % len(scene_ids)]

    def _director_allows(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        intent: NpcAutonomyIntent,
    ) -> bool:
        decision = self._director.precheck_npc_autonomy(case, session, intent)
        return bool(getattr(decision, "allowed", decision))

    def _observe_location_event(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> list[WorldEvent]:
        if self._max_observations_per_event == 0:
            return []
        scene_id = _location_scene_id(source_event)
        if scene_id is None:
            return []
        actor_id = _payload_text(source_event.payload, "actor_id") or source_event.actor_id
        observer_ids = self._observer_ids_in_scene(
            case=case,
            session=session,
            scene_id=scene_id,
            excluded_actor_id=actor_id,
        )

        events: list[WorldEvent] = []
        for observer_id in observer_ids[: self._max_observations_per_event]:
            payloads = self._perception_system.visible_events_for(
                case=case,
                session=session,
                observer_id=observer_id,
                events=[source_event],
            )
            for payload in payloads:
                event_payload = {str(key): value for key, value in payload.items()}
                event_payload.setdefault("observer_id", observer_id)
                event_payload.setdefault("observed_event_id", source_event.id)
                event_payload.setdefault("scene_id", scene_id)
                events.append(
                    self._recorder.append(
                        session,
                        actor_id=observer_id,
                        event_type=EventType.NPC_OBSERVED,
                        payload=event_payload,
                        caused_by_event_id=source_event.id,
                    )
                )
        return events

    def _derive_and_snapshot(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        derived_events = self._derived_event_system.derive(
            case=case,
            session=session,
            source_events=[source_event],
        )
        for event in derived_events:
            events.append(event)
            events.extend(self._memory_snapshot_system.apply(session=session, event=event))
        return events

    def _apply_runtime_projection(self, *, session: SessionState, event: WorldEvent) -> None:
        if _event_type_value(event) != EventType.NPC_LOCATION_CHANGED.value:
            return
        payload = event.payload
        actor_id = _payload_text(payload, "actor_id") or event.actor_id
        scene_id = _location_scene_id(event)
        if scene_id is None:
            return

        current_payload = payload.get("current")
        if not isinstance(current_payload, dict):
            current_payload = {}
        current_payload = {str(key): value for key, value in current_payload.items()}
        current_payload.setdefault("npc_id", actor_id)
        current_payload.setdefault("scene_id", scene_id)
        current_payload.setdefault("updated_at_tick", session.town_clock.tick)
        payload["current"] = current_payload
        payload.setdefault("npc_id", actor_id)
        payload.setdefault("scene_id", scene_id)
        payload.setdefault("to_scene_id", scene_id)
        if "rationale" not in payload and "movement_reason" in payload:
            payload["rationale"] = payload["movement_reason"]

        previous_scene_id = _payload_text(payload, "from_scene_id") or _payload_text(
            current_payload,
            "from_scene_id",
        )
        if previous_scene_id is not None:
            payload.setdefault("from_scene_id", previous_scene_id)
            if not isinstance(payload.get("previous"), dict):
                payload["previous"] = {"scene_id": previous_scene_id}

        session.npc_locations[actor_id] = NpcLocationState(
            npc_id=actor_id,
            scene_id=scene_id,
            updated_at_tick=session.town_clock.tick,
            updated_at_event_id=event.id,
        )

    def _ensure_initial_locations(
        self,
        *,
        case: CasePackage,
        session: SessionState,
    ) -> None:
        for scene in case.scenes:
            for character_id in scene.characters:
                if character_id in session.npc_locations:
                    continue
                session.npc_locations[character_id] = NpcLocationState(
                    npc_id=character_id,
                    scene_id=scene.id,
                    updated_at_tick=session.town_clock.tick,
                )

    def _observer_ids_in_scene(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        scene_id: str,
        excluded_actor_id: str,
    ) -> list[str]:
        return [
            character.id
            for character in sorted(case.characters, key=lambda item: item.id)
            if character.id != excluded_actor_id
            and current_npc_scene_id(case, session, character.id) == scene_id
        ]

    def _first_other_character_in_scene(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        scene_id: str,
        actor_id: str,
    ) -> str | None:
        for character in sorted(case.characters, key=lambda item: item.id):
            if character.id == actor_id:
                continue
            if current_npc_scene_id(case, session, character.id) == scene_id:
                return character.id
        return None


def _event_type_value(event: WorldEvent) -> str:
    event_type = event.type
    if isinstance(event_type, Enum):
        return str(event_type.value)
    return str(event_type)


def _location_scene_id(event: WorldEvent) -> str | None:
    payload = event.payload
    current = payload.get("current")
    if isinstance(current, dict):
        scene_id = _payload_text(current, "scene_id")
        if scene_id is not None:
            return scene_id
    return _payload_text(payload, "scene_id", "to_scene_id")


def _payload_text(payload: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None
