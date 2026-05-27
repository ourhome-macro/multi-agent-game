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
    SubjectType,
    WorldEvent,
    clamp_relationship_metric,
)
from app.runtime.events import EventRecorder
from app.runtime.pressure import calculate_interaction_pressure

RELATIONSHIP_METRICS = {"trust", "suspicion", "fear", "intimacy", "hostility"}
RELATIONSHIP_THRESHOLDS = {
    "suspicion": (0.7, "guarded"),
    "fear": (0.7, "afraid"),
    "trust": (0.7, "cooperative"),
}


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
                events.extend(
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
                events.append(
                    self._reject(
                        session=session,
                        action_type=proposed_action.type,
                        reason="narrative phase changes must be driven by narrative rules",
                        payload={"phase": proposed_action.phase},
                        caused_by_event_id=caused_by_event_id,
                    )
                )
        return events

    def apply_present_clue(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> list[WorldEvent]:
        if not self._is_known_character(case, action.target_id):
            return [
                self._reject(
                    session=session,
                    action_type="player.present_clue",
                    reason="target_id is not a known character",
                    payload={
                        "target_id": action.target_id,
                        "clue_id": action.clue_id,
                        "text": action.text,
                    },
                    caused_by_event_id=None,
                )
            ]
        clue_id = str(action.clue_id)
        clue_ids = {clue.id for clue in case.clues}
        if clue_id not in clue_ids:
            return [
                self._reject(
                    session=session,
                    action_type="player.present_clue",
                    reason="clue_id is not defined by the case package",
                    payload={
                        "target_id": action.target_id,
                        "clue_id": clue_id,
                        "text": action.text,
                    },
                    caused_by_event_id=None,
                )
            ]
        if clue_id not in session.discovered_clues:
            return [
                self._reject(
                    session=session,
                    action_type="player.present_clue",
                    reason="clue_id has not been discovered",
                    payload={
                        "target_id": action.target_id,
                        "clue_id": clue_id,
                        "text": action.text,
                    },
                    caused_by_event_id=None,
                )
            ]
        knowledge_id = f"player_knowledge.{clue_id}"
        if knowledge_id not in session.player_knowledge:
            return [
                self._reject(
                    session=session,
                    action_type="player.present_clue",
                    reason="clue_id is not available in player knowledge",
                    payload={
                        "target_id": action.target_id,
                        "clue_id": clue_id,
                        "knowledge_id": knowledge_id,
                        "text": action.text,
                    },
                    caused_by_event_id=None,
                )
            ]
        return [
            self._recorder.append(
                session,
                actor_id="player",
                event_type=EventType.PLAYER_PRESENTED_CLUE,
                payload={
                    "target_id": action.target_id,
                    "clue_id": clue_id,
                    "knowledge_id": knowledge_id,
                    "text": action.text,
                    "interaction_pressure": calculate_interaction_pressure(case, action),
                },
            )
        ]

    def apply_ask_about(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: PlayerAction,
    ) -> list[WorldEvent]:
        if not self._is_known_character(case, action.target_id):
            return [
                self._reject(
                    session=session,
                    action_type="player.ask_about",
                    reason="target_id is not a known character",
                    payload={
                        "target_id": action.target_id,
                        "subject_type": action.subject_type,
                        "subject_id": action.subject_id,
                        "text": action.text,
                    },
                    caused_by_event_id=None,
                )
            ]

        subject_id = str(action.subject_id)
        payload: dict[str, object] = {
            "target_id": action.target_id,
            "subject_type": str(action.subject_type.value if action.subject_type else ""),
            "subject_id": subject_id,
            "text": action.text,
            "interaction_pressure": calculate_interaction_pressure(case, action),
        }
        if action.subject_type == SubjectType.CLUE:
            clue_ids = {clue.id for clue in case.clues}
            if subject_id not in clue_ids:
                return [
                    self._reject(
                        session=session,
                        action_type="player.ask_about",
                        reason="subject clue is not defined by the case package",
                        payload=payload,
                        caused_by_event_id=None,
                    )
            ]
            knowledge_id = f"player_knowledge.{subject_id}"
            if (
                subject_id not in session.discovered_clues
                and knowledge_id not in session.player_knowledge
            ):
                return [
                    self._reject(
                        session=session,
                        action_type="player.ask_about",
                        reason="subject clue has not been discovered",
                        payload=payload,
                        caused_by_event_id=None,
                    )
                ]
            if knowledge_id in session.player_knowledge:
                payload["knowledge_id"] = knowledge_id

        elif action.subject_type == SubjectType.CHARACTER:
            if not self._is_known_character(case, subject_id):
                return [
                    self._reject(
                        session=session,
                        action_type="player.ask_about",
                        reason="subject character is not defined by the case package",
                        payload=payload,
                        caused_by_event_id=None,
                    )
                ]
        elif action.subject_type == SubjectType.SCENE:
            if not any(scene.id == subject_id for scene in case.scenes):
                return [
                    self._reject(
                        session=session,
                        action_type="player.ask_about",
                        reason="subject scene is not defined by the case package",
                        payload=payload,
                        caused_by_event_id=None,
                    )
                ]

        return [
            self._recorder.append(
                session,
                actor_id="player",
                event_type=EventType.PLAYER_ASKED_ABOUT,
                payload=payload,
            )
        ]

    def _apply_relationship_change(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        action: RelationshipChangeAction,
        caused_by_event_id: str,
    ) -> list[WorldEvent]:
        character_ids = {character.id for character in case.characters}
        valid_actor_ids = character_ids | {"player"}
        if action.source_id not in valid_actor_ids or action.target_id not in valid_actor_ids:
            return [
                self._reject(
                    session=session,
                    action_type=action.type,
                    reason="relationship endpoint is not a known character or player",
                    payload={
                        "source_id": action.source_id,
                        "target_id": action.target_id,
                        "deltas": action.deltas,
                    },
                    caused_by_event_id=caused_by_event_id,
                )
            ]

        unknown_metrics = set(action.deltas) - RELATIONSHIP_METRICS
        if unknown_metrics:
            return [
                self._reject(
                    session=session,
                    action_type=action.type,
                    reason=f"unknown relationship metrics: {sorted(unknown_metrics)}",
                    payload={
                        "source_id": action.source_id,
                        "target_id": action.target_id,
                        "deltas": action.deltas,
                    },
                    caused_by_event_id=caused_by_event_id,
                )
            ]

        key = relationship_key(action.source_id, action.target_id)
        relationship = session.relationships.get(key)
        if relationship is None:
            relationship = RelationshipState(source_id=action.source_id, target_id=action.target_id)
            session.relationships[key] = relationship

        previous_values = {field: getattr(relationship, field) for field in RELATIONSHIP_METRICS}
        for field, delta in action.deltas.items():
            current_value = getattr(relationship, field)
            setattr(relationship, field, clamp_relationship_metric(current_value + delta))

        events = [
            self._recorder.append(
                session,
                actor_id="system",
                event_type=EventType.RELATIONSHIP_CHANGED,
                payload={
                    "source_id": action.source_id,
                    "target_id": action.target_id,
                    "deltas": action.deltas,
                    "current": relationship.model_dump(mode="json"),
                },
                caused_by_event_id=caused_by_event_id,
            )
        ]
        events.extend(
            self._apply_relationship_thresholds(
                session=session,
                relationship=relationship,
                previous_values=previous_values,
                caused_by_event_id=events[-1].id,
            )
        )
        return events

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
        action_type: ProposedActionType | str,
        reason: str,
        payload: dict[str, object],
        caused_by_event_id: str | None,
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

    def _apply_relationship_thresholds(
        self,
        *,
        session: SessionState,
        relationship: RelationshipState,
        previous_values: dict[str, float],
        caused_by_event_id: str,
    ) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        for metric, (threshold, state_name) in RELATIONSHIP_THRESHOLDS.items():
            previous_value = previous_values.get(metric, 0.0)
            current_value = getattr(relationship, metric)
            threshold_key = relationship_threshold_key(
                relationship.source_id,
                relationship.target_id,
                metric,
                state_name,
            )
            if threshold_key in session.relationship_thresholds_crossed:
                continue
            if previous_value < threshold <= current_value:
                session.relationship_thresholds_crossed.add(threshold_key)
                events.append(
                    self._recorder.append(
                        session,
                        actor_id="system",
                        event_type=EventType.RELATIONSHIP_THRESHOLD_CROSSED,
                        payload={
                            "source_id": relationship.source_id,
                            "target_id": relationship.target_id,
                            "metric": metric,
                            "threshold": threshold,
                            "state": state_name,
                            "current_value": current_value,
                        },
                        caused_by_event_id=caused_by_event_id,
                    )
                )
        return events

    def _is_known_character(self, case: CasePackage, character_id: str) -> bool:
        return any(character.id == character_id for character in case.characters)


def relationship_key(source_id: str, target_id: str) -> str:
    return f"{source_id}->{target_id}"


def relationship_threshold_key(
    source_id: str,
    target_id: str,
    metric: str,
    state_name: str,
) -> str:
    return f"{source_id}->{target_id}:{metric}:{state_name}"
