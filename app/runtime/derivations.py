from __future__ import annotations

from app.domain.models import (
    CasePackage,
    CharacterFactAwarenessSourceType,
    CharacterFactStance,
    EventType,
    PlayerKnowledgeAcquisition,
    PlayerKnowledgeSourceType,
    PlayerKnowledgeState,
    SessionState,
    WorldEvent,
)
from app.runtime.character_fact_awareness import upsert_character_fact_awareness
from app.runtime.derivation_impressions import CharacterImpressionDerivationMixin
from app.runtime.derivation_memory_candidates import MemoryCandidateDerivationMixin
from app.runtime.derivation_memory_constants import (
    ASKED_ABOUT_MEMORY_RULE_ID,
    PRESENTED_CLUE_MEMORY_RULE_ID,
)
from app.runtime.derivation_utils import (
    append_unique as _append_unique,
)
from app.runtime.events import EventRecorder

__all__ = [
    "ASKED_ABOUT_MEMORY_RULE_ID",
    "DerivedEventSystem",
    "PRESENTED_CLUE_MEMORY_RULE_ID",
]


class DerivedEventSystem(
    CharacterImpressionDerivationMixin,
    MemoryCandidateDerivationMixin,
):
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
            impression_event = self._derive_character_impression(case, session, source_event)
            if impression_event is not None:
                events.append(impression_event)
            if source_event.type == EventType.CLUE_DISCOVERED:
                knowledge_event = self._derive_player_knowledge(case, session, source_event)
                if knowledge_event is not None:
                    events.append(knowledge_event)
                memory_event = self._derive_clue_memory_candidate(case, session, source_event)
                if memory_event is not None:
                    events.append(memory_event)
                events.extend(
                    self._derive_clue_chain_typed_memory_candidates(
                        case,
                        session,
                        source_event,
                    )
                )
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
            elif source_event.type == EventType.PLAYER_ASKED_ABOUT:
                awareness_event = self._derive_character_awareness_from_asked_about(
                    case,
                    session,
                    source_event,
                )
                if awareness_event is not None:
                    events.append(awareness_event)
                configured_events = self._derive_configured_memory_candidates(
                    case=case,
                    session=session,
                    source_event=source_event,
                )
                events.extend(configured_events)
                if not self._configured_event_created_memory(
                    configured_events,
                    self._asked_about_memory_id(source_event),
                ):
                    memory_event = self._derive_asked_about_memory_candidate(
                        case,
                        session,
                        source_event,
                    )
                    if memory_event is not None:
                        events.append(memory_event)
            elif source_event.type == EventType.PLAYER_PRESENTED_CLUE:
                awareness_event = self._derive_character_awareness_from_presented_clue(
                    case,
                    session,
                    source_event,
                )
                if awareness_event is not None:
                    events.append(awareness_event)
                configured_events = self._derive_configured_memory_candidates(
                    case=case,
                    session=session,
                    source_event=source_event,
                )
                events.extend(configured_events)
                if not self._configured_event_created_memory(
                    configured_events,
                    self._presented_clue_memory_id(source_event),
                ):
                    memory_event = self._derive_presented_clue_memory_candidate(
                        case,
                        session,
                        source_event,
                    )
                    if memory_event is not None:
                        events.append(memory_event)
                if not self._configured_event_created_memory(
                    configured_events,
                    self._scene_shared_presented_clue_memory_id(source_event),
                ):
                    memory_event = self._derive_scene_shared_presented_clue_memory_candidate(
                        case,
                        session,
                        source_event,
                    )
                    if memory_event is not None:
                        events.append(memory_event)
                events.extend(
                    self._derive_scene_shared_presented_clue_private_memory_candidates(
                        case,
                        session,
                        source_event,
                    )
                )
            elif source_event.type == EventType.PLAYER_ACCUSED:
                awareness_events = self._derive_character_awareness_from_accusation(
                    case,
                    session,
                    source_event,
                )
                events.extend(awareness_events)
                configured_events = self._derive_configured_memory_candidates(
                    case=case,
                    session=session,
                    source_event=source_event,
                )
                events.extend(configured_events)
                if not self._configured_event_created_memory(
                    configured_events,
                    self._player_accused_memory_id(source_event),
                ):
                    memory_event = self._derive_player_accused_memory_candidate(
                        case,
                        session,
                        source_event,
                    )
                    if memory_event is not None:
                        events.append(memory_event)
            elif source_event.type == EventType.ACCUSATION_EVALUATED:
                memory_event = self._derive_accusation_evaluated_memory_candidate(
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

        world_info_by_id = {item.id: item for item in case.world_info}
        world_info_id = next(
            (
                item_id
                for item_id in clue.reveals_world_info
                if item_id in world_info_by_id
            ),
            None,
        )
        knowledge_id = (
            f"player_knowledge.{world_info_id}"
            if world_info_id is not None
            else f"player_knowledge.{clue_id}"
        )
        if knowledge_id in session.player_knowledge:
            return None

        world_info = world_info_by_id.get(world_info_id) if world_info_id is not None else None
        title = world_info.title if world_info is not None else clue.title
        summary = world_info.description if world_info is not None else clue.description

        session.player_knowledge[knowledge_id] = PlayerKnowledgeState(
            knowledge_id=knowledge_id,
            clue_id=clue_id,
            world_info_id=world_info_id,
            confidence=1.0,
            acquisition=PlayerKnowledgeAcquisition.DISCOVERED,
            source_type=PlayerKnowledgeSourceType.CLUE,
            title=title,
            summary=summary,
            source_event_id=source_event.id,
        )
        return self._recorder.append(
            session,
            actor_id="derived_event_system",
            event_type=EventType.PLAYER_KNOWLEDGE_UPDATED,
            payload={
                "clue_id": clue_id,
                "world_info_id": world_info_id,
                "knowledge_id": knowledge_id,
                "confidence": 1.0,
                "acquisition": PlayerKnowledgeAcquisition.DISCOVERED.value,
                "source_type": PlayerKnowledgeSourceType.CLUE.value,
                "source_event_id": source_event.id,
                "title": title,
                "summary": summary,
            },
            caused_by_event_id=source_event.id,
        )

    def _derive_character_awareness_from_asked_about(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        subject_type = str(source_event.payload["subject_type"])
        if subject_type != "clue":
            return None
        clue_id = str(source_event.payload["subject_id"])
        world_info_ids = self._world_info_ids_for_clue(case, clue_id)
        if not world_info_ids:
            return None
        return upsert_character_fact_awareness(
            session=session,
            recorder=self._recorder,
            character_id=str(source_event.payload["target_id"]),
            world_info_id=world_info_ids[0],
            stance=CharacterFactStance.SUSPECTS,
            confidence=0.55,
            source_type=CharacterFactAwarenessSourceType.PLAYER_ASKED_ABOUT,
            source_refs=[f"clue:{clue_id}"],
            evidence_clue_ids=[clue_id],
            source_event=source_event,
        )

    def _derive_character_awareness_from_presented_clue(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        clue_id = str(source_event.payload["clue_id"])
        world_info_ids = self._world_info_ids_for_clue(case, clue_id)
        if not world_info_ids:
            return None
        return upsert_character_fact_awareness(
            session=session,
            recorder=self._recorder,
            character_id=str(source_event.payload["target_id"]),
            world_info_id=world_info_ids[0],
            stance=CharacterFactStance.KNOWS,
            confidence=0.85,
            source_type=CharacterFactAwarenessSourceType.PLAYER_PRESENTED_CLUE,
            source_refs=[f"clue:{clue_id}"],
            evidence_clue_ids=[clue_id],
            source_event=source_event,
        )

    def _derive_character_awareness_from_accusation(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> list[WorldEvent]:
        events: list[WorldEvent] = []
        evidence_clue_ids = [
            str(item) for item in source_event.payload.get("evidence_clue_ids", [])
        ]
        for world_info_id in self._world_info_ids_for_clues(case, evidence_clue_ids):
            event = upsert_character_fact_awareness(
                session=session,
                recorder=self._recorder,
                character_id=str(source_event.payload["target_id"]),
                world_info_id=world_info_id,
                stance=CharacterFactStance.KNOWS,
                confidence=0.95,
                source_type=CharacterFactAwarenessSourceType.PLAYER_ACCUSED,
                source_refs=[f"claim:{source_event.payload['claim_id']}"],
                evidence_clue_ids=evidence_clue_ids,
                source_event=source_event,
            )
            if event is not None:
                events.append(event)
        return events

    def _world_info_ids_for_clue(self, case: CasePackage, clue_id: str) -> list[str]:
        clue = next((item for item in case.clues if item.id == clue_id), None)
        if clue is None:
            return []
        world_info_ids = {item.id for item in case.world_info}
        return [
            world_info_id
            for world_info_id in clue.reveals_world_info
            if world_info_id in world_info_ids
        ]

    def _world_info_ids_for_clues(
        self,
        case: CasePackage,
        clue_ids: list[str],
    ) -> list[str]:
        world_info_ids: list[str] = []
        for clue_id in clue_ids:
            for world_info_id in self._world_info_ids_for_clue(case, clue_id):
                _append_unique(world_info_ids, world_info_id)
        return world_info_ids
