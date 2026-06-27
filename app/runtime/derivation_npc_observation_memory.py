from __future__ import annotations

from app.domain.models import CasePackage, SessionState, WorldEvent
from app.runtime.derivation_memory_constants import (
    NPC_HEARSAY_MEMORY_RULE_ID,
    NPC_OBSERVED_MEMORY_RULE_ID,
)
from app.runtime.derivation_utils import (
    append_unique as _append_unique,
)
from app.runtime.derivation_utils import (
    clamp01 as _clamp01,
)
from app.runtime.derivation_utils import (
    npc_hearsay_memory_id as _npc_hearsay_memory_id,
)
from app.runtime.derivation_utils import (
    npc_observed_memory_id as _npc_observed_memory_id,
)

NPC_OBSERVED_EVENT_TYPE = "npc.observed"
NPC_HEARSAY_RECEIVED_EVENT_TYPE = "npc.hearsay.received"
MAX_HEARSAY_CONFIDENCE = 0.5

_HEARSAY_POLARITIES = {"believes", "suspects", "doubts"}


class NpcObservationMemoryDerivationMixin:
    def _derive_npc_observed_memory_candidate(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        observer_id = _character_payload_id(
            case,
            source_event,
            ("observer_id",),
            actor_fallback=True,
        )
        observed_event_id = _optional_str(source_event.payload.get("observed_event_id"))
        if observer_id is None or observed_event_id is None:
            return None

        source_event_ids = [source_event.id]
        _append_unique(source_event_ids, observed_event_id)

        metadata: dict[str, object] = {
            "authority_source": "world_event",
            "authority": "event_observed",
        }
        scene_id = _optional_str(source_event.payload.get("scene_id"))
        if scene_id is not None:
            metadata["scene_id"] = scene_id

        return self._store_memory_candidate(
            session=session,
            source_event=source_event,
            memory_id=_npc_observed_memory_id(observer_id, observed_event_id),
            rule_id=NPC_OBSERVED_MEMORY_RULE_ID,
            memory_type="episodic",
            memory_scope="npc_private",
            memory_layer="working",
            content=_observed_content(case, session, source_event, observer_id),
            salience=_payload_float(source_event.payload, "salience", fallback=0.65),
            owner_character_id=observer_id,
            visible_to_character_ids=[observer_id],
            source_event_ids=source_event_ids,
            metadata=metadata,
        )

    def _derive_npc_hearsay_memory_candidate(
        self,
        case: CasePackage,
        session: SessionState,
        source_event: WorldEvent,
    ) -> WorldEvent | None:
        receiver_id = _character_payload_id(
            case,
            source_event,
            ("receiver_id", "listener_id", "target_id"),
            actor_fallback=True,
        )
        if receiver_id is None:
            return None

        belief_subject = _belief_subject(source_event)
        metadata: dict[str, object] = {
            "authority_source": "npc_hearsay",
            "authority": "non_authoritative",
            "non_authoritative": True,
            "belief_subject": belief_subject,
            "belief_polarity": _belief_polarity(source_event),
        }

        return self._store_memory_candidate(
            session=session,
            source_event=source_event,
            memory_id=_npc_hearsay_memory_id(receiver_id, source_event.id),
            rule_id=NPC_HEARSAY_MEMORY_RULE_ID,
            memory_type="belief",
            memory_scope="npc_private",
            memory_layer="working",
            content=_hearsay_content(case, source_event, receiver_id, belief_subject),
            salience=_payload_float(source_event.payload, "salience", fallback=0.45),
            owner_character_id=receiver_id,
            visible_to_character_ids=[receiver_id],
            confidence=_hearsay_confidence(source_event),
            metadata=metadata,
        )


def _character_payload_id(
    case: CasePackage,
    source_event: WorldEvent,
    keys: tuple[str, ...],
    *,
    actor_fallback: bool,
) -> str | None:
    character_ids = {character.id for character in case.characters}
    for key in keys:
        value = _optional_str(source_event.payload.get(key))
        if value in character_ids:
            return value
    actor_id = _optional_str(source_event.actor_id)
    if actor_fallback and actor_id in character_ids:
        return actor_id
    return None


def _observed_content(
    case: CasePackage,
    session: SessionState,
    source_event: WorldEvent,
    observer_id: str,
) -> str:
    explicit = _payload_text(
        source_event.payload,
        ("summary", "content", "description", "text"),
    )
    if explicit is not None:
        return explicit

    observer_name = _character_name(case, observer_id)
    observed_event_id = _optional_str(source_event.payload.get("observed_event_id"))
    observed_event = _session_event_by_id(session, observed_event_id)
    if observed_event is None:
        return f"{observer_name} observed event '{observed_event_id}'."
    return (
        f"{observer_name} observed {observed_event.actor_id} produce "
        f"event '{_event_type_value(observed_event)}'."
    )


def _hearsay_content(
    case: CasePackage,
    source_event: WorldEvent,
    receiver_id: str,
    belief_subject: str,
) -> str:
    explicit = _payload_text(
        source_event.payload,
        ("summary", "content", "claim", "text"),
    )
    if explicit is not None:
        return explicit

    receiver_name = _character_name(case, receiver_id)
    speaker_id = _optional_str(source_event.payload.get("speaker_id"))
    speaker_name = _character_name(case, speaker_id) if speaker_id is not None else "someone"
    return f"{receiver_name} heard hearsay from {speaker_name} about {belief_subject}."


def _belief_subject(source_event: WorldEvent) -> str:
    return (
        _payload_text(source_event.payload, ("belief_subject", "claim_id", "subject_id"))
        or f"hearsay.{source_event.id}"
    )


def _belief_polarity(source_event: WorldEvent) -> str:
    polarity = _optional_str(source_event.payload.get("belief_polarity"))
    if polarity in _HEARSAY_POLARITIES:
        return polarity
    return "suspects"


def _hearsay_confidence(source_event: WorldEvent) -> float:
    confidence = _payload_float(
        source_event.payload,
        "confidence",
        fallback=MAX_HEARSAY_CONFIDENCE,
    )
    return min(confidence, MAX_HEARSAY_CONFIDENCE)


def _payload_float(
    payload: dict[str, object],
    key: str,
    *,
    fallback: float,
) -> float:
    try:
        return _clamp01(float(payload.get(key, fallback)))
    except (TypeError, ValueError):
        return _clamp01(fallback)


def _payload_text(payload: dict[str, object], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _optional_str(payload.get(key))
        if value is not None:
            return value
    return None


def _session_event_by_id(
    session: SessionState,
    event_id: str | None,
) -> WorldEvent | None:
    if event_id is None:
        return None
    return next((event for event in session.events if event.id == event_id), None)


def _character_name(case: CasePackage, character_id: str | None) -> str:
    if character_id is None:
        return "unknown"
    return next(
        (character.display_name for character in case.characters if character.id == character_id),
        character_id,
    )


def _event_type_value(event: WorldEvent) -> str:
    event_type = event.type
    value = getattr(event_type, "value", None)
    if isinstance(value, str):
        return value
    return str(event_type)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
