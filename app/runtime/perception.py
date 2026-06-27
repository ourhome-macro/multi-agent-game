from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.domain.models import EventType, WorldEvent

NPC_OBSERVED_EVENT_TYPE = "npc.observed"

ObservationVisibility = Literal["public", "scene_shared", "private"]
PerceptionQuality = Literal["direct"]
ObservedPayload = dict[str, str | None]

_DEFAULT_BLOCKED_EVENT_TYPES = frozenset(
    {
        EventType.NPC_SKILL_SELECTED.value,
        EventType.NPC_SKILL_REJECTED.value,
        EventType.NPC_SKILL_COOLDOWN_UPDATED.value,
        EventType.DIRECTOR_BLOCKED.value,
        EventType.RULE_REJECTED.value,
        EventType.MEMORY_CANDIDATE_CREATED.value,
        EventType.AGENT_MEMORY_SNAPSHOT_UPDATED.value,
        EventType.CHARACTER_IMPRESSION_UPDATED.value,
        EventType.CHARACTER_FACT_AWARENESS_UPDATED.value,
    }
)

_TARGET_PRIVATE_EVENT_TYPES = frozenset(
    {
        EventType.PLAYER_TALKED.value,
        EventType.PLAYER_ASKED_ABOUT.value,
        EventType.PLAYER_ACCUSED.value,
        EventType.ACCUSATION_EVALUATED.value,
        EventType.NPC_REPLIED.value,
    }
)

_DEFAULT_PUBLIC_SCENE_EVENT_TYPES = frozenset(
    {
        EventType.PLAYER_INSPECTED.value,
        EventType.CLUE_DISCOVERED.value,
    }
)

_PRIVATE_VISIBILITIES = frozenset(
    {
        "private",
        "target_private",
        "npc_private",
        "director_audit",
    }
)


@dataclass(frozen=True)
class ObservedEvent:
    observer_id: str
    observed_event_id: str
    scene_id: str | None
    visibility: ObservationVisibility
    perception_quality: PerceptionQuality
    redacted_payload_ref: str

    def to_payload(self) -> ObservedPayload:
        return {
            "observer_id": self.observer_id,
            "observed_event_id": self.observed_event_id,
            "scene_id": self.scene_id,
            "visibility": self.visibility,
            "perception_quality": self.perception_quality,
            "redacted_payload_ref": self.redacted_payload_ref,
        }


class PerceptionSystem:
    """Build safe npc.observed payloads from world events.

    The payload is deliberately a reference envelope. It never copies the source
    event payload body into NPC-visible context.
    """

    def visible_events_for(
        self,
        *,
        case: object,
        session: object,
        observer_id: str,
        events: Iterable[WorldEvent],
    ) -> list[ObservedPayload]:
        _ = case
        observer_scene_id = _npc_scene_id(session, observer_id)
        observed: list[ObservedPayload] = []
        for event in events:
            perceived = self._perceive_event(
                event=event,
                observer_id=observer_id,
                observer_scene_id=observer_scene_id,
            )
            if perceived is not None:
                observed.append(perceived.to_payload())
        return observed

    def observe_recent(
        self,
        *,
        case: object,
        session: object,
        observer_id: str,
        events: Iterable[WorldEvent],
        limit: int | None = None,
    ) -> list[ObservedPayload]:
        recent_events = list(events)
        if limit is not None:
            if limit <= 0:
                return []
            recent_events = recent_events[-limit:]
        return self.visible_events_for(
            case=case,
            session=session,
            observer_id=observer_id,
            events=recent_events,
        )

    def _perceive_event(
        self,
        *,
        event: WorldEvent,
        observer_id: str,
        observer_scene_id: str | None,
    ) -> ObservedEvent | None:
        payload = event.payload
        if not isinstance(payload, dict):
            return None

        event_type = _event_type_value(event)
        if event_type in _DEFAULT_BLOCKED_EVENT_TYPES:
            return None
        if _has_private_memory_scope(payload, observer_id):
            return None
        if event_type == EventType.PLAYER_PRESENTED_CLUE.value:
            return self._perceive_presented_clue(
                event=event,
                observer_id=observer_id,
                observer_scene_id=observer_scene_id,
            )
        if self._target_private_event_visible(event_type, payload, observer_id):
            return _observed_event(
                event=event,
                observer_id=observer_id,
                scene_id=_event_scene_id(payload) or observer_scene_id,
                visibility="private",
            )
        if self._same_scene_public_event_visible(
            event_type=event_type,
            payload=payload,
            observer_scene_id=observer_scene_id,
        ):
            return _observed_event(
                event=event,
                observer_id=observer_id,
                scene_id=_event_scene_id(payload),
                visibility="public",
            )
        return None

    def _perceive_presented_clue(
        self,
        *,
        event: WorldEvent,
        observer_id: str,
        observer_scene_id: str | None,
    ) -> ObservedEvent | None:
        payload = event.payload
        scene_id = _event_scene_id(payload)
        present_character_ids = _string_set(payload.get("present_character_ids"))
        presentation_mode = _string_value(payload.get("presentation_mode"))
        is_scene_shared = presentation_mode == "scene_shared" or (
            presentation_mode is None and scene_id is not None and bool(present_character_ids)
        )

        if is_scene_shared:
            if scene_id is None or observer_scene_id != scene_id:
                return None
            if observer_id not in present_character_ids:
                return None
            return _observed_event(
                event=event,
                observer_id=observer_id,
                scene_id=scene_id,
                visibility="scene_shared",
            )

        if _string_value(payload.get("target_id")) != observer_id:
            return None
        return _observed_event(
            event=event,
            observer_id=observer_id,
            scene_id=scene_id or observer_scene_id,
            visibility="private",
        )

    @staticmethod
    def _target_private_event_visible(
        event_type: str,
        payload: dict[str, Any],
        observer_id: str,
    ) -> bool:
        if event_type not in _TARGET_PRIVATE_EVENT_TYPES:
            return False
        return _string_value(payload.get("target_id")) == observer_id

    @staticmethod
    def _same_scene_public_event_visible(
        *,
        event_type: str,
        payload: dict[str, Any],
        observer_scene_id: str | None,
    ) -> bool:
        _ = event_type
        scene_id = _event_scene_id(payload)
        if scene_id is None or observer_scene_id != scene_id:
            return False
        visibility = _string_value(payload.get("visibility"))
        if visibility in _PRIVATE_VISIBILITIES:
            return False
        if visibility in {"public", "scene_public"}:
            return True
        if event_type in _DEFAULT_PUBLIC_SCENE_EVENT_TYPES:
            return True
        if event_type in _TARGET_PRIVATE_EVENT_TYPES:
            return False
        return "target_id" not in payload


