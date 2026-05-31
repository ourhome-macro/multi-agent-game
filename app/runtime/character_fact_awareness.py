from __future__ import annotations

from app.domain.models import (
    CasePackage,
    CharacterFactAwarenessSourceType,
    CharacterFactAwarenessState,
    CharacterFactStance,
    EventType,
    SessionState,
    WorldEvent,
)
from app.runtime.events import EventRecorder

STANCE_PRIORITY = {
    CharacterFactStance.MISBELIEVES: 0,
    CharacterFactStance.SUSPECTS: 1,
    CharacterFactStance.KNOWS: 2,
    CharacterFactStance.CONCEALS: 3,
}


def character_fact_awareness_id(character_id: str, world_info_id: str) -> str:
    return f"character_fact_awareness.{character_id}.{world_info_id}"


def build_initial_character_fact_awareness(
    case: CasePackage,
) -> dict[str, CharacterFactAwarenessState]:
    awareness_by_id: dict[str, CharacterFactAwarenessState] = {}
    for character in case.characters:
        for goal in character.private.goals:
            for world_info_id in goal.related_world_info_ids:
                _upsert_initial_awareness(
                    awareness_by_id=awareness_by_id,
                    character_id=character.id,
                    world_info_id=world_info_id,
                    stance=CharacterFactStance.CONCEALS,
                    confidence=0.9,
                    source_type=CharacterFactAwarenessSourceType.CHARACTER_CARD,
                    source_refs=[f"goal:{goal.id}"],
                    evidence_clue_ids=[],
                )
        for secret in character.private.secrets:
            for world_info_id in secret.related_world_info_ids:
                _upsert_initial_awareness(
                    awareness_by_id=awareness_by_id,
                    character_id=character.id,
                    world_info_id=world_info_id,
                    stance=CharacterFactStance.CONCEALS,
                    confidence=1.0,
                    source_type=CharacterFactAwarenessSourceType.CHARACTER_CARD,
                    source_refs=[f"secret:{secret.id}"],
                    evidence_clue_ids=secret.related_clue_ids,
                )
        for knowledge in character.private.knowledge:
            for world_info_id in knowledge.related_world_info_ids:
                _upsert_initial_awareness(
                    awareness_by_id=awareness_by_id,
                    character_id=character.id,
                    world_info_id=world_info_id,
                    stance=CharacterFactStance.KNOWS,
                    confidence=1.0,
                    source_type=CharacterFactAwarenessSourceType.CHARACTER_CARD,
                    source_refs=[f"knowledge:{knowledge.id}"],
                    evidence_clue_ids=knowledge.related_clue_ids,
                )
    return awareness_by_id


def _upsert_initial_awareness(
    *,
    awareness_by_id: dict[str, CharacterFactAwarenessState],
    character_id: str,
    world_info_id: str,
    stance: CharacterFactStance,
    confidence: float,
    source_type: CharacterFactAwarenessSourceType,
    source_refs: list[str],
    evidence_clue_ids: list[str],
) -> None:
    awareness_id = character_fact_awareness_id(character_id, world_info_id)
    current = awareness_by_id.get(awareness_id)
    if current is None:
        awareness_by_id[awareness_id] = CharacterFactAwarenessState(
            awareness_id=awareness_id,
            character_id=character_id,
            world_info_id=world_info_id,
            stance=stance,
            confidence=confidence,
            source_type=source_type,
            source_refs=sorted(set(source_refs)),
            evidence_clue_ids=sorted(set(evidence_clue_ids)),
            source_event_ids=["case_package"],
            last_updated_event_id="case_package",
        )
        return

    if STANCE_PRIORITY[stance] > STANCE_PRIORITY[current.stance]:
        current.stance = stance
    current.confidence = max(current.confidence, confidence)
    current.source_refs = sorted({*current.source_refs, *source_refs})
    current.evidence_clue_ids = sorted({*current.evidence_clue_ids, *evidence_clue_ids})


def upsert_character_fact_awareness(
    *,
    session: SessionState,
    recorder: EventRecorder,
    character_id: str,
    world_info_id: str,
    stance: CharacterFactStance,
    confidence: float,
    source_type: CharacterFactAwarenessSourceType,
    source_refs: list[str],
    evidence_clue_ids: list[str],
    source_event: WorldEvent,
) -> WorldEvent | None:
    awareness_id = character_fact_awareness_id(character_id, world_info_id)
    current = session.character_fact_awareness.get(awareness_id)
    if current is not None and source_event.id in current.source_event_ids:
        return None

    if current is None:
        awareness = CharacterFactAwarenessState(
            awareness_id=awareness_id,
            character_id=character_id,
            world_info_id=world_info_id,
            stance=stance,
            confidence=confidence,
            source_type=source_type,
            source_refs=sorted(set(source_refs)),
            evidence_clue_ids=sorted(set(evidence_clue_ids)),
            source_event_ids=[source_event.id],
            last_updated_event_id=source_event.id,
        )
    else:
        awareness = current.model_copy(deep=True)
        if STANCE_PRIORITY[stance] > STANCE_PRIORITY[awareness.stance]:
            awareness.stance = stance
        awareness.confidence = max(awareness.confidence, confidence)
        awareness.source_type = source_type
        awareness.source_refs = sorted({*awareness.source_refs, *source_refs})
        awareness.evidence_clue_ids = sorted(
            {*awareness.evidence_clue_ids, *evidence_clue_ids}
        )
        awareness.source_event_ids = [
            *awareness.source_event_ids,
            source_event.id,
        ]

    event = recorder.append(
        session,
        actor_id="character_fact_awareness_system",
        event_type=EventType.CHARACTER_FACT_AWARENESS_UPDATED,
        payload=awareness.model_dump(mode="json"),
        caused_by_event_id=source_event.id,
    )
    awareness.last_updated_event_id = event.id
    event.payload = awareness.model_dump(mode="json")
    session.character_fact_awareness[awareness_id] = awareness
    return event
