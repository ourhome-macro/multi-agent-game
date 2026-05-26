from __future__ import annotations

from app.domain.models import (
    CasePackage,
    EventType,
    NarrativeState,
    RelationshipState,
    SessionState,
    WorldEvent,
)
from app.rules.engine import relationship_key


def replay_events(case: CasePackage, events: list[WorldEvent]) -> SessionState:
    if not events:
        raise ValueError("Cannot replay an empty event list")

    first_event = events[0]
    session = SessionState(
        id=first_event.session_id,
        case_id=case.meta.id,
        narrative=NarrativeState(phase=case.meta.initial_phase),
        relationships={
            relationship_key(item.source_id, item.target_id): RelationshipState(**item.model_dump())
            for item in case.relationships
        },
    )

    for event in events:
        _apply_event(session, event)
        session.events.append(event)
    return session


def _apply_event(session: SessionState, event: WorldEvent) -> None:
    if event.type == EventType.CLUE_DISCOVERED:
        clue_id = str(event.payload["clue_id"])
        session.discovered_clues.add(clue_id)
        session.narrative.discovered_clues.add(clue_id)
        return

    if event.type == EventType.RELATIONSHIP_CHANGED:
        current = event.payload.get("current")
        if isinstance(current, dict):
            relationship = RelationshipState.model_validate(current)
            session.relationships[
                relationship_key(relationship.source_id, relationship.target_id)
            ] = relationship
        return

    if event.type == EventType.NARRATIVE_BEAT_COMPLETED:
        session.narrative.completed_beats.add(str(event.payload["beat_id"]))
        return

    if event.type == EventType.NARRATIVE_PHASE_CHANGED:
        session.narrative.phase = str(event.payload["phase"])