def visible_events_for(
    *,
    case: object,
    session: object,
    observer_id: str,
    events: Iterable[WorldEvent],
) -> list[ObservedPayload]:
    return PerceptionSystem().visible_events_for(
        case=case,
        session=session,
        observer_id=observer_id,
        events=events,
    )


def observe_recent(
    *,
    case: object,
    session: object,
    observer_id: str,
    events: Iterable[WorldEvent],
    limit: int | None = None,
) -> list[ObservedPayload]:
    return PerceptionSystem().observe_recent(
        case=case,
        session=session,
        observer_id=observer_id,
        events=events,
        limit=limit,
    )


def _observed_event(
    *,
    event: WorldEvent,
    observer_id: str,
    scene_id: str | None,
    visibility: ObservationVisibility,
) -> ObservedEvent:
    return ObservedEvent(
        observer_id=observer_id,
        observed_event_id=event.id,
        scene_id=scene_id,
        visibility=visibility,
        perception_quality="direct",
        redacted_payload_ref=f"world_event:{event.id}:payload",
    )


def _event_type_value(event: WorldEvent) -> str:
    value = getattr(event.type, "value", event.type)
    return str(value)


def _npc_scene_id(session: object, npc_id: str) -> str | None:
    locations = _mapping_or_attr(session, "npc_locations")
    if locations is None:
        return None
    location: object | None = None
    if isinstance(locations, Mapping):
        location = locations.get(npc_id)
    else:
        location = getattr(locations, npc_id, None)
    return _location_scene_id(location)


def _location_scene_id(location: object | None) -> str | None:
    if location is None:
        return None
    if isinstance(location, str):
        return location
    if isinstance(location, Mapping):
        for key in ("scene_id", "current_scene_id", "location_id"):
            value = location.get(key)
            if isinstance(value, str) and value:
                return value
        return None
    for attr in ("scene_id", "current_scene_id", "location_id"):
        value = getattr(location, attr, None)
        if isinstance(value, str) and value:
            return value
    return None


def _mapping_or_attr(source: object, key: str) -> object | None:
    if isinstance(source, Mapping):
        return source.get(key)
    return getattr(source, key, None)


def _event_scene_id(payload: dict[str, Any]) -> str | None:
    return _string_value(payload.get("scene_id"))


def _string_value(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _string_set(value: object) -> set[str]:
    if not isinstance(value, list | tuple | set):
        return set()
    return {item for item in value if isinstance(item, str) and item}


def _has_private_memory_scope(payload: dict[str, Any], observer_id: str) -> bool:
    scope = _string_value(payload.get("memory_scope"))
    if scope in {"npc_private", "director_audit"}:
        return True
    owner_character_id = _string_value(payload.get("owner_character_id"))
    if owner_character_id is not None and owner_character_id != observer_id:
        return True
    visible_to_character_ids = payload.get("visible_to_character_ids")
    if visible_to_character_ids is not None and observer_id not in _string_set(
        visible_to_character_ids
    ):
        return True
    return False
