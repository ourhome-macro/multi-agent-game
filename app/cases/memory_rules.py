from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.cases.errors import CaseLoadError
from app.domain.models import MemoryDerivationRuleConfig


class MemoryDerivationRuleLoader:
    def __init__(self, *, app_rule_path: Path | None = None) -> None:
        self._app_rule_path = app_rule_path or (
            Path(__file__).resolve().parents[1]
            / "runtime"
            / "memory_derivation_rules.yaml"
        )

    def load(self, case_dir: Path) -> list[MemoryDerivationRuleConfig]:
        raw_rules: list[object] = []
        raw_rules.extend(self._read_rules(self._app_rule_path, required=False))
        raw_rules.extend(
            self._read_rules(case_dir / "memory_derivation_rules.yaml", required=False)
        )
        rules: list[MemoryDerivationRuleConfig] = []
        for index, raw_rule in enumerate(raw_rules):
            try:
                rules.append(MemoryDerivationRuleConfig.model_validate(raw_rule))
            except ValidationError as exc:
                raise CaseLoadError(
                    "Memory derivation rule schema validation failed "
                    f"for rule #{index + 1} in {case_dir}: {exc}"
                ) from exc
        return rules

    def _read_rules(self, path: Path, *, required: bool) -> list[object]:
        if not path.exists():
            if required:
                raise CaseLoadError(f"Required memory derivation rule file is missing: {path}")
            return []
        try:
            with path.open("r", encoding="utf-8") as file:
                loaded: Any = yaml.safe_load(file)
        except yaml.YAMLError as exc:
            raise CaseLoadError(f"Invalid YAML in {path}: {exc}") from exc
        if loaded is None:
            return []
        if not isinstance(loaded, list):
            raise CaseLoadError(f"Memory derivation rules must be a list: {path}")
        return list(loaded)
