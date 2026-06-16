from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import (
    CasePackage,
    EventType,
    MemoryDerivationRuleConfig,
    MemoryImpressionEffectConfig,
    MemoryLayer,
    MemoryOperation,
    MemoryScope,
    MemoryType,
    WorldEvent,
)

MEMORY_DERIVATION_TRIGGER_EVENTS = {
    EventType.PLAYER_ASKED_ABOUT.value,
    EventType.PLAYER_PRESENTED_CLUE.value,
    EventType.PLAYER_ACCUSED.value,
}
_TEMPLATE_TOKEN = re.compile(r"\{([^}]*)\}")


@dataclass(frozen=True)
class MemoryEffect:
    memory_id: str
    memory_type: MemoryType
    memory_scope: MemoryScope
    memory_layer: MemoryLayer
    operation: MemoryOperation
    subject_id: str
    owner_character_id: str | None
    visible_to_character_ids: list[str]
    content: str
    salience: float
    confidence: float
    source_event_ids: list[str]
    source_memory_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedMemoryEffect:
    rule_id: str
    effect: MemoryEffect


@dataclass(frozen=True)
class ResolvedImpressionEffect:
    rule_id: str
    impression: MemoryImpressionEffectConfig
    produced_memory_ids: tuple[str, ...]


def resolve_memory_derivation_effects(
    case: CasePackage,
    source_event: WorldEvent,
) -> list[ResolvedMemoryEffect]:
    context = _template_context(case, source_event)
    effects: list[ResolvedMemoryEffect] = []
    for rule in _matched_rules(case, source_event):
        for produced in rule.produces:
            salience = produced.salience
            if produced.salience_from_event is not None:
                salience = _float_context_value(
                    context,
                    produced.salience_from_event,
                    fallback=produced.salience,
                )
            if produced.min_salience is not None:
                salience = max(produced.min_salience, salience)
            salience = _clamp01(salience)
            effects.append(
                ResolvedMemoryEffect(
                    rule_id=produced.rule_id or rule.id,
                    effect=MemoryEffect(
                        memory_id=_render(produced.memory_id_pattern, context),
                        memory_type=produced.memory_type,
                        memory_scope=produced.memory_scope,
                        memory_layer=produced.memory_layer,
                        operation=produced.operation,
                        subject_id=_render(produced.subject_id, context),
                        owner_character_id=_render_optional(
                            produced.owner_character_id,
                            context,
                        ),
                        visible_to_character_ids=[
                            _render(item, context)
                            for item in produced.visible_to_character_ids
                        ],
                        content=_render(produced.content_pattern, context),
                        salience=salience,
                        confidence=produced.confidence,
                        source_event_ids=[
                            _render(item, context) for item in produced.source_event_ids
                        ],
                        source_memory_ids=[
                            _render(item, context)
                            for item in (
                                produced.source_memory_ids
                                if produced.source_memory_ids is not None
                                else [_source_memory_id_template(source_event)]
                            )
                            if item
                        ],
                        metadata=dict(produced.metadata),
                    ),
                )
            )
    return effects


def resolve_memory_impression_effects(
    case: CasePackage,
    source_event: WorldEvent,
) -> list[ResolvedImpressionEffect]:
    context = _template_context(case, source_event)
    resolved: list[ResolvedImpressionEffect] = []
    for rule in _matched_rules(case, source_event):
        if rule.impression is None:
            continue
        resolved.append(
            ResolvedImpressionEffect(
                rule_id=rule.id,
                impression=rule.impression,
                produced_memory_ids=tuple(
                    _render(produced.memory_id_pattern, context)
                    for produced in rule.produces
                ),
            )
        )
    return resolved


def memory_derivation_rule_ids_for_event(
    case: CasePackage,
    source_event: WorldEvent,
) -> set[str]:
    return {rule.id for rule in _matched_rules(case, source_event)}


def _matched_rules(
    case: CasePackage,
    source_event: WorldEvent,
) -> list[MemoryDerivationRuleConfig]:
    return [
        rule
        for rule in case.memory_derivation_rules
        if _rule_matches(rule, source_event)
    ]


def _rule_matches(rule: MemoryDerivationRuleConfig, source_event: WorldEvent) -> bool:
    if source_event.type.value != rule.trigger_type:
        return False
    target_id = rule.target_match_id
    if target_id is not None and source_event.payload.get("target_id") != target_id:
        return False
    subject_id = rule.subject_match_id
    if subject_id is not None and _event_subject_id(source_event) != subject_id:
        return False
    if rule.claim_id is not None and source_event.payload.get("claim_id") != rule.claim_id:
        return False
    return True


def _template_context(case: CasePackage, source_event: WorldEvent) -> dict[str, str]:
    context: dict[str, str] = {
        "source_event_id": source_event.id,
    }
    for key, value in source_event.payload.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            context[key] = str(value)

    target_id = _optional_str(source_event.payload.get("target_id"))
    if target_id is not None:
        context["target_id"] = target_id
        context["target_name"] = _character_name(case, target_id)

    subject_id = _event_subject_id(source_event)
    if subject_id is not None:
        context["subject_id"] = subject_id

    clue_id = _event_clue_id(source_event)
    if clue_id is not None:
        context["clue_id"] = clue_id
        context["clue_title"] = _clue_title(case, clue_id)

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


def _render_optional(template: str | None, context: dict[str, str]) -> str | None:
    if template is None:
        return None
    return _render(template, context)


def _event_subject_id(source_event: WorldEvent) -> str | None:
    if source_event.type == EventType.PLAYER_PRESENTED_CLUE:
        return _optional_str(source_event.payload.get("clue_id"))
    if source_event.type == EventType.PLAYER_ASKED_ABOUT:
        return _optional_str(source_event.payload.get("subject_id"))
    if source_event.type == EventType.PLAYER_ACCUSED:
        return _optional_str(source_event.payload.get("claim_id"))
    return None


def _event_clue_id(source_event: WorldEvent) -> str | None:
    if source_event.type == EventType.PLAYER_PRESENTED_CLUE:
        return _optional_str(source_event.payload.get("clue_id"))
    if (
        source_event.type == EventType.PLAYER_ASKED_ABOUT
        and source_event.payload.get("subject_type") == "clue"
    ):
        return _optional_str(source_event.payload.get("subject_id"))
    return None


def _source_memory_id_template(source_event: WorldEvent) -> str:
    if source_event.type == EventType.PLAYER_PRESENTED_CLUE:
        return "memory.player.presented_clue.{target_id}.{clue_id}"
    if source_event.type == EventType.PLAYER_ASKED_ABOUT:
        return "memory.player.asked_about.{target_id}.{subject_type}.{subject_id}"
    if source_event.type == EventType.PLAYER_ACCUSED:
        return "memory.player.accused.{target_id}.{claim_id}"
    return ""


def _character_name(case: CasePackage, character_id: str) -> str:
    return next(
        (item.display_name for item in case.characters if item.id == character_id),
        character_id,
    )


def _clue_title(case: CasePackage, clue_id: str) -> str:
    return next((item.title for item in case.clues if item.id == clue_id), clue_id)


def _float_context_value(
    context: dict[str, str],
    key: str,
    *,
    fallback: float,
) -> float:
    try:
        return float(context[key])
    except (KeyError, TypeError, ValueError):
        return fallback


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _clamp01(value: float) -> float:
    return round(min(max(value, 0.0), 1.0), 4)
