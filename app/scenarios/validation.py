from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml
from pydantic import ValidationError

from app.cases.loader import CaseLoader
from app.domain.models import ActionType, CasePackage, EventType, PlayerAction, SubjectType


class ScenarioValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ScenarioPackage:
    case_dir: Path
    scenario_path: Path
    case: CasePackage
    raw: Mapping[str, object]

    @property
    def case_id(self) -> str:
        return self.case.meta.id


_SCENARIO_FIELDS = frozenset(
    {
        "case_id",
        "expected_final_phase",
        "expected_final_beats",
        "expected_final_player_world_info_ids",
        "forbidden_public_terms",
        "steps",
        "reconstruction",
    }
)
_STEP_FIELDS = frozenset(
    {
        "name",
        "label",
        "action",
        "expected_events",
        "expected_phase",
        "expected_player_world_info_ids",
        "accepted",
        "director_blocked",
        "expected_new_awareness",
        "expected_block",
    }
)
_AWARENESS_FIELDS = frozenset({"character_id", "world_info_id"})
_EXPECTED_BLOCK_FIELDS = frozenset(
    {
        "target_id",
        "blocked_fact_id",
        "world_info_id",
        "matched_by",
        "matched_text",
        "safe_fallback_used",
    }
)
_RECONSTRUCTION_FIELDS = frozenset({"overview", "runtime_note", "director_note", "facts"})


def discover_standard_scenarios(cases_root: Path) -> list[Path]:
    if cases_root.is_dir() and (cases_root / "case.yaml").exists():
        scenario_path = cases_root / "scenarios" / "standard_path.yaml"
        return [scenario_path] if scenario_path.exists() else []
    if not cases_root.exists():
        raise ScenarioValidationError(f"Cases root does not exist: {cases_root}")
    return sorted(cases_root.glob("*/scenarios/standard_path.yaml"))


def load_scenario_package(scenario_path: Path) -> ScenarioPackage:
    raw = read_scenario_yaml(scenario_path)
    case_id = _expect_str(raw.get("case_id"), "case_id")
    expected_case_dir = scenario_path.parents[1]
    if expected_case_dir.name != case_id:
        raise ScenarioValidationError(
            f"{scenario_path} case_id '{case_id}' does not match case directory "
            f"'{expected_case_dir.name}'"
        )
    case = CaseLoader().load(expected_case_dir)
    if case.meta.id != case_id:
        raise ScenarioValidationError(
            f"{scenario_path} case_id '{case_id}' does not match case meta id "
            f"'{case.meta.id}'"
        )
    return ScenarioPackage(
        case_dir=expected_case_dir,
        scenario_path=scenario_path,
        case=case,
        raw=raw,
    )


