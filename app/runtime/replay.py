from __future__ import annotations

from app.domain.models import (
    AgentMemorySnapshot,
    CasePackage,
    EventType,
    MemoryCandidateState,
    NarrativeState,
    PlayerKnowledgeState,
    RelationshipState,
    SessionState,
    WorldEvent,
)
from app.rules.engine import relationship_key, relationship_threshold_key


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

    if event.type in {
        EventType.PLAYER_ASKED_ABOUT,
        EventType.PLAYER_PRESENTED_CLUE,
        EventType.PLAYER_ACCUSED,
        EventType.ACCUSATION_EVALUATED,
    }:
        return

    if event.type == EventType.RELATIONSHIP_CHANGED:
        current = event.payload.get("current")
        if isinstance(current, dict):
            relationship = RelationshipState.model_validate(current)
            session.relationships[
                relationship_key(relationship.source_id, relationship.target_id)
            ] = relationship
        return

    if event.type == EventType.RELATIONSHIP_THRESHOLD_CROSSED:
        session.relationship_thresholds_crossed.add(
            relationship_threshold_key(
                str(event.payload["source_id"]),
                str(event.payload["target_id"]),
                str(event.payload["metric"]),
                str(event.payload["state"]),
            )
        )
        return

    if event.type == EventType.PLAYER_KNOWLEDGE_UPDATED:
        knowledge = PlayerKnowledgeState(
            knowledge_id=str(event.payload["knowledge_id"]),
            clue_id=str(event.payload["clue_id"]),
            title=str(event.payload["title"]),
            summary=str(event.payload["summary"]),
            source_event_id=str(event.payload["source_event_id"]),
        )
        session.player_knowledge[knowledge.knowledge_id] = knowledge
        return

    if event.type == EventType.MEMORY_CANDIDATE_CREATED:
        memory = MemoryCandidateState(
            memory_id=str(event.payload["memory_id"]),
            subject_id=str(event.payload["subject_id"]),
            content=str(event.payload["content"]),
            source_event_id=str(event.payload["source_event_id"]),
            visibility=[str(item) for item in event.payload["visibility"]],
            salience=float(event.payload["salience"]),
        )
        session.memory_candidates[memory.memory_id] = memory
        return

    if event.type == EventType.AGENT_MEMORY_SNAPSHOT_UPDATED:
        memory_id = str(event.payload["memory_id"])
        current = session.memory_snapshots.get(memory_id)
        candidate = session.memory_candidates.get(memory_id)
        content = candidate.content if candidate is not None else ""
        created_at = current.created_at if current is not None else event.created_at
        snapshot = AgentMemorySnapshot(
            memory_id=memory_id,
            subject_id=str(event.payload["subject_id"]),
            content=current.content if current is not None else content,
            source_event_ids=[str(item) for item in event.payload["source_event_ids"]],
            salience=float(event.payload["salience"]),
            visibility=str(event.payload["visibility"]),
            last_updated_event_id=event.id,
            created_at=created_at,
            updated_at=event.created_at,
        )
        session.memory_snapshots[memory_id] = snapshot
        return

    if event.type == EventType.NARRATIVE_BEAT_COMPLETED:
        session.narrative.completed_beats.add(str(event.payload["beat_id"]))
        return

    if event.type == EventType.NARRATIVE_PHASE_CHANGED:
        session.narrative.phase = str(event.payload["phase"])
