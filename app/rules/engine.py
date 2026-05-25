from __future__ import annotations

from app.domain.models import (
    AgentIntent,
    CasePackage,
    DiscoverClueAction,
    EventType,
    PlayerAction,
    ProposedActionType,
    RelationshipChangeAction,
    RelationshipState,
    SessionState,
    WorldEvent,
)
from app.runtime.events import EventRecorder

RELATIONSHIP_METRICS = {"trust", "suspicion", "fear", "intimacy", "hostility"}


class RuleEngine:
    def __init__(self, recorder: EventRecorder) -> None:
        self._recorder = recorder

    def apply_inspect(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
        caused_by_event_id: str,
    ) -> list[WorldEvent]:
        hotspot = None
        for scene in case.scenes:
            hotspot = next((item for item in scene.hotspots if item.id == action.target_id), None)
            if hotspot is not None:
                break

        if hotspot is None:
            return []

        events: list[WorldEvent] = []
        for clue_id in hotspot.discover_clues:
            if clue_id in session.discovered_clues:
                continue
            session.discovered_clues.add(clue_id)
            session.narrative.discovered_clues.add(clue_id)
            events.append(
                self._recorder.append(
                    session,
                    actor_id="system",
                    event_type=EventType.CLUE_DISCOVERED,
                    payload={"clue_id": clue_id, "source_hotspot_id": hotspot.id},
                    caused_by_event_id=caused_by_event_id,
                )
            )
        return events

    def apply_agent_intent(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        intent: AgentIntent,
        caused_by_event_id: str,
    ) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        for proposed_action in intent.proposed_actions:
            if proposed_action.type == ProposedActionType.RELATIONSHIP_CHANGE:
                events.append(
                    self._apply_relationship_change(
                        case=case,
                        session=session,
                        action=proposed_action,
                        caused_by_event_id=caused_by_event_id,
                    )
                )
            elif proposed_action.type == ProposedActionType.DISCOVER_CLUE:
                event = self._apply_discover_clue(
                    case=case,
                    session=session,
                    action=proposed_action,
                    caused_by_event_id=caused_by_event_id,
                )
                if event is not None:
                    events.append(event)
            elif proposed_action.type == ProposedActionType.NARRATIVE_PHASE_CHANGE:
                session.narrative.phase = proposed_action.phase
                events.append(
                    self._recorder.append(
                        session,
                        actor_id="system",
                        event_type=EventType.NARRATIVE_PHASE_CHANGED,
                        payload={"phase": proposed_action.phase},
                        caused_by_event_id=caused_by_event_id,
                    )
                )
        return events

    def _apply_relationship_change(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: RelationshipChangeAction,
        caused_by_event_id: str,
    ) -> WorldEvent:
        character_ids = {character.id for character in case.characters}
        valid_actor_ids = character_ids | {"player"}
        if action.source not in valid_actor_ids or action.target not in valid_actor_ids:
            return self._reject(
                session=session,
                action_type=action.type,
                reason="relationship endpoint is not a known character or player",
                payload={
                    "source": action.source,
                    "target": action.target,
                    "deltas": action.deltas,
                },
                caused_by_event_id=caused_by_event_id,
            )

        unknown_metrics = set(action.deltas) - RELATIONSHIP_METRICS
        if unknown_metrics:
            return self._reject(
                session=session,
                action_type=action.type,
                reason=f"unknown relationship metrics: {sorted(unknown_metrics)}",
                payload={
                    "source": action.source,
                    "target": action.target,
                    "deltas": action.deltas,
                },
                caused_by_event_id=caused_by_event_id,
            )

        key = relationship_key(action.source, action.target)
        relationship = session.relationships.get(key)
        if relationship is None:
            relationship = RelationshipState(source=action.source, target=action.target)
            session.relationships[key] = relationship

        for field, delta in action.deltas.items():
            current_value = getattr(relationship, field)
            setattr(relationship, field, current_value + delta)

        return self._recorder.append(
            session,
            actor_id="system",
            event_type=EventType.RELATIONSHIP_CHANGED,
            payload={
                "source": action.source,
                "target": action.target,
                "deltas": action.deltas,
                "current": relationship.model_dump(),
            },
            caused_by_event_id=caused_by_event_id,
        )

    def _apply_discover_clue(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: DiscoverClueAction,
        caused_by_event_id: str,
    ) -> WorldEvent | None:
        clue_ids = {clue.id for clue in case.clues}
        if action.clue_id not in clue_ids:
            return self._reject(
                session=session,
                action_type=action.type,
                reason="clue_id is not defined by the case package",
                payload={"clue_id": action.clue_id},
                caused_by_event_id=caused_by_event_id,
            )
        if action.clue_id in session.discovered_clues:
            return None
        session.discovered_clues.add(action.clue_id)
        session.narrative.discovered_clues.add(action.clue_id)
        return self._recorder.append(
            session,
            actor_id="system",
            event_type=EventType.CLUE_DISCOVERED,
            payload={"clue_id": action.clue_id, "source": "agent_intent"},
            caused_by_event_id=caused_by_event_id,
        )

    def _reject(
        self,
        *,
        session: SessionState,
        action_type: ProposedActionType,
        reason: str,
        payload: dict[str, object],
        caused_by_event_id: str,
    ) -> WorldEvent:
        return self._recorder.append(
            session,
            actor_id="rule_engine",
            event_type=EventType.RULE_REJECTED,
            payload={
                "action_type": action_type,
                "reason": reason,
                "proposed_payload": payload,
            },
            caused_by_event_id=caused_by_event_id,
        )


def relationship_key(source: str, target: str) -> str:
    return f"{source}->{target}"