def read_scenario_yaml(path: Path) -> Mapping[str, object]:
    if not path.exists():
        raise ScenarioValidationError(f"Scenario YAML does not exist: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as exc:
        raise ScenarioValidationError(f"Invalid scenario YAML in {path}: {exc}") from exc
    if loaded is None:
        raise ScenarioValidationError(f"Scenario YAML is empty: {path}")
    return _expect_mapping(loaded, f"scenario file {path}")


def validate_standard_scenarios(cases_root: Path) -> list[str]:
    scenario_paths = discover_standard_scenarios(cases_root)
    if not scenario_paths:
        raise ScenarioValidationError(f"No standard scenario files found under {cases_root}")
    validated: list[str] = []
    for scenario_path in scenario_paths:
        package = load_scenario_package(scenario_path)
        validate_scenario_package(package)
        validated.append(package.case_id)
    return validated


def validate_scenario_package(package: ScenarioPackage) -> None:
    raw = package.raw
    scenario_path = package.scenario_path
    case = package.case
    _reject_unknown_fields(raw, _SCENARIO_FIELDS, f"scenario file {scenario_path}")
    _require_fields(
        raw,
        {
            "case_id",
            "expected_final_phase",
            "expected_final_beats",
            "expected_final_player_world_info_ids",
            "forbidden_public_terms",
            "steps",
        },
        f"scenario file {scenario_path}",
    )

    phase_ids = {phase.id for phase in case.narrative_rules.phases}
    beat_ids = {beat.id for beat in case.narrative_rules.beats}
    world_info_ids = {world_info.id for world_info in case.world_info}
    character_ids = {character.id for character in case.characters}
    clue_ids = {clue.id for clue in case.clues}
    scene_ids = {scene.id for scene in case.scenes}
    hotspot_ids = {hotspot.id for scene in case.scenes for hotspot in scene.hotspots}
    claim_ids = {claim.id for claim in case.solution_claims.claims}
    forbidden_fact_ids = {fact.id for fact in case.forbidden_facts}

    _ensure_known(
        phase_ids,
        [_expect_str(raw["expected_final_phase"], "expected_final_phase")],
        "expected_final_phase",
    )
    _ensure_known(
        beat_ids,
        _expect_string_list(raw["expected_final_beats"], "expected_final_beats"),
        "expected_final_beats",
    )
    _ensure_known(
        world_info_ids,
        _expect_string_list(
            raw["expected_final_player_world_info_ids"],
            "expected_final_player_world_info_ids",
        ),
        "expected_final_player_world_info_ids",
    )
    _expect_string_list(raw["forbidden_public_terms"], "forbidden_public_terms")
    _validate_reconstruction(raw.get("reconstruction"), "reconstruction")

    for index, raw_step in enumerate(_expect_sequence(raw["steps"], "steps")):
        context = f"steps[{index}]"
        step = _expect_mapping(raw_step, context)
        _validate_step(
            step,
            context=context,
            phase_ids=phase_ids,
            world_info_ids=world_info_ids,
            character_ids=character_ids,
            clue_ids=clue_ids,
            scene_ids=scene_ids,
            hotspot_ids=hotspot_ids,
            claim_ids=claim_ids,
            forbidden_fact_ids=forbidden_fact_ids,
        )


def _validate_step(
    step: Mapping[str, object],
    *,
    context: str,
    phase_ids: set[str],
    world_info_ids: set[str],
    character_ids: set[str],
    clue_ids: set[str],
    scene_ids: set[str],
    hotspot_ids: set[str],
    claim_ids: set[str],
    forbidden_fact_ids: set[str],
) -> None:
    _reject_unknown_fields(step, _STEP_FIELDS, context)
    _require_fields(
        step,
        {
            "name",
            "action",
            "expected_events",
            "expected_phase",
            "expected_player_world_info_ids",
        },
        context,
    )
    _expect_str(step["name"], f"{context}.name")
    if "label" in step:
        _expect_str(step["label"], f"{context}.label")
    _ensure_known(
        phase_ids,
        [_expect_str(step["expected_phase"], f"{context}.expected_phase")],
        f"{context}.expected_phase",
    )
    _ensure_known(
        world_info_ids,
        _expect_string_list(
            step["expected_player_world_info_ids"],
            f"{context}.expected_player_world_info_ids",
        ),
        f"{context}.expected_player_world_info_ids",
    )
    for event_index, raw_event_type in enumerate(
        _expect_sequence(step["expected_events"], f"{context}.expected_events")
    ):
        _build_event_type(raw_event_type, f"{context}.expected_events[{event_index}]")
    if "accepted" in step:
        _expect_bool(step["accepted"], f"{context}.accepted")
    if "director_blocked" in step:
        _expect_bool(step["director_blocked"], f"{context}.director_blocked")
    _validate_player_action(
        step["action"],
        context=f"{context}.action",
        character_ids=character_ids,
        clue_ids=clue_ids,
        scene_ids=scene_ids,
        hotspot_ids=hotspot_ids,
        claim_ids=claim_ids,
    )
    _validate_expected_awareness(
        step.get("expected_new_awareness", []),
        context=f"{context}.expected_new_awareness",
        character_ids=character_ids,
        world_info_ids=world_info_ids,
    )
    _validate_expected_block(
        step.get("expected_block"),
        context=f"{context}.expected_block",
        character_ids=character_ids,
        world_info_ids=world_info_ids,
        forbidden_fact_ids=forbidden_fact_ids,
    )


def _validate_player_action(
    value: object,
    *,
    context: str,
    character_ids: set[str],
    clue_ids: set[str],
    scene_ids: set[str],
    hotspot_ids: set[str],
    claim_ids: set[str],
) -> None:
    raw_action = _expect_mapping(value, context)
    try:
        action = PlayerAction.model_validate(dict(raw_action))
    except ValidationError as exc:
        raise ScenarioValidationError(f"Invalid PlayerAction at {context}: {exc}") from exc

    if action.type == ActionType.INSPECT:
        _ensure_known(hotspot_ids, [action.target_id], f"{context}.target_id")
    elif action.type in {ActionType.TALK, ActionType.ASK_ABOUT, ActionType.PRESENT_CLUE}:
        _ensure_known(character_ids, [action.target_id], f"{context}.target_id")
    elif action.type == ActionType.ACCUSE:
        _ensure_known(character_ids, [action.target_id], f"{context}.target_id")
        _ensure_known(claim_ids, [str(action.claim_id)], f"{context}.claim_id")

    if action.clue_id is not None:
        _ensure_known(clue_ids, [action.clue_id], f"{context}.clue_id")
    _ensure_known(clue_ids, action.evidence_clue_ids, f"{context}.evidence_clue_ids")
    if action.subject_type == SubjectType.CLUE:
        _ensure_known(clue_ids, [str(action.subject_id)], f"{context}.subject_id")
    elif action.subject_type == SubjectType.CHARACTER:
        _ensure_known(character_ids, [str(action.subject_id)], f"{context}.subject_id")
    elif action.subject_type == SubjectType.SCENE:
        _ensure_known(scene_ids, [str(action.subject_id)], f"{context}.subject_id")


def _validate_expected_awareness(
    value: object,
    *,
    context: str,
    character_ids: set[str],
    world_info_ids: set[str],
) -> None:
    for index, raw_item in enumerate(_expect_sequence(value, context)):
        item_context = f"{context}[{index}]"
        item = _expect_mapping(raw_item, item_context)
        _reject_unknown_fields(item, _AWARENESS_FIELDS, item_context)
        _require_fields(item, _AWARENESS_FIELDS, item_context)
        _ensure_known(
            character_ids,
            [_expect_str(item["character_id"], f"{item_context}.character_id")],
            f"{item_context}.character_id",
        )
        _ensure_known(
            world_info_ids,
            [_expect_str(item["world_info_id"], f"{item_context}.world_info_id")],
            f"{item_context}.world_info_id",
        )


def _validate_expected_block(
    value: object,
    *,
    context: str,
    character_ids: set[str],
    world_info_ids: set[str],
    forbidden_fact_ids: set[str],
) -> None:
    if value is None:
        return
    block = _expect_mapping(value, context)
    _reject_unknown_fields(block, _EXPECTED_BLOCK_FIELDS, context)
    _require_fields(block, {"target_id", "blocked_fact_id", "world_info_id"}, context)
    _ensure_known(
        character_ids,
        [_expect_str(block["target_id"], f"{context}.target_id")],
        f"{context}.target_id",
    )
    _ensure_known(
        forbidden_fact_ids,
        [_expect_str(block["blocked_fact_id"], f"{context}.blocked_fact_id")],
        f"{context}.blocked_fact_id",
    )
    _ensure_known(
        world_info_ids,
        [_expect_str(block["world_info_id"], f"{context}.world_info_id")],
        f"{context}.world_info_id",
    )
    if "matched_by" in block:
        _expect_str(block["matched_by"], f"{context}.matched_by")
    if "matched_text" in block:
        matched_text = _expect_str(block["matched_text"], f"{context}.matched_text")
        if matched_text != "[redacted]":
            raise ScenarioValidationError(f"{context}.matched_text must be '[redacted]'")
    if "safe_fallback_used" in block:
        _expect_bool(block["safe_fallback_used"], f"{context}.safe_fallback_used")


def _validate_reconstruction(value: object, context: str) -> None:
    if value is None:
        return
    reconstruction = _expect_mapping(value, context)
    _reject_unknown_fields(reconstruction, _RECONSTRUCTION_FIELDS, context)
    for key in _RECONSTRUCTION_FIELDS:
        if key in reconstruction:
            _expect_text_block(reconstruction[key], f"{context}.{key}")


def _build_event_type(value: object, context: str) -> EventType:
    event_type = _expect_str(value, context)
    try:
        return EventType(event_type)
    except ValueError as exc:
        valid_values = ", ".join(event.value for event in EventType)
        raise ScenarioValidationError(
            f"Unknown EventType at {context}: {event_type!r}. Valid values: {valid_values}"
        ) from exc


def _expect_mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ScenarioValidationError(f"{context} must be a mapping")
    for key in value:
        if not isinstance(key, str):
            raise ScenarioValidationError(f"{context} has a non-string key: {key!r}")
    return cast(Mapping[str, object], value)


def _expect_sequence(value: object, context: str) -> Sequence[object]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ScenarioValidationError(f"{context} must be a list")
    return cast(Sequence[object], value)


def _expect_str(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ScenarioValidationError(f"{context} must be a non-empty string")
    return value


def _expect_bool(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        raise ScenarioValidationError(f"{context} must be a boolean")
    return value


def _expect_string_list(value: object, context: str) -> list[str]:
    return [
        _expect_str(item, f"{context}[{index}]")
        for index, item in enumerate(_expect_sequence(value, context))
    ]


def _expect_text_block(value: object, context: str) -> None:
    if isinstance(value, str):
        return
    if isinstance(value, Sequence) and not isinstance(value, str):
        for index, item in enumerate(value):
            _expect_str(item, f"{context}[{index}]")
        return
    raise ScenarioValidationError(f"{context} must be a string or list of strings")


def _reject_unknown_fields(
    value: Mapping[str, object],
    allowed_fields: frozenset[str],
    context: str,
) -> None:
    unknown_fields = sorted(set(value) - allowed_fields)
    if unknown_fields:
        raise ScenarioValidationError(f"{context} has unknown fields: {unknown_fields}")


def _require_fields(
    value: Mapping[str, object],
    required_fields: set[str] | frozenset[str],
    context: str,
) -> None:
    missing_fields = sorted(required_fields - set(value))
    if missing_fields:
        raise ScenarioValidationError(f"{context} is missing required fields: {missing_fields}")


def _ensure_known(known_ids: set[str], referenced_ids: Sequence[str], label: str) -> None:
    unknown_ids = sorted(set(referenced_ids) - known_ids)
    if unknown_ids:
        raise ScenarioValidationError(f"{label} references unknown ids: {unknown_ids}")
