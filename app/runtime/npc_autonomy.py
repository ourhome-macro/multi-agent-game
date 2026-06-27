from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import CasePackage, SessionState
from app.runtime.npc_locations import npc_scene_id

NPC_AUTONOMY_MOVE: Final = "move"
NPC_AUTONOMY_OBSERVE: Final = "observe"
NPC_AUTONOMY_WAIT: Final = "wait"
NPC_AUTONOMY_TALK_TO: Final = "talk_to"

ALLOWED_NPC_AUTONOMY_TYPES: Final = frozenset(
    {
        NPC_AUTONOMY_MOVE,
        NPC_AUTONOMY_OBSERVE,
        NPC_AUTONOMY_WAIT,
        NPC_AUTONOMY_TALK_TO,
    }
)

NPC_LOCATION_CHANGED_EVENT_TYPE: Final = "npc.location.changed"
NPC_OBSERVED_EVENT_TYPE: Final = "npc.observed"

FORBIDDEN_NPC_AUTONOMY_FLAGS: Final = frozenset(
    {
        "clue_unlock",
        "clue.discover",
        "clue.discovered",
        "phase_change",
        "narrative.phase.change",
        "narrative.phase.changed",
        "forbidden_disclosure",
    }
)

FORBIDDEN_NPC_AUTONOMY_SIDE_EFFECT_TYPES: Final = frozenset(
    {
        "clue.discover",
        "clue.discovered",
        "narrative.phase.change",
        "narrative.phase.changed",
    }
)


class NpcAutonomyIntent(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    actor_id: str
    from_scene_id: str | None = None
    to_scene_id: str | None = None
    scene_id: str | None = None
    target_id: str | None = None
    rationale: str | None = None
    flags: list[str] = Field(default_factory=list)
    proposed_actions: list[Any] = Field(default_factory=list)


def autonomy_intent_type(intent: object) -> str | None:
    return _text_field(intent, "type", "intent_type", "action_type", lower=True)


def autonomy_actor_id(intent: object) -> str | None:
    return _text_field(intent, "actor_id", "character_id", "npc_id")


def autonomy_from_scene_id(intent: object) -> str | None:
    return _text_field(intent, "from_scene_id", "from_scene")


def autonomy_to_scene_id(intent: object) -> str | None:
    return _text_field(intent, "to_scene_id", "to_scene")


def autonomy_scene_id(intent: object) -> str | None:
    return _text_field(intent, "scene_id", "scene")


def autonomy_target_id(intent: object) -> str | None:
    return _text_field(intent, "target_id", "target_character_id")


def autonomy_rationale(intent: object) -> str | None:
    return _text_field(intent, "rationale", "reason")


def autonomy_action_type(intent: object) -> str:
    intent_type = autonomy_intent_type(intent) or "unknown"
    return f"npc_autonomy.{intent_type}"


def autonomy_payload(intent: object) -> dict[str, object]:
    model_dump = getattr(intent, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json", exclude_none=True)
        if isinstance(dumped, dict):
            return {str(key): value for key, value in dumped.items()}

    if isinstance(intent, Mapping):
        return {str(key): value for key, value in intent.items()}

    payload: dict[str, object] = {}
    for field_name in (
        "type",
        "intent_type",
        "action_type",
        "actor_id",
        "character_id",
        "npc_id",
        "from_scene_id",
        "to_scene_id",
        "scene_id",
        "target_id",
        "rationale",
        "reason",
        "flags",
        "risk_flags",
        "proposed_actions",
        "proposed_events",
        "side_effects",
    ):
        value = getattr(intent, field_name, None)
        if value is not None:
            payload[field_name] = value
    return payload


def autonomy_flag_names(intent: object) -> set[str]:
    names: set[str] = set()
    for field_name in ("flags", "risk_flags"):
        raw_value = _field(intent, field_name)
        if raw_value is None:
            continue
        names.update(_string_items(raw_value))
    return names


def autonomy_proposed_side_effect_types(intent: object) -> set[str]:
    side_effects: set[str] = set()
    for field_name in ("proposed_actions", "proposed_events", "side_effects"):
        raw_value = _field(intent, field_name)
        if raw_value is None:
            continue
        items = raw_value if isinstance(raw_value, list) else [raw_value]
        for item in items:
            if isinstance(item, str):
                side_effects.add(item.strip().lower())
                continue
            item_type = _text_field(item, "type", "event_type", "action_type", lower=True)
            if item_type is not None:
                side_effects.add(item_type)
    return side_effects


def forbidden_autonomy_side_effects(intent: object) -> list[str]:
    forbidden = set(autonomy_flag_names(intent)) & FORBIDDEN_NPC_AUTONOMY_FLAGS
    forbidden.update(
        set(autonomy_proposed_side_effect_types(intent))
        & FORBIDDEN_NPC_AUTONOMY_SIDE_EFFECT_TYPES
    )
    return sorted(forbidden)


def current_npc_scene_id(
    case: CasePackage,
    session: SessionState,
    character_id: str,
) -> str | None:
    current = npc_scene_id(case=case, session=session, character_id=character_id)
    if current is not None:
        return current

    for event in reversed(session.events):
        if _event_type_name(event.type) != NPC_LOCATION_CHANGED_EVENT_TYPE:
            continue
        if event.actor_id != character_id and event.payload.get("actor_id") != character_id:
            continue
        to_scene_id = event.payload.get("to_scene_id")
        if isinstance(to_scene_id, str) and to_scene_id:
            return to_scene_id

    for scene in case.scenes:
        if character_id in scene.characters:
            return scene.id
    return None


def _field(value: object, field_name: str) -> object | None:
    if isinstance(value, Mapping):
        return value.get(field_name)
    return getattr(value, field_name, None)


def _text_field(value: object, *field_names: str, lower: bool = False) -> str | None:
    for field_name in field_names:
        raw_value = _field(value, field_name)
        text = _to_text(raw_value, lower=lower)
        if text is not None:
            return text
    return None


def _to_text(value: object | None, *, lower: bool = False) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        value = value.value
    text = str(value).strip()
    if not text:
        return None
    return text.lower() if lower else text


def _string_items(value: object) -> set[str]:
    if isinstance(value, str):
        return {value.strip().lower()} if value.strip() else set()
    if not isinstance(value, list):
        return set()
    items: set[str] = set()
    for item in value:
        text = _to_text(item, lower=True)
        if text is not None:
            items.add(text)
    return items


def _event_type_name(value: object) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)
