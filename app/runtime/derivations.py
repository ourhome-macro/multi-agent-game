from __future__ import annotations

from app.domain.models import (
    CasePackage,
    EventType,
    MemoryCandidateState,
    PlayerKnowledgeState,
    SessionState,
    WorldEvent,
)
from app.runtime.events import EventRecorder


class DerivedEventSystem:
    def __init__(self, recorder: EventRecorder) -> None:
        self._recorder = recorder

    def derive(
        self,
        *,
        case: CasePackage,
        session: SessionState,
        source_events: list[WorldEvent],
    ) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        for source_event in source_events:
            if source_event.type == EventType.CLUE_DISCOVERED:
                knowledge_event = self._derive_player_knowledge(case, session, source_event)
                if knowledge_event is not None:
                    events.append(knowledge_event)
                memory_event = self._derive_clue_memory_candidate(case, session, source_event)
                if memory_event is not None:
                    events.append(memory_event)
            elif source_event.type == EventType.RELATIONSHIP_THRESHOLD_CROSSED:
                memory_event = self._derive_relationship_memory_candidate(
                    case,
                    session,
                    source_event,
                )
                if memory_event is not None:
                    events.append(memory_event)
            elif source_event.type == EventType.DIRECTOR_BLOCKED:
                memory_event = self._derive_director_block_memory_candidate(
                    case,
                    session,
                    source_event,
                )
                if memory_event is not None:
                    events.append(memory_event)
        return events

    def _derive_player_knowledge(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        clue_id = str(source_event.payload["clue_id"])
        clue = next((item for item in case.clues if item.id == clue_id), None)
        if clue is None:
            return None
        knowledge_id = f"player_knowledge.{clue_id}"
        if knowledge_id in session.player_knowledge:
            return None

        session.player_knowledge[knowledge_id] = PlayerKnowledgeState(
            knowledge_id=knowledge_id,
            clue_id=clue_id,
            title=clue.title,
            summary=clue.description,
            source_event_id=source_event.id,
        )
        return self._recorder.append(
            session,
            actor_id="derived_event_system",
            event_type=EventType.PLAYER_KNOWLEDGE_UPDATED,
            payload={
                "clue_id": clue_id,
                "knowledge_id": knowledge_id,
                "source_event_id": source_event.id,
                "title": clue.title,
                "summary": clue.description,
            },
            caused_by_event_id=source_event.id,
        )

    def _derive_clue_memory_candidate(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        clue_id = str(source_event.payload["clue_id"])
        clue = next((item for item in case.clues if item.id == clue_id), None)
        if clue is None:
            return None
        return self._store_memory_candidate(
            session=session,
            source_event=source_event,
            content=f"Player discovered clue '{clue.title}'.",
            salience=0.8,
        )

    def _derive_relationship_memory_candidate(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        source_id = str(source_event.payload["source_id"])
        metric = str(source_event.payload["metric"])
        state_name = str(source_event.payload["state"])
        character_name = next(
            (item.name for item in case.characters if item.id == source_id),
            source_id,
        )
        return self._store_memory_candidate(
            session=session,
            source_event=source_event,
            content=f"{character_name} became {state_name} toward the player ({metric}).",
            salience=0.7,
        )

    def _derive_director_block_memory_candidate(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        target_id = str(source_event.payload["target_id"])
        character_name = next(
            (item.name for item in case.characters if item.id == target_id),
            target_id,
        )
        return self._store_memory_candidate(
            session=session,
            source_event=source_event,
            content=f"Conversation with {character_name} was blocked by narrative rules.",
            salience=0.9,
        )

    def _store_memory_candidate(
        self,
        *,
        session: SessionState,
        source_event: WorldEvent,
        content: str,
        salience: float,
    ) -> WorldEvent | None:
        memory_id = f"memory_candidate.{source_event.id}"
        if memory_id in session.memory_candidates:
            return None
        session.memory_candidates[memory_id] = MemoryCandidateState(
            memory_id=memory_id,
            subject_id="player",
            content=content,
            source_event_id=source_event.id,
            visibility=["player"],
            salience=salience,
        )
        return self._recorder.append(
            session,
            actor_id="derived_event_system",
            event_type=EventType.MEMORY_CANDIDATE_CREATED,
            payload={
                "memory_id": memory_id,
                "subject_id": "player",
                "content": content,
                "source_event_id": source_event.id,
                "visibility": ["player"],
                "salience": salience,
            },
            caused_by_event_id=source_event.id,
        )
