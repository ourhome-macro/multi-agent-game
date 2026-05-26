from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.cases.errors import CaseLoadError
from app.domain.models import CasePackage

RELATIONSHIP_METRICS = {"trust", "suspicion", "fear", "intimacy", "hostility"}


class CaseLoader:
    def load(self, case_dir: Path) -> CasePackage:
        if not case_dir.exists():
            raise CaseLoadError(f"Case directory does not exist: {case_dir}")

        data = {
            "meta": self._read_yaml(case_dir / "case.yaml"),
            "characters": self._read_yaml(case_dir / "characters.yaml"),
            "scenes": self._read_yaml(case_dir / "scenes.yaml"),
            "clues": self._read_yaml(case_dir / "clues.yaml"),
            "relationships": self._read_yaml(case_dir / "relationships.yaml", default=[]),
            "forbidden_facts": self._read_yaml(case_dir / "forbidden_facts.yaml", default=[]),
            "mock_dialogues": self._read_yaml(case_dir / "mock_dialogues.yaml", default=[]),
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
        clue_ids = {clue.id for clue in package.clues}
        scene_ids = {scene.id for scene in package.scenes}
        dialogue_character_ids = {dialogue.character_id for dialogue in package.mock_dialogues}

        self._ensure_unique(
            "character",
            [character.id for character in package.characters],
            case_dir,
        )
        self._ensure_unique("clue", [clue.id for clue in package.clues], case_dir)
        self._ensure_unique("scene", [scene.id for scene in package.scenes], case_dir)
        self._ensure_unique(
            "mock dialogue character",
            [dialogue.character_id for dialogue in package.mock_dialogues],
            case_dir,
        )

        if not scene_ids:
            raise CaseLoadError(f"Case must define at least one scene: {case_dir}")
        if not character_ids:
            raise CaseLoadError(f"Case must define at least one character: {case_dir}")

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

        for clue in package.clues:
            for character_id in clue.related_characters:
                if character_id not in character_ids:
                    raise CaseLoadError(
                        f"Clue '{clue.id}' references unknown character '{character_id}'"
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

    def _ensure_unique(self, label: str, ids: list[str], case_dir: Path) -> None:
        duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
        if duplicates:
            raise CaseLoadError(
                f"Duplicate {label} ids in {case_dir}: {', '.join(duplicates)}"
            )
