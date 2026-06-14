from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.cases.errors import CaseLoadError
from app.cases.memory_rules import MemoryDerivationRuleLoader
from app.domain.models import (
    CasePackage,
    DiscoverClueAction,
    EventType,
    NarrativePhaseChangeAction,
    ProposedActionType,
    RelationshipChangeAction,
    SubjectType,
)

RELATIONSHIP_METRICS = {"trust", "suspicion", "fear", "intimacy", "hostility"}

# Player action events a memory derivation rule may trigger on. These are the
# event types wired into DerivedEventSystem's configured-rule dispatch.
MEMORY_RULE_TRIGGER_EVENT_TYPES = {
    EventType.PLAYER_ASKED_ABOUT.value,
    EventType.PLAYER_PRESENTED_CLUE.value,
    EventType.PLAYER_ACCUSED.value,
}
# Template variables a rule's memory_id / content may reference.
MEMORY_RULE_TEMPLATE_VARS = {
    "claim_id",
    "clue_id",
    "clue_title",
    "interaction_pressure",
    "knowledge_id",
    "scene_id",
    "source_event_id",
    "subject_id",
    "subject_type",
    "target_id",
    "target_name",
}
_TEMPLATE_TOKEN = re.compile(r"\{([^}]*)\}")


class CaseLoader:
    def load(self, case_dir: Path) -> CasePackage:
        if not case_dir.exists():
            raise CaseLoadError(f"Case directory does not exist: {case_dir}")

        data = {
            "meta": self._read_yaml(case_dir / "case.yaml"),
            "world_info": self._read_yaml(case_dir / "world_info.yaml", default=[]),
            "characters": self._read_yaml(case_dir / "characters.yaml"),
            "scenes": self._read_yaml(case_dir / "scenes.yaml"),
            "clues": self._read_yaml(case_dir / "clues.yaml"),
            "relationships": self._read_yaml(case_dir / "relationships.yaml", default=[]),
            "forbidden_facts": self._read_yaml(case_dir / "forbidden_facts.yaml", default=[]),
            "mock_dialogues": self._read_yaml(case_dir / "mock_dialogues.yaml", default=[]),
            "memory_derivation_rules": MemoryDerivationRuleLoader().load(case_dir),
            "narrative_rules": self._read_yaml(case_dir / "narrative_rules.yaml"),
            "solution_claims": self._read_yaml(
                case_dir / "solution_claims.yaml",
                default={"claims": []},
            ),
        }

        try:
            package = CasePackage.model_validate(data)
        except ValidationError as exc:
            message = f"Case package schema validation failed in {case_dir}: {exc}"
            raise CaseLoadError(message) from exc

        self._validate_references(package, case_dir)
        return package

    def _read_yaml(self, path: Path, default: Any | None = None) -> Any:
        if not path.exists():
            if default is not None:
                return default
            raise CaseLoadError(f"Required case config file is missing: {path}")

        try:
            with path.open("r", encoding="utf-8") as file:
                loaded = yaml.safe_load(file)
        except yaml.YAMLError as exc:
            raise CaseLoadError(f"Invalid YAML in {path}: {exc}") from exc

        if loaded is None:
            return default if default is not None else {}
        return loaded

    def _validate_references(self, package: CasePackage, case_dir: Path) -> None:
        character_ids = {character.id for character in package.characters}
        world_info_ids = {world_info.id for world_info in package.world_info}
        clue_ids = {clue.id for clue in package.clues}
        scene_ids = {scene.id for scene in package.scenes}
        dialogue_character_ids = {dialogue.character_id for dialogue in package.mock_dialogues}
        phase_ids = {phase.id for phase in package.narrative_rules.phases}
        beat_ids = {beat.id for beat in package.narrative_rules.beats}

        self._ensure_unique(
            "character",
            [character.id for character in package.characters],
            case_dir,
        )
        self._ensure_unique(
            "world info",
            [world_info.id for world_info in package.world_info],
            case_dir,
        )
        for world_info in package.world_info:
            self._validate_world_info_claim_patterns(world_info.id, world_info.claim_patterns)
        self._ensure_unique("clue", [clue.id for clue in package.clues], case_dir)
        self._ensure_unique("scene", [scene.id for scene in package.scenes], case_dir)
        self._ensure_unique(
            "narrative phase",
            [phase.id for phase in package.narrative_rules.phases],
            case_dir,
        )
        self._ensure_unique(
            "narrative beat",
            [beat.id for beat in package.narrative_rules.beats],
            case_dir,
        )
        self._ensure_unique(
            "mock dialogue character",
            [dialogue.character_id for dialogue in package.mock_dialogues],
            case_dir,
        )
        self._ensure_unique(
            "solution claim",
            [claim.id for claim in package.solution_claims.claims],
            case_dir,
        )

        if not scene_ids:
            raise CaseLoadError(f"Case must define at least one scene: {case_dir}")
        if not character_ids:
            raise CaseLoadError(f"Case must define at least one character: {case_dir}")
        if package.meta.initial_phase not in phase_ids:
            raise CaseLoadError(
                f"Case initial_phase '{package.meta.initial_phase}' is not declared in "
                "narrative_rules phases"
            )

        for scene in package.scenes:
            for character_id in scene.characters:
                if character_id not in character_ids:
                    raise CaseLoadError(
                        f"Scene '{scene.id}' references unknown character '{character_id}'"
                    )
            for hotspot in scene.hotspots:
                for clue_id in hotspot.discover_clues:
                    if clue_id not in clue_ids:
                        raise CaseLoadError(
                            f"Hotspot '{hotspot.id}' in scene '{scene.id}' references unknown clue "
                            f"'{clue_id}'"
                        )

        hotspot_ids = [hotspot.id for scene in package.scenes for hotspot in scene.hotspots]
        self._ensure_unique("hotspot", hotspot_ids, case_dir)
        reachable_clue_ids = {
            clue_id
            for scene in package.scenes
            for hotspot in scene.hotspots
            for clue_id in hotspot.discover_clues
        }

        for clue in package.clues:
            self._ensure_known_world_info(
                world_info_ids,
                clue.reveals_world_info,
                f"Clue '{clue.id}' reveals_world_info",
            )
            for character_id in clue.related_characters:
                if character_id not in character_ids:
                    raise CaseLoadError(
                        f"Clue '{clue.id}' references unknown character '{character_id}'"
                    )

        for character in package.characters:
            self._ensure_known_world_info(
                world_info_ids,
                list(character.private.disclosure_style.max_mode_by_world_info),
                f"Character '{character.id}' private disclosure_style max_mode_by_world_info",
            )
            for goal in character.private.goals:
                self._ensure_known_world_info(
                    world_info_ids,
                    goal.related_world_info_ids,
                    f"Character '{character.id}' private goal '{goal.id}' "
                    "related_world_info_ids",
                )
            for secret in character.private.secrets:
                self._ensure_known_clues(
                    clue_ids,
                    secret.related_clue_ids,
                    f"Character '{character.id}' private secret '{secret.id}' related_clue_ids",
                )
                self._ensure_known_world_info(
                    world_info_ids,
                    secret.related_world_info_ids,
                    f"Character '{character.id}' private secret '{secret.id}' "
                    "related_world_info_ids",
                )
            for knowledge in character.private.knowledge:
                self._ensure_known_clues(
                    clue_ids,
                    knowledge.related_clue_ids,
                    f"Character '{character.id}' private knowledge "
                    f"'{knowledge.id}' related_clue_ids",
                )
                self._ensure_known_world_info(
                    world_info_ids,
                    knowledge.related_world_info_ids,
                    f"Character '{character.id}' private knowledge "
                    f"'{knowledge.id}' related_world_info_ids",
                )

        for relationship in package.relationships:
            if relationship.source_id not in character_ids and relationship.source_id != "player":
                raise CaseLoadError(
                    f"Relationship references unknown source_id '{relationship.source_id}'"
                )
            if relationship.target_id not in character_ids and relationship.target_id != "player":
                raise CaseLoadError(
                    f"Relationship references unknown target_id '{relationship.target_id}'"
                )

        unknown_dialogues = dialogue_character_ids - character_ids
        if unknown_dialogues:
            raise CaseLoadError(
                f"Mock dialogue references unknown characters: {sorted(unknown_dialogues)}"
            )

        for dialogue in package.mock_dialogues:
            unknown_metrics = set(dialogue.relationship_delta_on_talk) - RELATIONSHIP_METRICS
            if unknown_metrics:
                raise CaseLoadError(
                    f"Mock dialogue for character '{dialogue.character_id}' references unknown "
                    f"relationship metrics: {sorted(unknown_metrics)}"
                )
            for reply in dialogue.replies:
                if reply.phase is not None and reply.phase not in phase_ids:
                    raise CaseLoadError(
                        f"Mock reply for character '{dialogue.character_id}' references unknown "
                        f"phase '{reply.phase}'"
                    )
                if reply.presented_clue is not None and reply.presented_clue not in clue_ids:
                    raise CaseLoadError(
                        f"Mock reply for character '{dialogue.character_id}' references unknown "
                        f"presented_clue '{reply.presented_clue}'"
                    )
                if reply.asked_subject_type == SubjectType.CLUE and (
                    reply.asked_subject_id not in clue_ids
                ):
                    raise CaseLoadError(
                        f"Mock reply for character '{dialogue.character_id}' references unknown "
                        f"asked clue '{reply.asked_subject_id}'"
                    )
                if reply.asked_subject_type == SubjectType.CHARACTER and (
                    reply.asked_subject_id not in character_ids
                ):
                    raise CaseLoadError(
                        f"Mock reply for character '{dialogue.character_id}' references unknown "
                        f"asked character '{reply.asked_subject_id}'"
                    )
                if reply.asked_subject_type == SubjectType.SCENE and (
                    reply.asked_subject_id not in scene_ids
                ):
                    raise CaseLoadError(
                        f"Mock reply for character '{dialogue.character_id}' references unknown "
                        f"asked scene '{reply.asked_subject_id}'"
                    )
                self._ensure_known_clues(
                    clue_ids,
                    reply.requires_discovered,
                    f"Mock reply for character '{dialogue.character_id}' requires",
                )
                self._ensure_known_clues(
                    clue_ids,
                    reply.missing_discovered,
                    f"Mock reply for character '{dialogue.character_id}' excludes",
                )
                unknown_min_metrics = set(reply.min_relationship) - RELATIONSHIP_METRICS
                unknown_max_metrics = set(reply.max_relationship) - RELATIONSHIP_METRICS
                if unknown_min_metrics or unknown_max_metrics:
                    raise CaseLoadError(
                        f"Mock reply for character '{dialogue.character_id}' references unknown "
                        "relationship metrics"
                    )
                reachable_clue_ids.update(
                    action.clue_id
                    for action in reply.proposed_actions
                    if isinstance(action, DiscoverClueAction)
                )
                for action in reply.proposed_actions:
                    self._validate_proposed_action(
                        action,
                        character_ids=character_ids,
                        clue_ids=clue_ids,
                        phase_ids=phase_ids,
                    )

        for claim in package.solution_claims.claims:
            if claim.target_id not in character_ids:
                raise CaseLoadError(
                    f"Solution claim '{claim.id}' references unknown target_id "
                    f"'{claim.target_id}'"
                )
            self._ensure_known_clues(
                clue_ids,
                claim.required_evidence,
                f"Solution claim '{claim.id}' required_evidence",
            )
            self._ensure_known_world_info(
                world_info_ids,
                claim.required_world_info,
                f"Solution claim '{claim.id}' required_world_info",
            )
            unknown_phases = sorted(set(claim.allowed_phases) - phase_ids)
            if unknown_phases:
                raise CaseLoadError(
                    f"Solution claim '{claim.id}' references unknown allowed phases: "
                    f"{unknown_phases}"
                )

        for fact in package.forbidden_facts:
            if fact.world_info_id is not None and fact.world_info_id not in world_info_ids:
                raise CaseLoadError(
                    f"Forbidden fact '{fact.id}' references unknown world_info_id "
                    f"'{fact.world_info_id}'"
                )
            if fact.reveal_phase is not None and fact.reveal_phase not in phase_ids:
                raise CaseLoadError(
                    f"Forbidden fact '{fact.id}' references unknown reveal_phase "
                    f"'{fact.reveal_phase}'"
                )

        for beat in package.narrative_rules.beats:
            if beat.phase is not None and beat.phase not in phase_ids:
                raise CaseLoadError(f"Beat '{beat.id}' references unknown phase '{beat.phase}'")
            if beat.next_phase is not None and beat.next_phase not in phase_ids:
                raise CaseLoadError(
                    f"Beat '{beat.id}' references unknown next_phase '{beat.next_phase}'"
                )
            if beat.trigger_payload and beat.trigger_event_type is None:
                raise CaseLoadError(
                    f"Beat '{beat.id}' trigger_payload requires trigger_event_type"
                )
            for required_beat_id in beat.all_completed:
                if required_beat_id not in beat_ids:
                    raise CaseLoadError(
                        f"Beat '{beat.id}' references unknown required beat "
                        f"'{required_beat_id}'"
                    )
                if required_beat_id == beat.id:
                    raise CaseLoadError(f"Beat '{beat.id}' cannot require itself")
            self._ensure_known_clues(
                clue_ids,
                beat.all_discovered,
                f"Beat '{beat.id}' all_discovered",
            )

        self._validate_memory_derivation_rules(
            package,
            character_ids=character_ids,
            clue_ids=clue_ids,
            scene_ids=scene_ids,
        )

        unreachable_clue_ids = clue_ids - reachable_clue_ids
        if unreachable_clue_ids:
            raise CaseLoadError(
                f"Clues are not reachable by any hotspot or mock proposed action: "
                f"{sorted(unreachable_clue_ids)}"
            )

    def _ensure_unique(self, label: str, ids: list[str], case_dir: Path) -> None:
        duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
        if duplicates:
            raise CaseLoadError(
                f"Duplicate {label} ids in {case_dir}: {', '.join(duplicates)}"
            )

    def _ensure_known_clues(
        self,
        clue_ids: set[str],
        referenced_ids: list[str],
        label: str,
    ) -> None:
        unknown_ids = sorted(set(referenced_ids) - clue_ids)
        if unknown_ids:
            raise CaseLoadError(f"{label} references unknown clues: {unknown_ids}")

    def _ensure_known_world_info(
        self,
        world_info_ids: set[str],
        referenced_ids: list[str],
        label: str,
    ) -> None:
        unknown_ids = sorted(set(referenced_ids) - world_info_ids)
        if unknown_ids:
            raise CaseLoadError(f"{label} references unknown world_info: {unknown_ids}")

    def _validate_memory_derivation_rules(
        self,
        package: CasePackage,
        *,
        character_ids: set[str],
        clue_ids: set[str],
        scene_ids: set[str],
    ) -> None:
        _ = scene_ids
        self._ensure_unique(
            "memory derivation rule",
            [rule.id for rule in package.memory_derivation_rules],
            self._case_dir(package),
        )
        for rule in package.memory_derivation_rules:
            if rule.trigger_type not in MEMORY_RULE_TRIGGER_EVENT_TYPES:
                raise CaseLoadError(
                    f"Memory derivation rule '{rule.id}' has unsupported "
                    f"trigger type '{rule.trigger_type}'"
                )
            if rule.target_match_id is not None and rule.target_match_id not in character_ids:
                raise CaseLoadError(
                    f"Memory derivation rule '{rule.id}' references unknown "
                    f"target_id '{rule.target_match_id}'"
                )
            if rule.subject_match_id is not None and rule.subject_match_id not in clue_ids:
                raise CaseLoadError(
                    f"Memory derivation rule '{rule.id}' references unknown "
                    f"subject_id '{rule.subject_match_id}'"
                )
            if rule.claim_id is not None and rule.trigger_type != EventType.PLAYER_ACCUSED.value:
                raise CaseLoadError(
                    f"Memory derivation rule '{rule.id}' uses claim_id but does not trigger "
                    f"on '{EventType.PLAYER_ACCUSED.value}'"
                )
            if not rule.produces:
                raise CaseLoadError(
                    f"Memory derivation rule '{rule.id}' must produce at least one memory effect"
                )
            effect_ids = [effect.memory_id_pattern for effect in rule.produces]
            self._ensure_unique(
                f"memory effect in rule '{rule.id}'",
                effect_ids,
                self._case_dir(package),
            )
            for effect in rule.produces:
                self._validate_memory_template(
                    rule.id,
                    "memory_id",
                    effect.memory_id_pattern,
                )
                self._validate_memory_template(
                    rule.id,
                    "content",
                    effect.content_pattern,
                )
                self._validate_memory_template(
                    rule.id,
                    "owner_character_id",
                    effect.owner_character_id or "",
                )
                for visible_id in effect.visible_to_character_ids:
                    self._validate_memory_template(
                        rule.id,
                        "visible_to_character_ids",
                        visible_id,
                    )
                for source_event_id in effect.source_event_ids:
                    self._validate_memory_template(
                        rule.id,
                        "source_event_ids",
                        source_event_id,
                    )
                for source_memory_id in effect.source_memory_ids or []:
                    self._validate_memory_template(
                        rule.id,
                        "source_memory_ids",
                        source_memory_id,
                    )

    def _validate_memory_template(
        self,
        rule_id: str,
        field_name: str,
        value: str,
    ) -> None:
        for token in _TEMPLATE_TOKEN.findall(value):
            if token not in MEMORY_RULE_TEMPLATE_VARS:
                raise CaseLoadError(
                    f"Memory derivation rule '{rule_id}' {field_name} uses unknown template "
                    f"variable '{{{token}}}'"
                )

    def _case_dir(self, package: CasePackage) -> str:
        return package.meta.id

    def _validate_world_info_claim_patterns(
        self,
        world_info_id: str,
        claim_patterns: list[str],
    ) -> None:
        for pattern in claim_patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise CaseLoadError(
                    f"WorldInfo '{world_info_id}' has invalid claim_pattern "
                    f"'{pattern}': {exc}"
                ) from exc

    def _validate_proposed_action(
        self,
        action: DiscoverClueAction | RelationshipChangeAction | NarrativePhaseChangeAction,
        *,
        character_ids: set[str],
        clue_ids: set[str],
        phase_ids: set[str],
    ) -> None:
        valid_actor_ids = character_ids | {"player"}
        if action.type == ProposedActionType.DISCOVER_CLUE and action.clue_id not in clue_ids:
            raise CaseLoadError(f"Mock proposed action references unknown clue '{action.clue_id}'")
        if action.type == ProposedActionType.RELATIONSHIP_CHANGE:
            if action.source_id not in valid_actor_ids:
                raise CaseLoadError(
                    f"Mock proposed relationship action references unknown source_id "
                    f"'{action.source_id}'"
                )
            if action.target_id not in valid_actor_ids:
                raise CaseLoadError(
                    f"Mock proposed relationship action references unknown target_id "
                    f"'{action.target_id}'"
                )
            unknown_metrics = set(action.deltas) - RELATIONSHIP_METRICS
            if unknown_metrics:
                raise CaseLoadError(
                    f"Mock proposed relationship action references unknown metrics: "
                    f"{sorted(unknown_metrics)}"
                )
        if (
            action.type == ProposedActionType.NARRATIVE_PHASE_CHANGE
            and action.phase not in phase_ids
        ):
            raise CaseLoadError(
                f"Mock proposed phase action references unknown phase '{action.phase}'"
            )
