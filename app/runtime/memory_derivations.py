from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import (
    CasePackage,
    EventType,
    MemoryDerivationRuleConfig,
    MemoryImpressionEffectConfig,
    MemoryType,
    WorldEvent,
)

# Player action events runtime can resolve a subject from when deriving typed
# memory. _event_subject_id only understands these; the loader rejects rules
# that trigger on anything else.
MEMORY_DERIVATION_TRIGGER_EVENTS = {
    EventType.PLAYER_ASKED_ABOUT.value,
    EventType.PLAYER_PRESENTED_CLUE.value,
}
_TEMPLATE_TOKEN = re.compile(r"\{([^}]*)\}")


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
class ResolvedImpressionEffect:
    rule_id: str
    impression: MemoryImpressionEffectConfig
    produced_memory_ids: tuple[str, ...]


def _rule_matches(rule: MemoryDerivationRuleConfig, source_event: WorldEvent) -> bool:
    if source_event.type.value != rule.trigger_action_type:
        return False
    if (
        rule.target_character_id is not None
        and source_event.payload.get("target_id") != rule.target_character_id
    ):
        return False
    if rule.subject_id is None:
        return True
    return _event_subject_id(source_event) == rule.subject_id


def _matched_rules(
    case: CasePackage,
    source_event: WorldEvent,
) -> list[MemoryDerivationRuleConfig]:
    return [
        rule
        for rule in case.memory_derivation_rules
        if _rule_matches(rule, source_event)
    ]


def resolve_memory_derivation_effects(
    case: CasePackage,
    source_event: WorldEvent,
) -> list[ResolvedMemoryEffect]:
    source_memory_id = _source_memory_id(source_event)
    if source_memory_id is None:
        return []
    context = _template_context(source_event)
    effects: list[ResolvedMemoryEffect] = []
    for rule in _matched_rules(case, source_event):
        for produced in rule.produces:
            effects.append(
                ResolvedMemoryEffect(
                    rule_id=rule.id,
                    source_memory_id=source_memory_id,
                    effect=MemoryEffect(
                        memory_id=_render(produced.memory_id, context),
                        memory_type=produced.memory_type,
                        content=_render(produced.content, context),
                        salience=produced.salience,
                        confidence=produced.confidence,
                        metadata=dict(produced.metadata),
                    ),
                )
            )
    return effects


def resolve_memory_impression_effects(
    case: CasePackage,
    source_event: WorldEvent,
) -> list[ResolvedImpressionEffect]:
    context = _template_context(source_event)
    resolved: list[ResolvedImpressionEffect] = []
    for rule in _matched_rules(case, source_event):
        if rule.impression is None:
            continue
        resolved.append(
            ResolvedImpressionEffect(
                rule_id=rule.id,
                impression=rule.impression,
                produced_memory_ids=tuple(
                    _render(produced.memory_id, context) for produced in rule.produces
                ),
            )
        )
    return resolved


def memory_derivation_rule_ids_for_event(
    case: CasePackage,
    source_event: WorldEvent,
) -> set[str]:
    return {rule.id for rule in _matched_rules(case, source_event)}


def _template_context(source_event: WorldEvent) -> dict[str, str]:
    context: dict[str, str] = {}
    target_id = _optional_str(source_event.payload.get("target_id"))
    if target_id is not None:
        context["target_id"] = target_id
    subject_id = _event_subject_id(source_event)
    if subject_id is not None:
        context["subject_id"] = subject_id
    return context


def _render(template: str, context: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            raise ValueError(
                f"Memory derivation template references unavailable variable '{key}'"
            )
        return context[key]

    return _TEMPLATE_TOKEN.sub(replace, template)


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
