from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.models import EventType, MemoryType, WorldEvent

JIANG_YANHUI_ID = "jiang_yanhui"
EMPTY_CAPSULES_ID = "empty_capsules"
MEDICINE_PRESENTED_CLUE_RULE_ID = (
    "memory_rule.jiang_empty_capsules_medicine_pressure.presented_clue.v1"
)
MEDICINE_ASKED_ABOUT_RULE_ID = (
    "memory_rule.jiang_empty_capsules_medicine_pressure.asked_about.v1"
)
MEDICINE_TOPIC_RULE_IDS = {
    MEDICINE_PRESENTED_CLUE_RULE_ID,
    MEDICINE_ASKED_ABOUT_RULE_ID,
}
MEDICINE_BELIEF_MEMORY_ID = (
    f"memory.player.belief.{JIANG_YANHUI_ID}.{EMPTY_CAPSULES_ID}"
)
MEDICINE_RELATIONSHIP_MEMORY_ID = (
    f"memory.player.relationship.{JIANG_YANHUI_ID}.{EMPTY_CAPSULES_ID}"
)
MEDICINE_STRATEGY_MEMORY_ID = (
    f"memory.player.strategy.{JIANG_YANHUI_ID}.{EMPTY_CAPSULES_ID}"
)
MEDICINE_STRATEGY_ID = "avoid_medicine_topic"


@dataclass(frozen=True)
class MemoryEffect:
    memory_id: str
    memory_type: MemoryType
    content: str
    salience: float
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedMemoryEffect:
    rule_id: str
    source_memory_id: str
    effect: MemoryEffect


@dataclass(frozen=True)
class MemoryDerivationRule:
    id: str
    trigger_action_type: str
    target_character_id: str | None
    subject_id: str | None
    produces: tuple[MemoryEffect, ...]

    def matches(self, source_event: WorldEvent) -> bool:
        if source_event.type.value != self.trigger_action_type:
            return False
        if (
            self.target_character_id is not None
            and source_event.payload.get("target_id") != self.target_character_id
        ):
            return False
        if self.subject_id is None:
            return True
        return _event_subject_id(source_event) == self.subject_id


MEMORY_DERIVATION_RULES: tuple[MemoryDerivationRule, ...] = (
    MemoryDerivationRule(
        id=MEDICINE_PRESENTED_CLUE_RULE_ID,
        trigger_action_type=EventType.PLAYER_PRESENTED_CLUE.value,
        target_character_id=JIANG_YANHUI_ID,
        subject_id=EMPTY_CAPSULES_ID,
        produces=(
            MemoryEffect(
                memory_id=MEDICINE_BELIEF_MEMORY_ID,
                memory_type="belief",
                content="Jiang believes the player is closing in on the medicine clue.",
                salience=0.9,
                confidence=0.8,
                metadata={
                    "belief_subject": "player_approaching_medicine_truth",
                    "belief_polarity": "believes",
                    "clue_id": EMPTY_CAPSULES_ID,
                },
            ),
            MemoryEffect(
                memory_id=MEDICINE_RELATIONSHIP_MEMORY_ID,
                memory_type="relationship",
                content=(
                    "Jiang becomes more suspicious of the player around the medicine clue."
                ),
                salience=0.85,
                confidence=0.8,
                metadata={
                    "relationship_delta": {
                        "suspicion": 0.2,
                        "trust": -0.1,
                    },
                    "clue_id": EMPTY_CAPSULES_ID,
                },
            ),
            MemoryEffect(
                memory_id=MEDICINE_STRATEGY_MEMORY_ID,
                memory_type="strategy",
                content="Jiang is inclined to avoid the medicine topic.",
                salience=0.95,
                confidence=0.85,
                metadata={
                    "strategy_id": MEDICINE_STRATEGY_ID,
                    "clue_id": EMPTY_CAPSULES_ID,
                },
            ),
        ),
    ),
    MemoryDerivationRule(
        id=MEDICINE_ASKED_ABOUT_RULE_ID,
        trigger_action_type=EventType.PLAYER_ASKED_ABOUT.value,
        target_character_id=JIANG_YANHUI_ID,
        subject_id=EMPTY_CAPSULES_ID,
        produces=(
            MemoryEffect(
                memory_id=MEDICINE_BELIEF_MEMORY_ID,
                memory_type="belief",
                content="Jiang believes the player is closing in on the medicine clue.",
                salience=0.9,
                confidence=0.8,
                metadata={
                    "belief_subject": "player_approaching_medicine_truth",
                    "belief_polarity": "believes",
                    "clue_id": EMPTY_CAPSULES_ID,
                },
            ),
            MemoryEffect(
                memory_id=MEDICINE_RELATIONSHIP_MEMORY_ID,
                memory_type="relationship",
                content=(
                    "Jiang becomes more suspicious of the player around the medicine clue."
                ),
                salience=0.85,
                confidence=0.8,
                metadata={
                    "relationship_delta": {
                        "suspicion": 0.2,
                        "trust": -0.1,
                    },
                    "clue_id": EMPTY_CAPSULES_ID,
                },
            ),
            MemoryEffect(
                memory_id=MEDICINE_STRATEGY_MEMORY_ID,
                memory_type="strategy",
                content="Jiang is inclined to avoid the medicine topic.",
                salience=0.95,
                confidence=0.85,
                metadata={
                    "strategy_id": MEDICINE_STRATEGY_ID,
                    "clue_id": EMPTY_CAPSULES_ID,
                },
            ),
        ),
    ),
)


def resolve_memory_derivation_effects(source_event: WorldEvent) -> list[ResolvedMemoryEffect]:
    effects: list[ResolvedMemoryEffect] = []
    source_memory_id = _source_memory_id(source_event)
    if source_memory_id is None:
        return effects
    for rule in MEMORY_DERIVATION_RULES:
        if not rule.matches(source_event):
            continue
        effects.extend(
            ResolvedMemoryEffect(
                rule_id=rule.id,
                source_memory_id=source_memory_id,
                effect=effect,
            )
            for effect in rule.produces
        )
    return effects


def memory_derivation_rule_ids_for_event(source_event: WorldEvent) -> set[str]:
    return {rule.id for rule in MEMORY_DERIVATION_RULES if rule.matches(source_event)}


def _event_subject_id(source_event: WorldEvent) -> str | None:
    if source_event.type == EventType.PLAYER_PRESENTED_CLUE:
        return _optional_str(source_event.payload.get("clue_id"))
    if source_event.type == EventType.PLAYER_ASKED_ABOUT:
        return _optional_str(source_event.payload.get("subject_id"))
    return None


def _source_memory_id(source_event: WorldEvent) -> str | None:
    target_id = _optional_str(source_event.payload.get("target_id"))
    if target_id is None:
        return None
    if source_event.type == EventType.PLAYER_PRESENTED_CLUE:
        clue_id = _optional_str(source_event.payload.get("clue_id"))
        if clue_id is None:
            return None
        return f"memory.player.presented_clue.{target_id}.{clue_id}"
    if source_event.type == EventType.PLAYER_ASKED_ABOUT:
        subject_type = _optional_str(source_event.payload.get("subject_type"))
        subject_id = _optional_str(source_event.payload.get("subject_id"))
        if subject_type is None or subject_id is None:
            return None
        return f"memory.player.asked_about.{target_id}.{subject_type}.{subject_id}"
    return None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
