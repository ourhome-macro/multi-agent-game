from __future__ import annotations

from app.domain.models import (
    AgentMemorySnapshot,
    CasePackage,
    CharacterFactAwarenessState,
    CharacterImpression,
    EventType,
    MemoryCandidateState,
    MemoryOperation,
    NarrativeState,
    PlayerKnowledgeAcquisition,
    PlayerKnowledgeSourceType,
    PlayerKnowledgeState,
    RelationshipState,
    SessionState,
    WorldEvent,
    normalize_memory_operation,
)
from app.rules.engine import relationship_key, relationship_threshold_key
from app.runtime.character_fact_awareness import build_initial_character_fact_awareness


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
        character_fact_awareness=build_initial_character_fact_awareness(case),
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
            clue_id=(
                str(event.payload["clue_id"])
                if event.payload.get("clue_id") is not None
                else None
            ),
            world_info_id=(
                str(event.payload["world_info_id"])
                if event.payload.get("world_info_id") is not None
                else None
            ),
            confidence=float(event.payload.get("confidence", 1.0)),
            acquisition=PlayerKnowledgeAcquisition(
                str(event.payload.get("acquisition", PlayerKnowledgeAcquisition.DISCOVERED))
            ),
            source_type=PlayerKnowledgeSourceType(
                str(event.payload.get("source_type", PlayerKnowledgeSourceType.CLUE))
            ),
            title=str(event.payload["title"]),
            summary=str(event.payload["summary"]),
            source_event_id=str(event.payload["source_event_id"]),
        )
        session.player_knowledge[knowledge.knowledge_id] = knowledge
        return

    if event.type == EventType.CHARACTER_FACT_AWARENESS_UPDATED:
        awareness = CharacterFactAwarenessState.model_validate(event.payload)
        session.character_fact_awareness[awareness.awareness_id] = awareness
        return

    if event.type == EventType.MEMORY_CANDIDATE_CREATED:
        memory = MemoryCandidateState(
            memory_id=str(event.payload["memory_id"]),
            rule_id=_optional_str(event.payload.get("rule_id")),
            memory_type=str(event.payload.get("memory_type", "episodic")),
            memory_scope=str(event.payload.get("memory_scope", "npc_private")),
            memory_layer=str(event.payload.get("memory_layer", "working")),
            operation=normalize_memory_operation(event.payload.get("operation")),
            subject_id=str(event.payload["subject_id"]),
            owner_character_id=_optional_str(event.payload.get("owner_character_id")),
            visible_to_character_ids=[
                str(item) for item in event.payload.get("visible_to_character_ids", [])
            ],
            content=str(event.payload["content"]),
            source_event_id=str(event.payload["source_event_id"]),
            source_event_ids=_source_event_ids(
                event.payload,
                str(event.payload["source_event_id"]),
            ),
            source_memory_ids=[
                str(item) for item in event.payload.get("source_memory_ids", [])
            ],
            visibility=[str(item) for item in event.payload["visibility"]],
            salience=float(event.payload["salience"]),
            confidence=float(event.payload.get("confidence", 1.0)),
            metadata=_metadata(event.payload.get("metadata")),
        )
        session.memory_candidates[memory.memory_id] = memory
        return

    if event.type == EventType.AGENT_MEMORY_SNAPSHOT_UPDATED:
        memory_id = str(event.payload["memory_id"])
        current = session.memory_snapshots.get(memory_id)
        candidate = session.memory_candidates.get(memory_id)
        fallback_content = candidate.content if candidate is not None else ""
        content = str(event.payload.get("content") or fallback_content)
        created_at = current.created_at if current is not None else event.created_at
        operation = normalize_memory_operation(
            event.payload.get("operation") or event.payload.get("last_operation")
        )
        if current is not None and operation not in {
            MemoryOperation.REVISE,
            MemoryOperation.SUPERSEDE,
        }:
            content = current.content
        snapshot = AgentMemorySnapshot(
            memory_id=memory_id,
            rule_id=_optional_str(event.payload.get("rule_id")),
            memory_type=str(
                event.payload.get(
                    "memory_type",
                    candidate.memory_type if candidate is not None else "episodic",
                )
            ),
            memory_scope=str(
                event.payload.get(
                    "memory_scope",
                    candidate.memory_scope if candidate is not None else "npc_private",
                )
            ),
            memory_layer=str(
                event.payload.get(
                    "memory_layer",
                    candidate.memory_layer if candidate is not None else "working",
                )
            ),
            last_operation=operation,
            subject_id=_optional_str(event.payload.get("subject_id")),
            owner_character_id=_optional_str(event.payload.get("owner_character_id")),
            visible_to_character_ids=[
                str(item) for item in event.payload.get("visible_to_character_ids", [])
            ],
            content=content,
            source_event_ids=[str(item) for item in event.payload["source_event_ids"]],
            source_memory_ids=[
                str(item) for item in event.payload.get("source_memory_ids", [])
            ],
            salience=float(event.payload["salience"]),
            confidence=float(event.payload.get("confidence", 1.0)),
            visibility=str(event.payload["visibility"]),
            metadata=_metadata(event.payload.get("metadata")),
            last_updated_event_id=event.id,
            created_at=created_at,
            updated_at=event.created_at,
        )
        session.memory_snapshots[memory_id] = snapshot
        return

    if event.type == EventType.CHARACTER_IMPRESSION_UPDATED:
        impression = CharacterImpression.model_validate(event.payload)
        session.character_impressions.setdefault(impression.observer_id, {})[
            impression.target_id
        ] = impression
        return

    if event.type == EventType.NARRATIVE_BEAT_COMPLETED:
        session.narrative.completed_beats.add(str(event.payload["beat_id"]))
        return

    if event.type == EventType.NARRATIVE_PHASE_CHANGED:
        session.narrative.phase = str(event.payload["phase"])
        return


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _source_event_ids(payload: dict[str, object], fallback_event_id: str) -> list[str]:
    values = payload.get("source_event_ids")
    if isinstance(values, list):
        return [str(item) for item in values if str(item)]
    return [fallback_event_id]


def _metadata(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}
