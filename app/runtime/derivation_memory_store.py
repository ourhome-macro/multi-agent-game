from __future__ import annotations

from app.domain.models import (
    CasePackage,
    EventType,
    MemoryCandidateState,
    MemoryOperation,
    SessionState,
    WorldEvent,
    serialize_memory_operation,
)


class MemoryCandidateStoreMixin:
    def _character_name(self, case: CasePackage, character_id: str) -> str:
        return next(
            (item.display_name for item in case.characters if item.id == character_id),
            character_id,
        )

    def _store_memory_candidate(
        self,
        *,
        session: SessionState,
        source_event: WorldEvent,
        memory_id: str,
        rule_id: str | None = None,
        memory_type: str = "episodic",
        content: str,
        salience: float,
        owner_character_id: str | None,
        visible_to_character_ids: list[str],
        memory_scope: str = "npc_private",
        memory_layer: str = "working",
        operation: MemoryOperation = MemoryOperation.CREATE,
        source_memory_ids: list[str] | None = None,
        confidence: float = 1.0,
        metadata: dict[str, object] | None = None,
        subject_id: str = "player",
        source_event_ids: list[str] | None = None,
    ) -> WorldEvent | None:
        stored_source_event_ids = source_event_ids or [source_event.id]
        current = session.memory_candidates.get(memory_id)
        if current is not None and any(
            event_id in current.source_event_ids for event_id in stored_source_event_ids
        ):
            return None
        current_snapshot = session.memory_snapshots.get(memory_id)
        if current_snapshot is not None and any(
            event_id in current_snapshot.source_event_ids
            for event_id in stored_source_event_ids
        ):
            return None
        session.memory_candidates[memory_id] = MemoryCandidateState(
            memory_id=memory_id,
            rule_id=rule_id,
            memory_type=memory_type,
            memory_scope=memory_scope,
            memory_layer=memory_layer,
            operation=operation,
            subject_id=subject_id,
            owner_character_id=owner_character_id,
            visible_to_character_ids=visible_to_character_ids,
            content=content,
            source_event_id=source_event.id,
            source_event_ids=stored_source_event_ids,
            source_memory_ids=source_memory_ids or [],
            visibility=["player"],
            salience=salience,
            confidence=confidence,
            metadata=metadata or {},
        )
        return self._recorder.append(
            session,
            actor_id="derived_event_system",
            event_type=EventType.MEMORY_CANDIDATE_CREATED,
            payload={
                "memory_id": memory_id,
                "rule_id": rule_id,
                "memory_type": memory_type,
                "memory_scope": memory_scope,
                "memory_layer": memory_layer,
                "operation": serialize_memory_operation(operation),
                "subject_id": subject_id,
                "owner_character_id": owner_character_id,
                "visible_to_character_ids": visible_to_character_ids,
                "content": content,
                "source_event_id": source_event.id,
                "source_event_ids": stored_source_event_ids,
                "source_memory_ids": source_memory_ids or [],
                "visibility": ["player"],
                "salience": salience,
                "confidence": confidence,
                "metadata": metadata or {},
            },
            caused_by_event_id=source_event.id,
        )
