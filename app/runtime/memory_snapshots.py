from __future__ import annotations

from app.domain.models import (
    AgentMemorySnapshot,
    EventType,
    MemoryCandidateState,
    MemoryOperation,
    SessionState,
    WorldEvent,
    normalize_memory_operation,
    serialize_memory_operation,
)
from app.runtime.events import EventRecorder


class MemorySnapshotSystem:
    def __init__(self, recorder: EventRecorder) -> None:
        self._recorder = recorder

    def apply(self, *, session: SessionState, event: WorldEvent) -> list[WorldEvent]:
        if event.type != EventType.MEMORY_CANDIDATE_CREATED:
            return []
        if event.payload.get("subject_id") != "player":
            return []

        candidate = self._candidate_from_event(event)
        current = session.memory_snapshots.get(candidate.memory_id)
        operation = candidate.operation
        if (
            operation == MemoryOperation.CREATE
            and current is not None
        ):
            operation = MemoryOperation.REINFORCE
        snapshot = self._reduce_candidate(current, candidate, event)
        session.memory_snapshots[snapshot.memory_id] = snapshot

        snapshot_event = self._recorder.append(
            session,
            actor_id="memory_snapshot_system",
            event_type=EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
            payload={
                "memory_id": snapshot.memory_id,
                "rule_id": snapshot.rule_id,
                "memory_type": snapshot.memory_type,
                "memory_scope": snapshot.memory_scope,
                "memory_layer": snapshot.memory_layer,
                "last_operation": serialize_memory_operation(operation),
                "subject_id": snapshot.subject_id,
                "owner_character_id": snapshot.owner_character_id,
                "visible_to_character_ids": snapshot.visible_to_character_ids,
                "content": snapshot.content,
                "source_event_ids": snapshot.source_event_ids,
                "source_memory_ids": snapshot.source_memory_ids,
                "salience": snapshot.salience,
                "confidence": snapshot.confidence,
                "visibility": snapshot.visibility,
                "metadata": snapshot.metadata,
                "operation": serialize_memory_operation(operation),
            },
            caused_by_event_id=event.id,
        )
        snapshot.last_updated_event_id = snapshot_event.id
        snapshot.updated_at = snapshot_event.created_at
        snapshot.last_operation = operation
        if current is None:
            snapshot.created_at = snapshot_event.created_at
        return [snapshot_event]

    def _candidate_from_event(self, event: WorldEvent) -> MemoryCandidateState:
        source_event_id = str(event.payload.get("source_event_id") or event.id)
        memory_id = str(
            event.payload.get("memory_id")
            or f"memory_candidate.{event.payload['subject_id']}.{source_event_id}"
        )
        return MemoryCandidateState(
            memory_id=memory_id,
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
            source_event_id=source_event_id,
            source_event_ids=_source_event_ids(event.payload, source_event_id),
            source_memory_ids=[
                str(item) for item in event.payload.get("source_memory_ids", [])
            ],
            visibility=[str(item) for item in event.payload.get("visibility", [])],
            salience=float(event.payload["salience"]),
            confidence=float(event.payload.get("confidence", 1.0)),
            metadata=_metadata(event.payload.get("metadata")),
        )

    def _reduce_candidate(
        self,
        current: AgentMemorySnapshot | None,
        candidate: MemoryCandidateState,
        event: WorldEvent,
    ) -> AgentMemorySnapshot:
        operation = candidate.operation
        if (
            operation == MemoryOperation.CREATE
            and current is not None
        ):
            operation = MemoryOperation.REINFORCE
        source_event_ids = list(current.source_event_ids) if current is not None else []
        for event_id in candidate.source_event_ids or [candidate.source_event_id]:
            if event_id not in source_event_ids:
                source_event_ids.append(event_id)
        source_memory_ids = (
            list(current.source_memory_ids) if current is not None else []
        )
        for memory_id in candidate.source_memory_ids:
            if memory_id not in source_memory_ids:
                source_memory_ids.append(memory_id)
        metadata = dict(current.metadata) if current is not None else {}
        metadata.update(candidate.metadata)
        content = current.content if current is not None else candidate.content
        if operation in {MemoryOperation.REVISE, MemoryOperation.SUPERSEDE}:
            content = candidate.content
        memory_layer = (
            current.memory_layer if current is not None else candidate.memory_layer
        )
        if operation == MemoryOperation.ARCHIVE:
            memory_layer = "archival"

        return AgentMemorySnapshot(
            memory_id=candidate.memory_id,
            rule_id=current.rule_id if current is not None else candidate.rule_id,
            memory_type=(
                current.memory_type if current is not None else candidate.memory_type
            ),
            memory_scope=(
                current.memory_scope if current is not None else candidate.memory_scope
            ),
            memory_layer=memory_layer,
            last_operation=operation,
            subject_id=candidate.subject_id,
            owner_character_id=(
                current.owner_character_id
                if current is not None
                else candidate.owner_character_id
            ),
            visible_to_character_ids=(
                list(current.visible_to_character_ids)
                if current is not None
                else list(candidate.visible_to_character_ids)
            ),
            content=content,
            source_event_ids=source_event_ids,
            source_memory_ids=source_memory_ids,
            salience=max(current.salience if current is not None else 0.0, candidate.salience),
            confidence=max(
                current.confidence if current is not None else 0.0,
                candidate.confidence,
            ),
            visibility="private",
            metadata=metadata,
            last_updated_event_id=event.id,
            created_at=current.created_at if current is not None else event.created_at,
            updated_at=event.created_at,
        )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _source_event_ids(payload: dict[str, object], fallback_event_id: str) -> list[str]:
    values = payload.get("source_event_ids")
    if not isinstance(values, list) or not values:
        return [fallback_event_id]
    return [str(item) for item in values]


def _metadata(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}
