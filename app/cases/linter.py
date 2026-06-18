from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.cases.errors import CaseLoadError
from app.cases.loader import CaseLoader
from app.domain.models import (
    BacktrackClueUnlockConfig,
    CasePackage,
    EventType,
    NpcSkillConfig,
    ProposedActionType,
    SceneHotspotConfig,
    WorldInfoConfig,
    WorldInfoSensitivity,
)
from app.scenarios.validation import (
    ScenarioValidationError,
    discover_scenarios,
    validate_scenario_package,
)

PRODUCTION_CASE_ID = "mist_clock_manor"


@dataclass(frozen=True)
class CaseLintViolation:
    code: str
    path: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class CaseLintReport:
    case_id: str
    case_dir: str
    passed: bool
    violations: list[CaseLintViolation] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "case_dir": self.case_dir,
            "passed": self.passed,
            "violation_count": len(self.violations),
            "violations": [violation.to_dict() for violation in self.violations],
        }

    def to_markdown(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [
            f"# Case Authoring Lint: {self.case_id}",
            "",
            f"- case_dir: `{self.case_dir}`",
            f"- status: `{status}`",
            f"- violations: `{len(self.violations)}`",
        ]
        if not self.violations:
            return "\n".join(lines) + "\n"
        lines.extend(["", "| Severity | Code | Path | Message |", "| --- | --- | --- | --- |"])
        for violation in self.violations:
            lines.append(
                "| "
                f"{_escape_markdown_table(violation.severity)} | "
                f"{_escape_markdown_table(violation.code)} | "
                f"`{_escape_markdown_table(violation.path)}` | "
                f"{_escape_markdown_table(violation.message)} |"
            )
        return "\n".join(lines) + "\n"


def lint_production_case(case_dir: Path, *, case_id: str = PRODUCTION_CASE_ID) -> CaseLintReport:
    """Run production authoring lint for the single supported case package."""

    violations: list[CaseLintViolation] = []
    if case_id != PRODUCTION_CASE_ID:
        violations.append(
            CaseLintViolation(
                code="linter.unsupported_case",
                path="--case",
                message=(
                    "case authoring linter is intentionally scoped to "
                    f"{PRODUCTION_CASE_ID}, got {case_id}"
                ),
            )
        )
        return CaseLintReport(
            case_id=case_id,
            case_dir=str(case_dir),
            passed=False,
            violations=violations,
        )

    if case_dir.name != case_id:
        violations.append(
            CaseLintViolation(
                code="case.directory_mismatch",
                path=str(case_dir),
                message=f"case directory name must be {case_id}",
            )
        )

    try:
        raw_case = _RawCase.load(case_dir)
    except CaseLoadError as exc:
        violations.append(
            CaseLintViolation(
                code="loader.schema_or_reference",
                path=str(case_dir),
                message=str(exc),
            )
        )
        return CaseLintReport(
            case_id=case_id,
            case_dir=str(case_dir),
            passed=False,
            violations=violations,
        )

    try:
        package = CaseLoader().load(case_dir)
    except CaseLoadError as exc:
        violations.append(
            CaseLintViolation(
                code="loader.schema_or_reference",
                path=str(case_dir),
                message=str(exc),
            )
        )
        violations.extend(
            _MistClockManorRawLinter(raw_case=raw_case, case_dir=case_dir).run()
        )
        return CaseLintReport(
            case_id=case_id,
            case_dir=str(case_dir),
            passed=False,
            violations=violations,
        )

    if package.meta.id != case_id:
        violations.append(
            CaseLintViolation(
                code="case.id_mismatch",
                path="case.yaml:id",
                message=f"case meta id must be {case_id}, got {package.meta.id}",
            )
        )

    checker = _MistClockManorLinter(package=package, raw_case=raw_case, case_dir=case_dir)
    violations.extend(checker.run())

    return CaseLintReport(
        case_id=case_id,
        case_dir=str(case_dir),
        passed=not violations,
        violations=violations,
    )


@dataclass(frozen=True)
class _RawCase:
    world_info: list[Mapping[str, object]]
    clues: list[Mapping[str, object]]
    scenes: list[Mapping[str, object]]
    npc_skills: list[Mapping[str, object]]
    memory_derivation_rules: list[Mapping[str, object]]
    narrative_rules: Mapping[str, object]
    forbidden_facts: list[Mapping[str, object]]
    scenarios: dict[str, Mapping[str, object]]

    @classmethod
    def load(cls, case_dir: Path) -> _RawCase:
        return cls(
            world_info=_read_yaml_list(case_dir / "world_info.yaml"),
            clues=_read_yaml_list(case_dir / "clues.yaml"),
            scenes=_read_yaml_list(case_dir / "scenes.yaml"),
            npc_skills=_read_yaml_list(case_dir / "npc_skills.yaml"),
            memory_derivation_rules=_read_yaml_list(
                case_dir / "memory_derivation_rules.yaml"
            ),
            narrative_rules=_read_yaml_mapping(case_dir / "narrative_rules.yaml"),
            forbidden_facts=_read_yaml_list(case_dir / "forbidden_facts.yaml"),
            scenarios={
                path.name: _read_yaml_mapping(path)
                for path in discover_scenarios(case_dir, pattern="*.yaml")
            },
        )


@dataclass(frozen=True)
class _MistClockManorLinter:
    package: CasePackage
    raw_case: _RawCase
    case_dir: Path

    def run(self) -> list[CaseLintViolation]:
        violations: list[CaseLintViolation] = []
        violations.extend(self._validate_scenarios_with_existing_contract())
        violations.extend(self._validate_high_sensitivity_world_info())
        violations.extend(self._validate_optional_clues_off_core_path())
        violations.extend(self._validate_backtrack_unlocks())
        violations.extend(self._validate_npc_skill_relationship_delta_caps())
        violations.extend(self._validate_memory_rule_authority())
        violations.extend(self._validate_forbidden_terms_not_public())
        return violations

    def _validate_scenarios_with_existing_contract(self) -> list[CaseLintViolation]:
        violations: list[CaseLintViolation] = []
        for scenario_path in discover_scenarios(self.case_dir, pattern="*.yaml"):
            try:
                validate_scenario_package(
                    _ScenarioLintPackage(
                        case_dir=self.case_dir,
                        scenario_path=scenario_path,
                        case=self.package,
                        raw=_read_yaml_mapping(scenario_path),
                    )
                )
            except ScenarioValidationError as exc:
                violations.append(
                    CaseLintViolation(
                        code="scenario.contract",
                        path=_relpath(scenario_path),
                        message=str(exc),
                    )
                )
        return violations

    def _validate_high_sensitivity_world_info(self) -> list[CaseLintViolation]:
        violations: list[CaseLintViolation] = []
        player_facing_world_info_ids = _player_facing_world_info_ids(
            self.package,
            self.raw_case,
        )
        for index, world_info in enumerate(self.package.world_info):
            if world_info.sensitivity != WorldInfoSensitivity.HIGH:
                continue
            if world_info.id not in player_facing_world_info_ids:
                continue
            path = f"world_info.yaml[{index}]({world_info.id})"
            safe_fragments = world_info.claim_graph.safe_fragments
            if not safe_fragments:
                violations.append(
                    CaseLintViolation(
                        code="world_info.high_sensitivity.safe_fragment_missing",
                        path=path,
                        message="high-sensitivity world_info must define safe fragments",
                    )
                )
                continue
            for fragment in safe_fragments:
                if not _has_unlock_conditions(fragment.unlock_conditions):
                    violations.append(
                        CaseLintViolation(
                            code="world_info.high_sensitivity.unlock_missing",
                            path=f"{path}.claim_graph.safe_fragments({fragment.id})",
                            message=(
                                "high-sensitivity safe fragment must have explicit "
                                "unlock conditions"
                            ),
                        )
                    )
        return violations

    def _validate_optional_clues_off_core_path(self) -> list[CaseLintViolation]:
        violations: list[CaseLintViolation] = []
        optional_clue_ids = {clue.id for clue in self.package.clues if not clue.key}
        if not optional_clue_ids:
            return []

        for beat in self.package.narrative_rules.beats:
            leaked = sorted(set(beat.all_discovered) & optional_clue_ids)
            if leaked:
                violations.append(
                    CaseLintViolation(
                        code="optional_clue.core_beat",
                        path=f"narrative_rules.yaml:beats({beat.id}).all_discovered",
                        message=(
                            "optional thickness clues must not gate core narrative beats: "
                            f"{leaked}"
                        ),
                    )
                )

        standard = self.raw_case.scenarios.get("standard_path.yaml")
        if standard is not None:
            expected_final = _string_set(standard.get("expected_final_player_world_info_ids"))
            optional_world_info_ids = {
                world_info_id
                for clue in self.package.clues
                if not clue.key
                for world_info_id in clue.reveals_world_info
            }
            leaked_world_info = sorted(expected_final & optional_world_info_ids)
            if leaked_world_info:
                violations.append(
                    CaseLintViolation(
                        code="optional_world_info.standard_path",
                        path=(
                            "scenarios/standard_path.yaml:"
                            "expected_final_player_world_info_ids"
                        ),
                        message=(
                            "optional clue world_info must not be required by standard "
                            f"path expectations: {leaked_world_info}"
                        ),
                    )
                )

        for claim in self.package.solution_claims.claims:
            if claim.result != "correct":
                continue
            leaked = sorted(set(claim.required_evidence) & optional_clue_ids)
            if leaked:
                violations.append(
                    CaseLintViolation(
                        code="optional_clue.solution_claim",
                        path=f"solution_claims.yaml:claims({claim.id}).required_evidence",
                        message=(
                            "optional thickness clues must not be required evidence for "
                            f"the production correct claim: {leaked}"
                        ),
                    )
                )
        return violations

    def _validate_backtrack_unlocks(self) -> list[CaseLintViolation]:
        violations: list[CaseLintViolation] = []
        all_direct_clue_ids = {
            clue_id
            for scene in self.package.scenes
            for hotspot in scene.hotspots
            for clue_id in hotspot.discover_clues
        }
        reachable_hotspot_ids = {
            hotspot.id for scene in self.package.scenes for hotspot in scene.hotspots
        }
        reachable_beat_ids = _reachable_beat_ids(self.package)
        reachable_clue_ids = set(all_direct_clue_ids)

        for scene in self.package.scenes:
            for hotspot in scene.hotspots:
                for unlock in hotspot.backtrack_unlocks:
                    path = (
                        f"scenes.yaml:hotspots({hotspot.id})."
                        f"backtrack_unlocks({unlock.id})"
                    )
                    if set(unlock.clue_ids) & all_direct_clue_ids:
                        violations.append(
                            CaseLintViolation(
                                code="backtrack.direct_duplicate",
                                path=f"{path}.clue_ids",
                                message=(
                                    "backtrack_unlocks must not re-unlock clues already "
                                    "available through first-pass hotspot discovery"
                                ),
                            )
                        )

                    if not _blocks_first_inspection(hotspot, unlock):
                        violations.append(
                            CaseLintViolation(
                                code="backtrack.first_inspection_unlock",
                                path=f"{path}.conditions",
                                message=(
                                    "backtrack unlock must require a prior inspection of "
                                    "the same hotspot and min_prior_inspections >= 1"
                                ),
                            )
                        )

                    missing_clues = sorted(set(unlock.conditions.discovered_clues) - reachable_clue_ids)
                    missing_beats = sorted(set(unlock.conditions.completed_beats) - reachable_beat_ids)
                    missing_hotspots = sorted(
                        set(unlock.conditions.prior_inspected_hotspots)
                        - reachable_hotspot_ids
                    )
                    if missing_clues or missing_beats or missing_hotspots:
                        violations.append(
                            CaseLintViolation(
                                code="backtrack.unreachable_conditions",
                                path=f"{path}.conditions",
                                message=(
                                    "backtrack unlock conditions are not reachable from "
                                    "current production case; "
                                    f"clues={missing_clues}, beats={missing_beats}, "
                                    f"hotspots={missing_hotspots}"
                                ),
                            )
                        )
                    reachable_clue_ids.update(unlock.clue_ids)
        return violations

    def _validate_npc_skill_relationship_delta_caps(self) -> list[CaseLintViolation]:
        violations: list[CaseLintViolation] = []
        for skill in self.package.npc_skills:
            if not _allows_relationship_change(skill):
                continue
            if not skill.proposed_action_policy.max_relationship_delta:
                violations.append(
                    CaseLintViolation(
                        code="npc_skill.relationship_delta_cap_missing",
                        path=f"npc_skills.yaml({skill.id}).proposed_action_policy",
                        message=(
                            "NPC skill allowing relationship.change must define "
                            "max_relationship_delta"
                        ),
                    )
                )
        return violations

    def _validate_memory_rule_authority(self) -> list[CaseLintViolation]:
        violations: list[CaseLintViolation] = []
        for rule_index, rule in enumerate(self.package.memory_derivation_rules):
            for effect_index, effect in enumerate(rule.produces):
                path = (
                    "memory_derivation_rules.yaml"
                    f"[{rule_index}]({rule.id}).produces[{effect_index}]"
                )
                if not effect.source_event_ids:
                    violations.append(
                        CaseLintViolation(
                            code="memory_rule.source_event_ids_missing",
                            path=path,
                            message="memory rule effect must declare source_event_ids",
                        )
                    )

                has_authority = bool(effect.metadata.get("authority_source"))
                has_non_authoritative = effect.metadata.get("non_authoritative") is True
                authority_required = (
                    effect.memory_type in {"belief", "relationship", "strategy"}
                    or not effect.source_event_ids
                )
                if authority_required and has_authority == has_non_authoritative:
                    violations.append(
                        CaseLintViolation(
                            code="memory_rule.authority_missing",
                            path=f"{path}.metadata",
                            message=(
                                "memory rule effect must mark exactly one of "
                                "authority_source or non_authoritative"
                            ),
                        )
                    )
        return violations

    def _validate_forbidden_terms_not_public(self) -> list[CaseLintViolation]:
        violations: list[CaseLintViolation] = []
        public_fields = [
            *(
                (
                    f"clues.yaml({clue.id}).title",
                    clue.title,
                )
                for clue in self.package.clues
            ),
            *(
                (
                    f"clues.yaml({clue.id}).description",
                    clue.description,
                )
                for clue in self.package.clues
            ),
            *(
                (
                    f"world_info.yaml({world_info.id}).title",
                    world_info.title,
                )
                for world_info in self.package.world_info
            ),
            *(
                (
                    f"world_info.yaml({world_info.id}).description",
                    world_info.description,
                )
                for world_info in self.package.world_info
            ),
        ]
        for fact in self.package.forbidden_facts:
            for term in fact.blocked_terms:
                normalized_term = _normalize_public_text(term)
                if not normalized_term:
                    continue
                for path, value in public_fields:
                    if normalized_term == _normalize_public_text(value):
                        violations.append(
                            CaseLintViolation(
                                code="forbidden_term.public_exact_match",
                                path=path,
                                message=(
                                    f"public field exactly matches forbidden fact "
                                    f"'{fact.id}' blocked term"
                                ),
                            )
                        )
        return violations


@dataclass(frozen=True)
class _MistClockManorRawLinter:
    raw_case: _RawCase
    case_dir: Path

    def run(self) -> list[CaseLintViolation]:
        violations: list[CaseLintViolation] = []
        violations.extend(self._validate_high_sensitivity_world_info())
        violations.extend(self._validate_optional_clues_off_core_path())
        violations.extend(self._validate_backtrack_unlocks())
        violations.extend(self._validate_npc_skill_relationship_delta_caps())
        violations.extend(self._validate_memory_rule_authority())
        violations.extend(self._validate_forbidden_terms_not_public())
        return violations

    def _validate_high_sensitivity_world_info(self) -> list[CaseLintViolation]:
        violations: list[CaseLintViolation] = []
        player_facing_world_info_ids = _raw_player_facing_world_info_ids(self.raw_case)
        for index, world_info in enumerate(self.raw_case.world_info):
            world_info_id = _mapping_str(world_info, "id")
            if _mapping_str(world_info, "sensitivity") != "high":
                continue
            if world_info_id not in player_facing_world_info_ids:
                continue
            path = f"world_info.yaml[{index}]({world_info_id})"
            safe_fragments = _raw_safe_fragments(world_info)
            if not safe_fragments:
                violations.append(
                    CaseLintViolation(
                        code="world_info.high_sensitivity.safe_fragment_missing",
                        path=path,
                        message="high-sensitivity world_info must define safe fragments",
                    )
                )
                continue
            for fragment in safe_fragments:
                if not _raw_has_unlock_conditions(fragment.get("unlock_conditions")):
                    violations.append(
                        CaseLintViolation(
                            code="world_info.high_sensitivity.unlock_missing",
                            path=(
                                f"{path}.claim_graph.safe_fragments"
                                f"({_mapping_str(fragment, 'id')})"
                            ),
                            message=(
                                "high-sensitivity safe fragment must have explicit "
                                "unlock conditions"
                            ),
                        )
                    )
        return violations

    def _validate_optional_clues_off_core_path(self) -> list[CaseLintViolation]:
        violations: list[CaseLintViolation] = []
        optional_clue_ids = {
            clue_id
            for clue in self.raw_case.clues
            if (clue_id := _mapping_str(clue, "id")) and clue.get("key") is not True
        }
        for beat in _as_mapping_sequence(self.raw_case.narrative_rules.get("beats")):
            leaked = sorted(_string_set(beat.get("all_discovered")) & optional_clue_ids)
            if leaked:
                violations.append(
                    CaseLintViolation(
                        code="optional_clue.core_beat",
                        path=(
                            "narrative_rules.yaml:beats"
                            f"({_mapping_str(beat, 'id')}).all_discovered"
                        ),
                        message=(
                            "optional thickness clues must not gate core narrative beats: "
                            f"{leaked}"
                        ),
                    )
                )

        standard = self.raw_case.scenarios.get("standard_path.yaml")
        if standard is not None:
            expected_final = _string_set(standard.get("expected_final_player_world_info_ids"))
            optional_world_info_ids = {
                world_info_id
                for clue in self.raw_case.clues
                if clue.get("key") is not True
                for world_info_id in _string_set(clue.get("reveals_world_info"))
            }
            leaked_world_info = sorted(expected_final & optional_world_info_ids)
            if leaked_world_info:
                violations.append(
                    CaseLintViolation(
                        code="optional_world_info.standard_path",
                        path=(
                            "scenarios/standard_path.yaml:"
                            "expected_final_player_world_info_ids"
                        ),
                        message=(
                            "optional clue world_info must not be required by standard "
                            f"path expectations: {leaked_world_info}"
                        ),
                    )
                )
        return violations

    def _validate_backtrack_unlocks(self) -> list[CaseLintViolation]:
        violations: list[CaseLintViolation] = []
        reachable_hotspot_ids = {
            hotspot_id
            for hotspot in _raw_hotspots(self.raw_case.scenes)
            if (hotspot_id := _mapping_str(hotspot, "id"))
        }
        direct_clue_ids = {
            clue_id
            for hotspot in _raw_hotspots(self.raw_case.scenes)
            for clue_id in _string_set(hotspot.get("discover_clues"))
        }
        reachable_clue_ids = set(direct_clue_ids)
        reachable_beat_ids = {
            beat_id
            for beat in _as_mapping_sequence(self.raw_case.narrative_rules.get("beats"))
            if (beat_id := _mapping_str(beat, "id"))
        }

        for hotspot in _raw_hotspots(self.raw_case.scenes):
            hotspot_id = _mapping_str(hotspot, "id")
            for unlock in _as_mapping_sequence(hotspot.get("backtrack_unlocks")):
                unlock_id = _mapping_str(unlock, "id")
                path = (
                    f"scenes.yaml:hotspots({hotspot_id})."
                    f"backtrack_unlocks({unlock_id})"
                )
                unlock_clue_ids = _string_set(unlock.get("clue_ids"))
                if unlock_clue_ids & direct_clue_ids:
                    violations.append(
                        CaseLintViolation(
                            code="backtrack.direct_duplicate",
                            path=f"{path}.clue_ids",
                            message=(
                                "backtrack_unlocks must not re-unlock clues already "
                                "available through first-pass hotspot discovery"
                            ),
                        )
                    )
                conditions = _as_mapping(unlock.get("conditions"))
                prior_hotspot_ids = _string_set(conditions.get("prior_inspected_hotspots"))
                min_prior_inspections = _non_negative_int(
                    conditions.get("min_prior_inspections")
                )
                if hotspot_id not in prior_hotspot_ids or min_prior_inspections < 1:
                    violations.append(
                        CaseLintViolation(
                            code="backtrack.first_inspection_unlock",
                            path=f"{path}.conditions",
                            message=(
                                "backtrack unlock must require a prior inspection of "
                                "the same hotspot and min_prior_inspections >= 1"
                            ),
                        )
                    )

                missing_clues = sorted(
                    _string_set(conditions.get("discovered_clues")) - reachable_clue_ids
                )
                missing_beats = sorted(
                    _string_set(conditions.get("completed_beats")) - reachable_beat_ids
                )
                missing_hotspots = sorted(prior_hotspot_ids - reachable_hotspot_ids)
                if missing_clues or missing_beats or missing_hotspots:
                    violations.append(
                        CaseLintViolation(
                            code="backtrack.unreachable_conditions",
                            path=f"{path}.conditions",
                            message=(
                                "backtrack unlock conditions are not reachable from "
                                "current production case; "
                                f"clues={missing_clues}, beats={missing_beats}, "
                                f"hotspots={missing_hotspots}"
                            ),
                        )
                    )
                reachable_clue_ids.update(unlock_clue_ids)
        return violations

    def _validate_npc_skill_relationship_delta_caps(self) -> list[CaseLintViolation]:
        violations: list[CaseLintViolation] = []
        for skill in self.raw_case.npc_skills:
            policy = _as_mapping(skill.get("proposed_action_policy"))
            if "relationship.change" not in _string_set(policy.get("allowed")):
                continue
            if not _as_mapping(policy.get("max_relationship_delta")):
                violations.append(
                    CaseLintViolation(
                        code="npc_skill.relationship_delta_cap_missing",
                        path=(
                            f"npc_skills.yaml({_mapping_str(skill, 'id')})."
                            "proposed_action_policy"
                        ),
                        message=(
                            "NPC skill allowing relationship.change must define "
                            "max_relationship_delta"
                        ),
                    )
                )
        return violations

    def _validate_memory_rule_authority(self) -> list[CaseLintViolation]:
        violations: list[CaseLintViolation] = []
        for rule_index, rule in enumerate(self.raw_case.memory_derivation_rules):
            for effect_index, effect in enumerate(_as_mapping_sequence(rule.get("produces"))):
                path = (
                    "memory_derivation_rules.yaml"
                    f"[{rule_index}]({_mapping_str(rule, 'id')}).produces[{effect_index}]"
                )
                source_event_ids = _string_set(effect.get("source_event_ids"))
                if not source_event_ids:
                    violations.append(
                        CaseLintViolation(
                            code="memory_rule.source_event_ids_missing",
                            path=path,
                            message="memory rule effect must declare source_event_ids",
                        )
                    )
                metadata = _as_mapping(effect.get("metadata"))
                has_authority = bool(_mapping_str(metadata, "authority_source"))
                has_non_authoritative = metadata.get("non_authoritative") is True
                memory_type = _mapping_str(effect, "memory_type") or "episodic"
                authority_required = (
                    memory_type in {"belief", "relationship", "strategy"}
                    or not source_event_ids
                )
                if authority_required and has_authority == has_non_authoritative:
                    violations.append(
                        CaseLintViolation(
                            code="memory_rule.authority_missing",
                            path=f"{path}.metadata",
                            message=(
                                "memory rule effect must mark exactly one of "
                                "authority_source or non_authoritative"
                            ),
                        )
                    )
        return violations

    def _validate_forbidden_terms_not_public(self) -> list[CaseLintViolation]:
        violations: list[CaseLintViolation] = []
        public_fields = [
            *(
                (f"clues.yaml({_mapping_str(clue, 'id')}).title", _mapping_str(clue, "title"))
                for clue in self.raw_case.clues
            ),
            *(
                (
                    f"clues.yaml({_mapping_str(clue, 'id')}).description",
                    _mapping_str(clue, "description"),
                )
                for clue in self.raw_case.clues
            ),
            *(
                (
                    f"world_info.yaml({_mapping_str(world_info, 'id')}).title",
                    _mapping_str(world_info, "title"),
                )
                for world_info in self.raw_case.world_info
            ),
            *(
                (
                    f"world_info.yaml({_mapping_str(world_info, 'id')}).description",
                    _mapping_str(world_info, "description"),
                )
                for world_info in self.raw_case.world_info
            ),
        ]
        for fact in self.raw_case.forbidden_facts:
            for term in _string_set(fact.get("blocked_terms")):
                normalized_term = _normalize_public_text(term)
                if not normalized_term:
                    continue
                for path, value in public_fields:
                    if value and normalized_term == _normalize_public_text(value):
                        violations.append(
                            CaseLintViolation(
                                code="forbidden_term.public_exact_match",
                                path=path,
                                message=(
                                    f"public field exactly matches forbidden fact "
                                    f"'{_mapping_str(fact, 'id')}' blocked term"
                                ),
                            )
                        )
        return violations


@dataclass(frozen=True)
class _ScenarioLintPackage:
    case_dir: Path
    scenario_path: Path
    case: CasePackage
    raw: Mapping[str, object]

    @property
    def case_id(self) -> str:
        return self.case.meta.id


def _read_yaml_list(path: Path) -> list[Mapping[str, object]]:
    loaded = _read_yaml(path)
    if loaded is None:
        return []
    if not isinstance(loaded, list):
        raise CaseLoadError(f"Expected YAML list at {path}")
    result: list[Mapping[str, object]] = []
    for index, item in enumerate(loaded):
        if not isinstance(item, Mapping):
            raise CaseLoadError(f"Expected mapping at {path}[{index}]")
        result.append({str(key): value for key, value in item.items()})
    return result


def _read_yaml_mapping(path: Path) -> Mapping[str, object]:
    loaded = _read_yaml(path)
    if not isinstance(loaded, Mapping):
        raise CaseLoadError(f"Expected YAML mapping at {path}")
    return {str(key): value for key, value in loaded.items()}


def _read_yaml(path: Path) -> object:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as exc:
        raise CaseLoadError(f"Invalid YAML in {path}: {exc}") from exc


def _has_unlock_conditions(conditions: object) -> bool:
    return any(
        bool(getattr(conditions, field_name))
        for field_name in (
            "phases",
            "completed_beats",
            "discovered_clues",
            "player_knowledge_ids",
            "player_world_info_ids",
        )
    )


def _hotspot_to_clues(package: CasePackage) -> dict[str, set[str]]:
    return {
        hotspot.id: set(hotspot.discover_clues)
        | {
            clue_id
            for unlock in hotspot.backtrack_unlocks
            for clue_id in unlock.clue_ids
        }
        for scene in package.scenes
        for hotspot in scene.hotspots
    }


def _player_facing_world_info_ids(
    package: CasePackage,
    raw_case: _RawCase,
) -> set[str]:
    ids = {
        world_info_id
        for clue in package.clues
        for world_info_id in clue.reveals_world_info
    }
    standard = raw_case.scenarios.get("standard_path.yaml")
    if standard is not None:
        ids.update(_string_set(standard.get("expected_final_player_world_info_ids")))
    return ids


def _raw_player_facing_world_info_ids(raw_case: _RawCase) -> set[str]:
    ids = {
        world_info_id
        for clue in raw_case.clues
        for world_info_id in _string_set(clue.get("reveals_world_info"))
    }
    standard = raw_case.scenarios.get("standard_path.yaml")
    if standard is not None:
        ids.update(_string_set(standard.get("expected_final_player_world_info_ids")))
    return ids


def _clue_ids_from_scenario_actions(
    scenario: Mapping[str, object],
    *,
    hotspot_to_clues: Mapping[str, set[str]],
) -> set[str]:
    clue_ids: set[str] = set()
    for step in _as_sequence(scenario.get("steps")):
        if not isinstance(step, Mapping):
            continue
        action = step.get("action")
        if not isinstance(action, Mapping):
            continue
        action_type = action.get("type")
        target_id = action.get("target_id")
        if action_type == "inspect" and isinstance(target_id, str):
            clue_ids.update(hotspot_to_clues.get(target_id, set()))
        clue_id = action.get("clue_id")
        if isinstance(clue_id, str):
            clue_ids.add(clue_id)
        subject_type = action.get("subject_type")
        subject_id = action.get("subject_id")
        if subject_type == "clue" and isinstance(subject_id, str):
            clue_ids.add(subject_id)
        clue_ids.update(item for item in _as_sequence(action.get("evidence_clue_ids")) if isinstance(item, str))
    return clue_ids


def _reachable_beat_ids(package: CasePackage) -> set[str]:
    direct_clue_ids = {
        clue_id
        for scene in package.scenes
        for hotspot in scene.hotspots
        for clue_id in hotspot.discover_clues
    }
    reachable_clue_ids = set(direct_clue_ids)
    reachable_beats: set[str] = set()
    changed = True
    while changed:
        changed = False
        for beat in package.narrative_rules.beats:
            if beat.id in reachable_beats:
                continue
            if not set(beat.all_completed) <= reachable_beats:
                continue
            if not set(beat.all_discovered) <= reachable_clue_ids:
                continue
            reachable_beats.add(beat.id)
            changed = True
        for scene in package.scenes:
            for hotspot in scene.hotspots:
                for unlock in hotspot.backtrack_unlocks:
                    if not set(unlock.conditions.completed_beats) <= reachable_beats:
                        continue
                    if not set(unlock.conditions.discovered_clues) <= reachable_clue_ids:
                        continue
                    before = len(reachable_clue_ids)
                    reachable_clue_ids.update(unlock.clue_ids)
                    changed = changed or len(reachable_clue_ids) != before
    return reachable_beats


def _blocks_first_inspection(
    hotspot: SceneHotspotConfig,
    unlock: BacktrackClueUnlockConfig,
) -> bool:
    return (
        hotspot.id in set(unlock.conditions.prior_inspected_hotspots)
        and unlock.conditions.min_prior_inspections >= 1
    )


def _allows_relationship_change(skill: NpcSkillConfig) -> bool:
    return ProposedActionType.RELATIONSHIP_CHANGE in set(skill.proposed_action_policy.allowed)


def _string_set(value: object) -> set[str]:
    return {item for item in _as_sequence(value) if isinstance(item, str)}


def _as_sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, str):
        return value
    return ()


def _as_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    return {}


def _as_mapping_sequence(value: object) -> Sequence[Mapping[str, object]]:
    return [item for item in _as_sequence(value) if isinstance(item, Mapping)]


def _mapping_str(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    return item if isinstance(item, str) else ""


def _raw_safe_fragments(world_info: Mapping[str, object]) -> Sequence[Mapping[str, object]]:
    claim_graph = _as_mapping(world_info.get("claim_graph"))
    return _as_mapping_sequence(claim_graph.get("safe_fragments"))


def _raw_hotspots(scenes: Iterable[Mapping[str, object]]) -> Sequence[Mapping[str, object]]:
    return [
        hotspot
        for scene in scenes
        for hotspot in _as_mapping_sequence(scene.get("hotspots"))
    ]


def _raw_has_unlock_conditions(conditions: object) -> bool:
    mapping = _as_mapping(conditions)
    return any(
        bool(mapping.get(field_name))
        for field_name in (
            "phases",
            "completed_beats",
            "discovered_clues",
            "player_knowledge_ids",
            "player_world_info_ids",
        )
    )


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def _normalize_public_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _escape_markdown_table(value: str) -> str:
    return value.replace("|", "\\|")


def _relpath(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)
