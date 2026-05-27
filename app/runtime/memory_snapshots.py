from __future__ import annotations

from app.domain.models import (
    AgentMemorySnapshot,
    EventType,
    MemoryCandidateState,
    SessionState,
    WorldEvent,
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
        operation = "created" if current is None else "updated"
        snapshot = self._reduce_candidate(current, candidate, event)
        session.memory_snapshots[snapshot.memory_id] = snapshot

        snapshot_event = self._recorder.append(
            session,
            actor_id="memory_snapshot_system",
            event_type=EventType.AGENT_MEMORY_SNAPSHOT_UPDATED,
            payload={
                "memory_id": snapshot.memory_id,
                "subject_id": snapshot.subject_id,
                "source_event_ids": snapshot.source_event_ids,
                "salience": snapshot.salience,
                "visibility": snapshot.visibility,
                "operation": operation,
            },
            caused_by_event_id=event.id,
        )
        snapshot.last_updated_event_id = snapshot_event.id
        snapshot.updated_at = snapshot_event.created_at
        if operation == "created":
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
            subject_id=str(event.payload["subject_id"]),
            content=str(event.payload["content"]),
            source_event_id=source_event_id,
            visibility=[str(item) for item in event.payload.get("visibility", [])],
            salience=float(event.payload["salience"]),
        )

    def _reduce_candidate(
        self,
        current: AgentMemorySnapshot | None,
        candidate: MemoryCandidateState,
        event: WorldEvent,
    ) -> AgentMemorySnapshot:
        source_event_ids = (
            list(current.source_event_ids) if current is not None else []
        )
        if candidate.source_event_id not in source_event_ids:
            source_event_ids.append(candidate.source_event_id)

        return AgentMemorySnapshot(
            memory_id=candidate.memory_id,
            subject_id=candidate.subject_id,
            content=current.content if current is not None else candidate.content,
            source_event_ids=source_event_ids,
            salience=max(current.salience if current is not None else 0.0, candidate.salience),
            visibility="private",
            last_updated_event_id=event.id,
            created_at=current.created_at if current is not None else event.created_at,
            updated_at=event.created_at,
        )
